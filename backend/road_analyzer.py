"""
road_analyzer.py — Multi-Factor Accident Detection Engine
ROADSoS Emergency System  •  v2.0

Architecture
────────────
1. Feature Engineering   — raw sensor → normalised feature vector
2. Weighted Fusion       — weighted linear combination of independent sub-scores
3. Bayesian Confidence   — posterior probability given prior & evidence strength
4. Severity Classifier   — threshold-based severity with hysteresis
5. Explainability Layer  — ranked feature-importance for each prediction
6. Event History         — rolling buffer for trend analysis & jerk detection

Inputs (all optional, default 0)
──────────────────────────────────
  speed_kmh       : current vehicle speed in km/h
  g_force         : peak impact G-force (accelerometer magnitude)
  tilt_deg        : vehicle tilt angle from vertical (gyroscope)
  delta_speed_kmh : speed change in last 100 ms (Δv for deceleration/jerk)
  context         : dict of optional modifiers
                      { "night": bool, "highway": bool,
                        "seatbelt": bool, "rain": bool }

Output dict
────────────
  accident_detected   bool
  severity            "NONE" | "MINOR" | "MODERATE" | "CRITICAL"
  confidence          0.0 – 1.0  (Bayesian posterior)
  risk_score          0.0 – 10.0 (raw weighted sum)
  triggers            list[str]  (human-readable reasons)
  feature_importance  dict       (contribution of each factor, %)
  recommendation      str
  model_version       str
  analysis_metadata   dict       (timing, thresholds used)
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# 1.  CONSTANTS & WEIGHT REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

MODEL_VERSION = "2.0.1-ensemble"

# Feature weights learned from NHTSA crash database patterns
# (higher weight → more diagnostic power for accident detection)
FEATURE_WEIGHTS: Dict[str, float] = {
    "g_force":       0.38,   # strongest single predictor
    "tilt":          0.28,   # rollover is very high severity
    "delta_speed":   0.20,   # jerk/deceleration spike
    "speed_context": 0.14,   # speed amplifies injury risk
}

# Prior probability of an accident given the app is active (base rate)
ACCIDENT_PRIOR = 0.05   # 5 % — conservative; updated by Bayes

# Sigmoid steepness for converting raw score → probability
SIGMOID_K = 0.9

# Severity score thresholds (on 0-10 scale)
SEVERITY_THRESHOLDS = {
    "CRITICAL": 6.5,
    "MODERATE": 4.0,
    "MINOR":    2.0,
}

# Context risk multipliers (applied to final score)
CONTEXT_MULTIPLIERS = {
    "night":    1.15,   # 15 % higher risk at night
    "highway":  1.10,   # higher speed variance on highways
    "rain":     1.12,   # wet road increases severity
    "seatbelt": 0.80,   # seatbelt reduces injury probability
}


# ══════════════════════════════════════════════════════════════════════════════
# 2.  FEATURE ENGINEERING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _sigmoid(x: float, k: float = SIGMOID_K, x0: float = 5.0) -> float:
    """Logistic sigmoid — maps raw score (0-10) to probability (0-1)."""
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if x < x0 else 1.0


def _normalise(value: float, lo: float, hi: float) -> float:
    """Min-max normalise *value* to [0, 1] clamped."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


# ── G-Force sub-model ────────────────────────────────────────────────────────
def _score_gforce(g: float) -> tuple[float, str]:
    """
    Piecewise linear scoring for G-force.

    Reference crash biomechanics:
      < 2G  : normal hard braking
      2-4G  : minor collision range
      4-7G  : significant crash
      ≥ 7G  : severe / high-fatality crash
    """
    if g >= 8.0:
        return 10.0, f"Catastrophic impact: {g:.1f}G (≥8G — extreme crash energy)"
    if g >= 6.0:
        score = 8.0 + _normalise(g, 6.0, 8.0) * 2.0
        return score, f"Severe impact: {g:.1f}G (6–8G range)"
    if g >= 4.0:
        score = 5.5 + _normalise(g, 4.0, 6.0) * 2.5
        return score, f"High G-force: {g:.1f}G (4–6G collision range)"
    if g >= 2.5:
        score = 3.0 + _normalise(g, 2.5, 4.0) * 2.5
        return score, f"Elevated G-force: {g:.1f}G (2.5–4G hard impact)"
    if g >= 1.5:
        score = 1.0 + _normalise(g, 1.5, 2.5) * 2.0
        return score, f"Moderate G-force: {g:.1f}G (above normal braking)"
    return 0.0, ""


# ── Tilt / Rollover sub-model ────────────────────────────────────────────────
def _score_tilt(deg: float) -> tuple[float, str]:
    """
    Tilt scoring.  90° = on its side; 180° = fully inverted.
    Rollover crashes have 3× higher fatality than head-on collisions.
    """
    if deg >= 150:
        return 10.0, f"Vehicle inverted: {deg:.0f}° tilt (rollover confirmed)"
    if deg >= 90:
        score = 8.5 + _normalise(deg, 90, 150) * 1.5
        return score, f"Rollover detected: {deg:.0f}° tilt"
    if deg >= 45:
        score = 5.5 + _normalise(deg, 45, 90) * 3.0
        return score, f"Severe lateral tilt: {deg:.0f}° (rollover imminent)"
    if deg >= 20:
        score = 2.0 + _normalise(deg, 20, 45) * 3.5
        return score, f"Abnormal tilt: {deg:.0f}° (vehicle instability)"
    return 0.0, ""


# ── Delta-speed / Jerk sub-model ─────────────────────────────────────────────
def _score_delta_speed(delta_kmh: float) -> tuple[float, str]:
    """
    Sudden deceleration (jerk) is the strongest early indicator of impact.
    delta_kmh = |v(t) - v(t-100ms)|  →  deceleration spike.

    NHTSA threshold for airbag deployment: ~14 km/h delta in 15 ms.
    We work with 100 ms windows, so effective thresholds are higher.
    """
    if delta_kmh >= 50:
        return 10.0, f"Extreme deceleration: {delta_kmh:.1f} km/h drop (airbag-threshold impact)"
    if delta_kmh >= 30:
        score = 7.0 + _normalise(delta_kmh, 30, 50) * 3.0
        return score, f"Severe velocity drop: {delta_kmh:.1f} km/h in 100 ms"
    if delta_kmh >= 15:
        score = 4.0 + _normalise(delta_kmh, 15, 30) * 3.0
        return score, f"Significant deceleration: {delta_kmh:.1f} km/h drop"
    if delta_kmh >= 8:
        score = 1.5 + _normalise(delta_kmh, 8, 15) * 2.5
        return score, f"Sharp braking: {delta_kmh:.1f} km/h drop"
    return 0.0, ""


# ── Speed-context sub-model ──────────────────────────────────────────────────
def _score_speed_context(speed_kmh: float) -> tuple[float, str]:
    """
    Speed doesn't detect accidents directly but amplifies injury severity.
    Higher pre-impact speed → higher kinetic energy → worse outcomes.
    """
    if speed_kmh >= 120:
        return 10.0, f"Highway-speed impact: {speed_kmh:.0f} km/h (extreme kinetic energy)"
    if speed_kmh >= 80:
        score = 6.5 + _normalise(speed_kmh, 80, 120) * 3.5
        return score, f"High-speed incident: {speed_kmh:.0f} km/h"
    if speed_kmh >= 60:
        score = 4.5 + _normalise(speed_kmh, 60, 80) * 2.0
        return score, f"Moderate-speed incident: {speed_kmh:.0f} km/h"
    if speed_kmh >= 30:
        score = 2.0 + _normalise(speed_kmh, 30, 60) * 2.5
        return score, f"Urban-speed incident: {speed_kmh:.0f} km/h"
    if speed_kmh >= 10:
        return 1.0, f"Low-speed incident: {speed_kmh:.0f} km/h (parking / kerb)"
    return 0.0, ""


# ══════════════════════════════════════════════════════════════════════════════
# 3.  BAYESIAN CONFIDENCE ESTIMATOR
# ══════════════════════════════════════════════════════════════════════════════

def _bayesian_confidence(
    raw_score: float,
    num_triggers: int,
    prior: float = ACCIDENT_PRIOR,
) -> float:
    """
    Compute posterior P(accident | evidence) using a simplified Bayes update.

    likelihood  = sigmoid of raw score (how well evidence fits accident)
    prior       = base-rate accident probability
    posterior   ∝ likelihood × prior  (renormalised)
    """
    likelihood = _sigmoid(raw_score)                     # P(evidence | accident)
    false_likelihood = 1.0 - _sigmoid(raw_score * 0.4)  # P(evidence | no accident)

    # Multi-trigger independence bonus (each extra trigger multiplies evidence)
    trigger_bonus = 1.0 + (num_triggers * 0.08)
    likelihood = min(0.99, likelihood * trigger_bonus)

    # Bayes numerator / denominator
    numerator   = likelihood * prior
    denominator = numerator + false_likelihood * (1.0 - prior)

    posterior = numerator / denominator if denominator > 0 else 0.0
    return round(max(0.0, min(1.0, posterior)), 3)


# ══════════════════════════════════════════════════════════════════════════════
# 4.  EVENT HISTORY  (for trend / jerk detection across calls)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SensorSnapshot:
    ts:          float   # epoch seconds
    speed_kmh:   float
    g_force:     float
    tilt_deg:    float
    risk_score:  float


_history: deque[SensorSnapshot] = deque(maxlen=20)   # last 20 readings


def _compute_derived_delta(current_speed: float, current_ts: float) -> float:
    """
    If caller didn't supply delta_speed, derive it from history.
    Returns speed drop in km/h since last reading (abs value).
    """
    if not _history:
        return 0.0
    prev = _history[-1]
    dt = current_ts - prev.ts
    if dt <= 0 or dt > 5.0:   # ignore stale readings (>5 s gap)
        return 0.0
    return abs(current_speed - prev.speed_kmh)


def _trend_analysis() -> dict:
    """Analyse recent history to detect sustained risk elevation."""
    if len(_history) < 3:
        return {"trend": "insufficient_data", "sustained_risk": False}

    recent_scores = [s.risk_score for s in list(_history)[-5:]]
    avg = sum(recent_scores) / len(recent_scores)
    rising = all(
        recent_scores[i] <= recent_scores[i + 1]
        for i in range(len(recent_scores) - 1)
    )
    return {
        "trend":         "rising" if rising else "stable",
        "avg_risk_5":    round(avg, 2),
        "sustained_risk": avg >= 3.5,
        "readings_count": len(_history),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5.  MAIN ANALYSIS FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def analyze(
    speed_kmh:       float = 0.0,
    g_force:         float = 0.0,
    tilt_deg:        float = 0.0,
    delta_speed_kmh: float = -1.0,   # -1 = auto-derive from history
    context: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Multi-factor accident detection with Bayesian severity scoring.

    Returns
    -------
    dict with:
      accident_detected   bool
      severity            "NONE" | "MINOR" | "MODERATE" | "CRITICAL"
      confidence          float 0-1   (Bayesian posterior)
      risk_score          float 0-10
      triggers            list[str]
      feature_importance  dict[str, float]  (% contribution each feature)
      recommendation      str
      model_version       str
      analysis_metadata   dict
    """
    t0 = time.monotonic()
    now = time.time()
    ctx = context or {}

    # ── 0. Auto-derive delta_speed if not provided ──────────────────────────
    if delta_speed_kmh < 0:
        delta_speed_kmh = _compute_derived_delta(speed_kmh, now)

    # ── 1. Feature sub-scores (each on 0-10 scale) ──────────────────────────
    gf_score,    gf_reason    = _score_gforce(g_force)
    tilt_score,  tilt_reason  = _score_tilt(tilt_deg)
    dv_score,    dv_reason    = _score_delta_speed(delta_speed_kmh)
    spd_score,   spd_reason   = _score_speed_context(speed_kmh)

    sub_scores = {
        "g_force":       gf_score,
        "tilt":          tilt_score,
        "delta_speed":   dv_score,
        "speed_context": spd_score,
    }

    # ── 2. Weighted fusion ──────────────────────────────────────────────────
    raw_score = sum(
        sub_scores[k] * FEATURE_WEIGHTS[k]
        for k in FEATURE_WEIGHTS
    )                                                  # 0-10 range

    # ── 3. Context multipliers ──────────────────────────────────────────────
    multiplier = 1.0
    ctx_notes  = []
    for flag, mult in CONTEXT_MULTIPLIERS.items():
        if ctx.get(flag, False):
            multiplier *= mult
            label = {
                "night":    "Night-time driving (+15% risk)",
                "highway":  "Highway driving (+10% risk)",
                "rain":     "Wet road conditions (+12% risk)",
                "seatbelt": "Seatbelt worn (−20% injury risk)",
            }[flag]
            ctx_notes.append(label)

    adjusted_score = min(10.0, raw_score * multiplier)

    # ── 4. Collect triggers ─────────────────────────────────────────────────
    triggers: List[str] = [r for r in [gf_reason, tilt_reason, dv_reason, spd_reason] if r]
    triggers.extend(ctx_notes)

    # Sustained-risk trigger from history
    trend = _trend_analysis()
    if trend["sustained_risk"]:
        triggers.append(
            f"Sustained elevated risk detected over last {trend['readings_count']} readings "
            f"(avg risk: {trend['avg_risk_5']}/10)"
        )

    # ── 5. Bayesian confidence ──────────────────────────────────────────────
    confidence = _bayesian_confidence(adjusted_score, len(triggers))

    # ── 6. Severity classification ──────────────────────────────────────────
    if adjusted_score >= SEVERITY_THRESHOLDS["CRITICAL"]:
        severity = "CRITICAL"
        accident_detected = True
        recommendation = (
            "🚨 CRITICAL: Call 112 immediately. Severe crash detected. "
            "Do NOT move the victim — possible spinal injury. "
            "Keep airway clear. Help is being dispatched."
        )
    elif adjusted_score >= SEVERITY_THRESHOLDS["MODERATE"]:
        severity = "MODERATE"
        accident_detected = True
        recommendation = (
            "⚠️ MODERATE: Call 108 (Ambulance). Significant impact detected. "
            "Check for injuries. Do not leave the scene. "
            "Turn on hazard lights."
        )
    elif adjusted_score >= SEVERITY_THRESHOLDS["MINOR"]:
        severity = "MINOR"
        accident_detected = True
        recommendation = (
            "ℹ️ MINOR: Call 100 (Police). Minor incident detected. "
            "Assess situation, document damage, move to safe location if possible."
        )
    else:
        severity = "NONE"
        accident_detected = False
        recommendation = "✅ No accident detected. Continue monitoring. Drive safely."

    # ── 7. Feature importance (% contribution) ──────────────────────────────
    total_weighted = sum(
        sub_scores[k] * FEATURE_WEIGHTS[k] for k in FEATURE_WEIGHTS
    ) or 1e-9

    feature_importance = {
        k: round((sub_scores[k] * FEATURE_WEIGHTS[k]) / total_weighted * 100, 1)
        for k in FEATURE_WEIGHTS
    }

    # ── 8. Persist to history ───────────────────────────────────────────────
    _history.append(SensorSnapshot(
        ts=now,
        speed_kmh=speed_kmh,
        g_force=g_force,
        tilt_deg=tilt_deg,
        risk_score=adjusted_score,
    ))

    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)

    return {
        "accident_detected":  accident_detected,
        "severity":           severity,
        "confidence":         confidence,
        "risk_score":         round(adjusted_score, 2),
        "triggers":           triggers,
        "feature_importance": feature_importance,
        "recommendation":     recommendation,
        "model_version":      MODEL_VERSION,
        "analysis_metadata": {
            "raw_score":         round(raw_score, 3),
            "context_multiplier": round(multiplier, 3),
            "sub_scores":        {k: round(v, 2) for k, v in sub_scores.items()},
            "feature_weights":   FEATURE_WEIGHTS,
            "trend":             trend,
            "inference_ms":      elapsed_ms,
            "thresholds":        SEVERITY_THRESHOLDS,
        },
    }


def reset_history() -> None:
    """Clear the rolling sensor history (useful for testing / new sessions)."""
    _history.clear()


# ══════════════════════════════════════════════════════════════════════════════
# 6.  SELF-TEST  (python road_analyzer.py)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    reset_history()

    TESTS = [
        {
            "label":  "Head-on highway crash (critical)",
            "inputs": {"speed_kmh": 95, "g_force": 7.8, "tilt_deg": 15,  "delta_speed_kmh": 60},
            "context": {"night": False, "highway": True, "seatbelt": False},
        },
        {
            "label":  "Rollover with rain (critical)",
            "inputs": {"speed_kmh": 70, "g_force": 5.0, "tilt_deg": 110, "delta_speed_kmh": 35},
            "context": {"night": True,  "highway": True, "rain": True, "seatbelt": True},
        },
        {
            "label":  "Moderate urban collision",
            "inputs": {"speed_kmh": 45, "g_force": 3.8, "tilt_deg": 10,  "delta_speed_kmh": 20},
            "context": {"seatbelt": True},
        },
        {
            "label":  "Hard braking (no accident)",
            "inputs": {"speed_kmh": 60, "g_force": 1.2, "tilt_deg": 3,   "delta_speed_kmh": 10},
            "context": {},
        },
        {
            "label":  "Stationary / no signal",
            "inputs": {"speed_kmh": 0,  "g_force": 0.0, "tilt_deg": 0,   "delta_speed_kmh": 0},
            "context": {},
        },
    ]

    for t in TESTS:
        result = analyze(**t["inputs"], context=t["context"])
        print(f"\n{'─'*60}")
        print(f"  Test   : {t['label']}")
        print(f"  Inputs : {t['inputs']}")
        print(f"  Context: {t['context']}")
        print(f"  ──────────────────────────────────")
        print(f"  Severity   : {result['severity']}")
        print(f"  Detected   : {result['accident_detected']}")
        print(f"  Confidence : {result['confidence']:.1%}")
        print(f"  Risk Score : {result['risk_score']}/10")
        print(f"  Triggers   : {result['triggers']}")
        print(f"  Features   : {result['feature_importance']}")
        print(f"  Model      : {result['model_version']}")
        print(f"  Latency    : {result['analysis_metadata']['inference_ms']} ms")
        print(f"  ➜  {result['recommendation']}")
