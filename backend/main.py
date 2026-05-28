"""
main.py — ROADSoS FastAPI Backend v7.0.0
Emergency Response Platform — Production Ready
"""
import time
import math
import os
import uuid
import requests
import logging

from dotenv import load_dotenv
load_dotenv()  # Load .env before anything reads os.getenv()

from fastapi import FastAPI, Query, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from services.call_service import make_call
from services.whatsapp_service import send_whatsapp
from services.sms_service import send_sms
from road_analyzer import analyze as analyze_accident

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roadsos")

app = FastAPI(title="ROADSoS API", version="7.0.0")

# ─────────────────────────────────────────────
# CORS — allow all origins
# ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# CONFIG — all from environment variables
# ─────────────────────────────────────────────
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
TWILIO_SID        = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN      = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE      = os.getenv("TWILIO_PHONE_NUMBER", "")
FROM_WHATSAPP     = os.getenv("FROM_WHATSAPP", "whatsapp:+14155238886")
PINK_POLICE_NUM   = os.getenv("PINK_POLICE_NUMBER", "1091")  # Women helpline

FAMILY_CONTACTS = [
    "+917232062340",   # Primary contact
    "+916205958187",   # Secondary contact
    # NOTE: For Twilio trial — each number must be verified at twilio.com
    # WhatsApp sandbox: each number must text 'join receive-attention' to +14155238886
]

# ─────────────────────────────────────────────
# IN-MEMORY STATE
# ─────────────────────────────────────────────
sos_events: List[dict] = []
active_sos: Optional[dict] = None

# ─────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────
class SOSRequest(BaseModel):
    lat: float
    lng: float
    channels: Optional[List[str]] = None
    source: Optional[str] = "manual"
    cancel_token: Optional[str] = None
    nearest_hospital: Optional[dict] = None

class CancelRequest(BaseModel):
    cancel_token: str
    reason: Optional[str] = "User cancelled"

class DetectRequest(BaseModel):
    speed_kmh: float = 0.0
    g_force: float = 0.0
    tilt_deg: float = 0.0
    delta_speed_kmh: float = 0.0
    context: Optional[dict] = None

class WomenSOSRequest(BaseModel):
    lat: float
    lng: float
    contacts: Optional[List[str]] = None   # Override family contacts if provided

# ─────────────────────────────────────────────
# HELPER — Haversine distance (km)
# ─────────────────────────────────────────────
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ─────────────────────────────────────────────
# HELPER — Google Places Nearby Search (single type)
# ─────────────────────────────────────────────
def _google_nearby(lat: float, lng: float, place_type: str,
                   radius: int = 8000, keyword: str = "") -> list:
    """Call Google Places nearbysearch for one type. Returns list of services."""
    if not GOOGLE_API_KEY:
        log.warning("GOOGLE_API_KEY not set — skipping Google Places call")
        return []

    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": place_type,
        "key": GOOGLE_API_KEY,
    }
    if keyword:
        params["keyword"] = keyword

    try:
        res = requests.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            params=params, timeout=8
        )
        data = res.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            log.warning(f"Google Places [{place_type}] status: {data.get('status')}")
            return []
        return data.get("results", [])
    except Exception as e:
        log.error(f"Google Places error [{place_type}]: {e}")
        return []

# ─────────────────────────────────────────────
# HELPER — Convert Google result → service dict
# ─────────────────────────────────────────────
def _google_to_service(result: dict, category: str, user_lat: float, user_lng: float) -> dict:
    hlat = result["geometry"]["location"]["lat"]
    hlng = result["geometry"]["location"]["lng"]
    d    = haversine_km(user_lat, user_lng, hlat, hlng)
    sid  = (hash(result.get("place_id", result.get("name", ""))) & 0x7FFFFFFF) % 900000 + 100
    return {
        "id":           sid,
        "name":         result.get("name", "Unknown"),
        "category":     category,
        "address":      result.get("vicinity", "Nearby"),
        "lat":          hlat,
        "lng":          hlng,
        "phone":        result.get("formatted_phone_number", ""),
        "rating":       result.get("rating"),
        "distance_km":  round(d, 2),
        "eta_minutes":  max(3, math.ceil((d / 40) * 60)),
        "_dist":        d * 1000,
    }

# ─────────────────────────────────────────────
# HELPER — Query Overpass (free, no key needed)
# ─────────────────────────────────────────────
def _overpass_services(lat: float, lng: float, radius: int = 8000) -> list:
    query = f"""[out:json][timeout:12];
(
  node["amenity"="hospital"](around:{radius},{lat},{lng});
  node["amenity"="police"](around:{radius},{lat},{lng});
  node["amenity"="fire_station"](around:{radius},{lat},{lng});
  node["shop"="car_repair"](around:{radius},{lat},{lng});
  way["amenity"="hospital"](around:{radius},{lat},{lng});
  way["amenity"="police"](around:{radius},{lat},{lng});
  way["amenity"="fire_station"](around:{radius},{lat},{lng});
)->.all;
(.all;>;);
out center;"""
    cat_map = {
        "hospital":    "hospital",
        "police":      "police",
        "fire_station":"fire",
        "car_repair":  "towing",
    }
    try:
        res  = requests.post("https://overpass-api.de/api/interpreter", data=query, timeout=12)
        data = res.json()
        seen, services = set(), []
        for el in data.get("elements", []):
            tags    = el.get("tags", {})
            amenity = tags.get("amenity") or tags.get("shop")
            if not amenity or amenity not in cat_map:
                continue
            name = tags.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            slat = el.get("lat") or (el.get("center") or {}).get("lat")
            slng = el.get("lon") or (el.get("center") or {}).get("lon")
            if not slat or not slng:
                continue
            d = haversine_km(lat, lng, slat, slng)
            services.append({
                "id":          (hash(name) & 0x7FFFFFFF) % 900000 + 100,
                "name":        name,
                "category":    cat_map[amenity],
                "address":     ", ".join(filter(None, [tags.get("addr:street"), tags.get("addr:city")])) or "Nearby",
                "lat":         slat,
                "lng":         slng,
                "phone":       tags.get("phone") or tags.get("contact:phone") or "",
                "distance_km": round(d, 2),
                "eta_minutes": max(3, math.ceil((d / 40) * 60)),
                "_dist":       d * 1000,
            })
        services.sort(key=lambda x: x["distance_km"])
        return services
    except Exception as e:
        log.error(f"Overpass error: {e}")
        return []

# ─────────────────────────────────────────────
# HELPER — get services for ONE category
#   Google Places → Overpass fallback
# ─────────────────────────────────────────────
def _get_category(lat: float, lng: float, place_type: str, category: str,
                  radius: int = 8000, keyword: str = "") -> list:
    results = _google_nearby(lat, lng, place_type, radius, keyword)
    if results:
        services = [_google_to_service(r, category, lat, lng) for r in results[:15]]
        services.sort(key=lambda x: x["distance_km"])
        log.info(f"[{category}] Google returned {len(services)} results")
        return services

    # Overpass fallback for this category
    all_op = _overpass_services(lat, lng, radius)
    filtered = [s for s in all_op if s["category"] == category]
    log.info(f"[{category}] Overpass returned {len(filtered)} results")
    return filtered

# ─────────────────────────────────────────────
# HELPER — Twilio call with retry
# ─────────────────────────────────────────────
def _call_with_retry(number: str, message: str, retries: int = 2) -> dict:
    for attempt in range(1, retries + 1):
        try:
            sid = make_call(number, message)
            return {"number": number, "status": "success", "attempt": attempt, "sid": sid}
        except Exception as e:
            log.error(f"Twilio call error (attempt {attempt}): {e}")
            if attempt < retries:
                time.sleep(1)
    return {"number": number, "status": "failed", "attempt": retries}

# ─────────────────────────────────────────────
# HELPER — Fire SOS across all channels
# ─────────────────────────────────────────────
def _fire_sos(lat: float, lng: float, channels: Optional[List[str]],
              source: str, nearest_hospital_hint: Optional[dict] = None,
              contacts: Optional[List[str]] = None) -> dict:
    global active_sos

    enabled  = set(channels) if channels else {"call_112", "call_108", "whatsapp", "sms", "family_call", "share"}
    targets  = contacts if contacts else FAMILY_CONTACTS

    timestamp    = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cancel_token = str(uuid.uuid4())
    maps_link    = f"https://maps.google.com/?q={lat},{lng}"

    # Nearest hospital: frontend hint > live Google > Overpass
    if nearest_hospital_hint and nearest_hospital_hint.get("name"):
        nearest = nearest_hospital_hint
        if nearest.get("lat") and nearest.get("lng"):
            d = haversine_km(lat, lng, nearest["lat"], nearest["lng"])
            nearest = {**nearest, "distance_km": round(d, 2)}
        nearby_hospitals = [nearest]
    else:
        hospitals = _get_category(lat, lng, "hospital", "hospital")
        nearest   = hospitals[0] if hospitals else None
        nearby_hospitals = hospitals[:3]

    hospital_info = f"{nearest['name']} ({nearest['distance_km']}km away)" if nearest else "Unknown"

    voice_msg = (
        f"EMERGENCY SOS ALERT from ROADSoS. "
        f"Accident detected. Location: {maps_link}. "
        f"Nearest hospital: {hospital_info}. Please respond immediately."
    )
    wa_msg = (
        f"🚨 *EMERGENCY SOS ALERT*\n\n"
        f"📍 Location: {maps_link}\n"
        f"🏥 Nearest Hospital: {hospital_info}\n"
        f"📞 Coordinates: {lat:.5f}, {lng:.5f}\n\n"
        f"_Sent via ROADSoS Emergency System_"
    )
    sms_msg = f"SOS ALERT - ROADSoS. Location: {maps_link}. Hospital: {hospital_info}."

    channel_results = {}

    # ── Family Voice Calls ───────────────────────────────
    if "family_call" in enabled:
        call_results = []
        for i, num in enumerate(targets):
            result = _call_with_retry(num, voice_msg, retries=2)
            result["name"] = f"Family Contact {i + 1}"
            call_results.append(result)
        channel_results["family_call"] = {
            "channel": "family_call", "label": "Family Voice Calls",
            "results": call_results,
            "status": "success" if any(r["status"] == "success" for r in call_results) else "failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    else:
        channel_results["family_call"] = {"channel": "family_call", "status": "skipped"}

    # ── WhatsApp ─────────────────────────────────────────
    if "whatsapp" in enabled:
        wa_results = []
        for num in targets:
            try:
                sid = send_whatsapp(num, wa_msg)
                wa_results.append({"number": num, "status": "sent", "sid": sid})
            except Exception as e:
                log.error(f"WhatsApp error: {e}")
                wa_results.append({"number": num, "status": "failed", "error": str(e)})
        channel_results["whatsapp"] = {
            "channel": "whatsapp", "label": "WhatsApp Alerts",
            "results": wa_results,
            "status": "success" if any(r["status"] == "sent" for r in wa_results) else "failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    else:
        channel_results["whatsapp"] = {"channel": "whatsapp", "status": "skipped"}

    # ── SMS ──────────────────────────────────────────────
    if "sms" in enabled:
        sms_results = []
        for num in targets:
            try:
                sid = send_sms(num, sms_msg)
                sms_results.append({"number": num, "status": "sent", "sid": sid})
            except Exception as e:
                log.error(f"SMS error: {e}")
                sms_results.append({"number": num, "status": "failed", "error": str(e)})
        channel_results["sms"] = {
            "channel": "sms", "label": "SMS Alerts",
            "results": sms_results,
            "status": "success" if any(r["status"] == "sent" for r in sms_results) else "failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    else:
        channel_results["sms"] = {"channel": "sms", "status": "skipped"}

    response = {
        "status":              "SOS_ACTIVATED",
        "version":             "7.0.0",
        "source":              source,
        "cancel_token":        cancel_token,
        "timestamp":           timestamp,
        "location":            {"lat": lat, "lng": lng, "maps_url": maps_link},
        "nearest_hospital":    nearest,
        "all_nearby_hospitals":nearby_hospitals,
        "channels":            channel_results,
        # Backward-compatible fields
        "calls":       channel_results.get("family_call", {}).get("results", []),
        "whatsapp":    channel_results.get("whatsapp", {}).get("results", []),
        "message_sent":voice_msg,
    }

    active_sos = response
    sos_events.insert(0, response)
    if len(sos_events) > 10:
        sos_events.pop()

    return response

# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "status":    "ROADSoS running 🚀",
        "version":   "7.0.0",
        "google_api":"configured" if GOOGLE_API_KEY else "NOT SET",
        "twilio":    "configured" if TWILIO_SID else "NOT SET",
        "endpoints": [
            "/api/services", "/api/hospitals", "/api/police",
            "/api/fire",     "/api/towing",    "/api/places",
            "/api/sos",      "/api/sos/cancel","/api/sos/status",
            "/api/detect",   "/api/women-sos",
        ],
    }

# ─────────────────────────────────────────────
# GET /api/hospitals
# ─────────────────────────────────────────────
@app.get("/api/hospitals")
def hospitals_endpoint(
    lat: float = Query(..., description="User latitude"),
    lng: float = Query(..., description="User longitude"),
    radius: int = Query(8000, description="Search radius in metres"),
    response: Response = None,
):
    log.info(f"/api/hospitals lat={lat} lng={lng}")
    results = _get_category(lat, lng, "hospital", "hospital", radius)
    if not results:
        raise HTTPException(status_code=503, detail="Unable to fetch real-time hospital data")
    if response:
        response.headers["Cache-Control"] = "public, max-age=180"
    return {"status": "ok", "count": len(results), "hospitals": results}

# ─────────────────────────────────────────────
# GET /api/police
# ─────────────────────────────────────────────
@app.get("/api/police")
def police_endpoint(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(8000),
    response: Response = None,
):
    log.info(f"/api/police lat={lat} lng={lng}")
    results = _get_category(lat, lng, "police", "police", radius)
    if not results:
        raise HTTPException(status_code=503, detail="Unable to fetch real-time police data")
    if response:
        response.headers["Cache-Control"] = "public, max-age=180"
    return {"status": "ok", "count": len(results), "police": results}

# ─────────────────────────────────────────────
# GET /api/fire
# ─────────────────────────────────────────────
@app.get("/api/fire")
def fire_endpoint(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(8000),
    response: Response = None,
):
    log.info(f"/api/fire lat={lat} lng={lng}")
    results = _get_category(lat, lng, "fire_station", "fire", radius)
    if not results:
        raise HTTPException(status_code=503, detail="Unable to fetch real-time fire station data")
    if response:
        response.headers["Cache-Control"] = "public, max-age=180"
    return {"status": "ok", "count": len(results), "fire": results}

# ─────────────────────────────────────────────
# GET /api/towing
# ─────────────────────────────────────────────
@app.get("/api/towing")
def towing_endpoint(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(8000),
    response: Response = None,
):
    log.info(f"/api/towing lat={lat} lng={lng}")
    # Try car_repair first, then keyword=towing
    results = _get_category(lat, lng, "car_repair", "towing", radius)
    if not results:
        results = _get_category(lat, lng, "car_repair", "towing", radius, keyword="towing")
    if not results:
        raise HTTPException(status_code=503, detail="Unable to fetch real-time towing data")
    if response:
        response.headers["Cache-Control"] = "public, max-age=180"
    return {"status": "ok", "count": len(results), "towing": results}

# ─────────────────────────────────────────────
# GET /api/services  (all types in one call)
# ─────────────────────────────────────────────
@app.get("/api/services")
def services_endpoint(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(8000),
    response: Response = None,
):
    log.info(f"/api/services lat={lat} lng={lng}")

    # Try Google Places for all types
    if GOOGLE_API_KEY:
        type_map = {
            "hospital":    "hospital",
            "police":      "police",
            "fire_station":"fire",
            "car_repair":  "towing",
        }
        all_services = []
        for gtype, cat in type_map.items():
            raw = _google_nearby(lat, lng, gtype, radius)
            for r in raw[:10]:
                all_services.append(_google_to_service(r, cat, lat, lng))

        if all_services:
            all_services.sort(key=lambda x: x["distance_km"])
            log.info(f"/api/services Google returned {len(all_services)} total")
            if response:
                response.headers["Cache-Control"] = "public, max-age=180"
            return {"status": "ok", "source": "google", "count": len(all_services), "services": all_services}

    # Fall back to Overpass (free, no key)
    op = _overpass_services(lat, lng, radius)
    if op:
        log.info(f"/api/services Overpass returned {len(op)} total")
        if response:
            response.headers["Cache-Control"] = "public, max-age=180"
        return {"status": "ok", "source": "overpass", "count": len(op), "services": op}

    raise HTTPException(
        status_code=503,
        detail="Unable to fetch real-time services. No data from Google or Overpass."
    )

# ─────────────────────────────────────────────
# GET /api/places  (alias kept for backward compat)
# ─────────────────────────────────────────────
@app.get("/api/places")
def places_endpoint(lat: float = Query(...), lng: float = Query(...), radius: int = Query(8000), response: Response = None):
    return services_endpoint(lat, lng, radius, response)

# ─────────────────────────────────────────────
# GET /api/sos  (legacy GET)
# ─────────────────────────────────────────────
@app.get("/api/sos")
def sos_get(lat: float = Query(...), lng: float = Query(...)):
    return _fire_sos(lat=lat, lng=lng, channels=None, source="manual_get")

# ─────────────────────────────────────────────
# POST /api/sos  (enhanced multi-channel)
# ─────────────────────────────────────────────
@app.post("/api/sos")
def sos_post(req: SOSRequest):
    return _fire_sos(
        lat=req.lat, lng=req.lng,
        channels=req.channels,
        source=req.source or "manual",
        nearest_hospital_hint=req.nearest_hospital,
    )

# ─────────────────────────────────────────────
# POST /api/sos/cancel
# ─────────────────────────────────────────────
@app.post("/api/sos/cancel")
def sos_cancel(req: CancelRequest):
    global active_sos
    if not active_sos or active_sos.get("cancel_token") != req.cancel_token:
        return {"status": "not_found", "message": "No active SOS matching this token"}

    cancel_msg = (
        f"✅ *SOS CANCELLED — ROADSoS*\n\n"
        f"The emergency alert has been cancelled by the user.\n"
        f"Reason: {req.reason}\n\n"
        f"_If this was sent in error, please disregard._"
    )
    cancel_sms = f"SOS CANCELLED - ROADSoS. Alert cancelled. Reason: {req.reason}"

    results = []
    for num in FAMILY_CONTACTS:
        try:
            send_whatsapp(num, cancel_msg)
            results.append({"number": num, "whatsapp": "sent"})
        except Exception as e:
            log.error(f"Cancel WhatsApp error: {e}")
            results.append({"number": num, "whatsapp": "failed"})
        try:
            send_sms(num, cancel_sms)
        except Exception as e:
            log.error(f"Cancel SMS error: {e}")

    active_sos = None
    return {
        "status":        "SOS_CANCELLED",
        "cancel_token":  req.cancel_token,
        "reason":        req.reason,
        "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "notifications": results,
    }

# ─────────────────────────────────────────────
# GET /api/sos/status
# ─────────────────────────────────────────────
@app.get("/api/sos/status")
def sos_status():
    if not active_sos:
        return {"status": "no_active_sos", "last_events": sos_events[:3]}
    return {
        "status": "has_active_sos",
        "active": {
            "timestamp":        active_sos.get("timestamp"),
            "location":         active_sos.get("location"),
            "nearest_hospital": active_sos.get("nearest_hospital"),
            "cancel_token":     active_sos.get("cancel_token"),
        },
        "last_events": sos_events[:3],
    }

# ─────────────────────────────────────────────
# POST /api/women-sos  🚨 Women Safety SOS
# ─────────────────────────────────────────────
@app.post("/api/women-sos")
def women_sos(req: WomenSOSRequest):
    """
    Women Safety SOS — sends urgent alerts to family + Pink Police line.
    Triggers: Voice Call + WhatsApp + SMS, with women-safety-specific message.
    """
    log.info(f"Women SOS triggered at lat={req.lat} lng={req.lng}")

    maps_link = f"https://maps.google.com/?q={req.lat},{req.lng}"
    targets   = req.contacts if req.contacts else FAMILY_CONTACTS

    sos_msg = (
        f"🚨 WOMEN SAFETY SOS ALERT!\n\n"
        f"I need help immediately!\n"
        f"📍 My live location: {maps_link}\n"
        f"📞 Coordinates: {req.lat:.5f}, {req.lng:.5f}\n\n"
        f"Please call me or contact police immediately.\n"
        f"Pink Police / Women Helpline: {PINK_POLICE_NUM}\n\n"
        f"_Sent automatically via ROADSoS Women Safety SOS_"
    )
    sms_msg  = f"🚨 SOS ALERT! I need help. My live location: {maps_link} — Women Safety Emergency"
    voice_msg = (
        f"EMERGENCY. Women Safety SOS Alert from ROADSoS. "
        f"The person needs immediate help. "
        f"Live location: {maps_link}. "
        f"Contact Pink Police at {PINK_POLICE_NUM}."
    )

    results = {"whatsapp": [], "sms": [], "calls": []}

    for num in targets:
        # WhatsApp
        try:
            sid = send_whatsapp(num, sos_msg)
            results["whatsapp"].append({"number": num, "status": "sent", "sid": sid})
        except Exception as e:
            log.error(f"Women SOS WhatsApp error: {e}")
            results["whatsapp"].append({"number": num, "status": "failed", "error": str(e)})

        # SMS
        try:
            sid = send_sms(num, sms_msg)
            results["sms"].append({"number": num, "status": "sent", "sid": sid})
        except Exception as e:
            log.error(f"Women SOS SMS error: {e}")
            results["sms"].append({"number": num, "status": "failed", "error": str(e)})

        # Voice Call
        try:
            sid = make_call(num, voice_msg)
            results["calls"].append({"number": num, "status": "success", "sid": sid})
        except Exception as e:
            log.error(f"Women SOS call error: {e}")
            results["calls"].append({"number": num, "status": "failed", "error": str(e)})

    return {
        "status":          "WOMEN_SOS_ACTIVATED",
        "version":         "7.0.0",
        "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "location":        {"lat": req.lat, "lng": req.lng, "maps_url": maps_link},
        "pink_police":     PINK_POLICE_NUM,
        "contacts_alerted":len(targets),
        "channels":        results,
    }

# ─────────────────────────────────────────────
# POST/GET /api/detect  — AI accident detection
# ─────────────────────────────────────────────
@app.post("/api/detect")
def detect_post(req: DetectRequest):
    log.info(f"/api/detect speed={req.speed_kmh} g={req.g_force} tilt={req.tilt_deg}")
    result = analyze_accident(
        speed_kmh=req.speed_kmh,
        g_force=req.g_force,
        tilt_deg=req.tilt_deg,
    )
    return {
        "status": "ok",
        "input":  {"speed_kmh": req.speed_kmh, "g_force": req.g_force, "tilt_deg": req.tilt_deg},
        "analysis": result,
    }

@app.get("/api/detect")
def detect_get(speed_kmh: float = 0, g_force: float = 0, tilt_deg: float = 0):
    result = analyze_accident(speed_kmh=speed_kmh, g_force=g_force, tilt_deg=tilt_deg)
    return {
        "status": "ok",
        "input":  {"speed_kmh": speed_kmh, "g_force": g_force, "tilt_deg": tilt_deg},
        "analysis": result,
    }

# ══════════════════════════════════════════════════════════════════════════════
# WOMEN SOS — DEDICATED CHANNEL ENDPOINTS (fired in parallel by frontend)
# ══════════════════════════════════════════════════════════════════════════════

def _women_sos_messages(lat: float, lng: float) -> dict:
    """Build all Women SOS message strings from a lat/lng pair."""
    maps_link = f"https://maps.google.com/?q={lat},{lng}"
    return {
        "maps_link": maps_link,
        "whatsapp": (
            f"🚨 WOMEN SAFETY SOS ALERT!\n\n"
            f"I need help immediately!\n"
            f"📍 My live location: {maps_link}\n"
            f"📞 Coordinates: {lat:.5f}, {lng:.5f}\n\n"
            f"Please call me or contact police immediately.\n"
            f"Pink Police / Women Helpline: {PINK_POLICE_NUM}\n\n"
            f"_Sent automatically via ROADSoS Women Safety SOS_"
        ),
        "sms": (
            f"🚨 SOS ALERT! I need help. "
            f"My live location: {maps_link} "
            f"— Women Safety Emergency. "
            f"Call {PINK_POLICE_NUM} (Women Helpline)"
        )[:160],
        "voice": (
            f"EMERGENCY. Women Safety SOS Alert from ROADSoS. "
            f"The person needs immediate help. "
            f"Live location: {maps_link}. "
            f"Contact Pink Police at {PINK_POLICE_NUM}."
        ),
    }


# ─────────────────────────────────────────────
# POST /women-sos-call  — Voice calls only
# ─────────────────────────────────────────────
@app.post("/women-sos-call")
def women_sos_call(req: WomenSOSRequest):
    """Trigger Twilio voice calls to family contacts + Pink Police."""
    log.info(f"Women SOS CALL: lat={req.lat} lng={req.lng}")
    msgs    = _women_sos_messages(req.lat, req.lng)
    targets = req.contacts if req.contacts else FAMILY_CONTACTS
    results = []

    for num in targets:
        res = _call_with_retry(num, msgs["voice"], retries=2)
        results.append(res)

    overall = "success" if any(r["status"] == "success" for r in results) else "failed"
    log.info(f"Women SOS CALL result: {overall} for {len(targets)} contacts")
    return {
        "status":    overall,
        "channel":   "call",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "location":  {"lat": req.lat, "lng": req.lng, "maps_url": msgs["maps_link"]},
        "results":   results,
    }


# ─────────────────────────────────────────────
# POST /women-sos-sms  — SMS only
# ─────────────────────────────────────────────
@app.post("/women-sos-sms")
def women_sos_sms(req: WomenSOSRequest):
    """Send Twilio SMS to family contacts."""
    log.info(f"Women SOS SMS: lat={req.lat} lng={req.lng}")
    msgs    = _women_sos_messages(req.lat, req.lng)
    targets = req.contacts if req.contacts else FAMILY_CONTACTS
    results = []

    for num in targets:
        try:
            sid = send_sms(num, msgs["sms"])
            log.info(f"SMS sent to {num}: sid={sid}")
            results.append({"number": num, "status": "sent", "sid": sid})
        except Exception as e:
            log.error(f"Women SOS SMS error for {num}: {e}")
            results.append({"number": num, "status": "failed", "error": str(e)})

    overall = "success" if any(r["status"] == "sent" for r in results) else "failed"
    return {
        "status":    overall,
        "channel":   "sms",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "location":  {"lat": req.lat, "lng": req.lng, "maps_url": msgs["maps_link"]},
        "results":   results,
    }


# ─────────────────────────────────────────────
# POST /women-sos-whatsapp  — WhatsApp only
# ─────────────────────────────────────────────
@app.post("/women-sos-whatsapp")
def women_sos_whatsapp(req: WomenSOSRequest):
    """Send Twilio WhatsApp messages to family contacts."""
    log.info(f"Women SOS WhatsApp: lat={req.lat} lng={req.lng}")
    msgs    = _women_sos_messages(req.lat, req.lng)
    targets = req.contacts if req.contacts else FAMILY_CONTACTS
    results = []

    for num in targets:
        try:
            sid = send_whatsapp(num, msgs["whatsapp"])
            log.info(f"WhatsApp sent to {num}: sid={sid}")
            results.append({"number": num, "status": "sent", "sid": sid})
        except Exception as e:
            log.error(f"Women SOS WhatsApp error for {num}: {e}")
            results.append({"number": num, "status": "failed", "error": str(e)})

    overall = "success" if any(r["status"] == "sent" for r in results) else "failed"
    return {
        "status":    overall,
        "channel":   "whatsapp",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "location":  {"lat": req.lat, "lng": req.lng, "maps_url": msgs["maps_link"]},
        "results":   results,
    }
