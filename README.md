<div align="center">

  <img src="https://img.shields.io/badge/Status-Active-success.svg" alt="Status" />
  <img src="https://img.shields.io/badge/Version-7.0.0-blue.svg" alt="Version" />
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen.svg" alt="PRs Welcome" />
  <img src="https://img.shields.io/badge/PWA-Offline--First-orange.svg" alt="PWA" />

  <h1>🚨 ROADSoS — InfraX2026</h1>
  <p><strong>A high-stakes, location-based emergency response platform designed to optimize the "golden hour" following road accidents.</strong></p>
  <p>Built with the rigor and innovation standards of the <em>National Road Safety Hackathon</em> by Team CivTech Coder (Ronak & Jonathan).</p>

</div>

---

## 📑 Table of Contents

1. [About the Project](#-about-the-project)
2. [The Solution](#-the-solution)
3. [Key Features](#-key-features)
4. [Architecture](#-architecture)
5. [Tech Stack](#%EF%B8%8F-tech-stack)
6. [API Reference](#-api-reference)
7. [Getting Started](#-getting-started)
8. [Environment Variables](#-environment-variables)
9. [Deployment](#-deployment)
10. [Roadmap](#-roadmap)
11. [Contributing](#-contributing)
12. [License & Contact](#-license--contact)

---

## 📖 About the Project

### The Problem

In the event of a road accident, victims and bystanders often face critical difficulty in quickly identifying and contacting the appropriate emergency services. The **"golden hour"** — the crucial period immediately after an accident when timely medical assistance can save lives — is frequently lost due to:

- **Fragmented information**: No single platform for hospitals, police, ambulance, and vehicle recovery.
- **Network dependency**: Most apps fail in low-signal or no-signal zones common at accident sites.
- **Notification delays**: Emergency contacts must be alerted simultaneously across multiple channels.
- **No automatic detection**: Bystanders may not even know an accident has occurred.

---

## 💡 The Solution

ROADSoS provides a unified, **offline-first Progressive Web App (PWA)** that:

- 🏥 Locates the **nearest hospitals & trauma centres**
- 🚑 Finds **ambulance services** with live ETA estimates
- 🚓 Maps **police stations** within the search radius
- 🔥 Identifies **fire stations** in proximity
- 🚜 Connects to **towing & vehicle recovery** services
- 📱 Fires multi-channel **SOS alerts** (Voice Call + WhatsApp + SMS) to family contacts simultaneously
- 🤖 Uses an **AI-based accident detection engine** driven by phone sensors (G-force, tilt, speed delta)
- 👩 Includes a dedicated **Women Safety SOS** with Pink Police / Women Helpline integration

---

## ⭐ Key Features

| Feature | Description |
|---|---|
| 🗺️ **Comprehensive Emergency Mapping** | Google Places API (primary) + OpenStreetMap Overpass (fallback) — always finds nearby services |
| 📶 **Offline-First PWA** | Service Worker caches critical data; works without network |
| 🤖 **AI Accident Detection** | Multi-factor Bayesian scoring engine using G-force, tilt, speed & deceleration |
| 📣 **Multi-Channel SOS** | Simultaneous Voice Call + WhatsApp + SMS via Twilio in one tap |
| 👩 **Women Safety SOS** | Dedicated SOS with Pink Police helpline (1091) integration |
| ⚡ **3-minute Service Cache** | Smart TTL cache avoids redundant API calls and speeds up responses |
| 🌍 **Global Applicability** | Dual data source (Google + Overpass) enables worldwide coverage |
| 🔄 **SOS Cancellation** | Token-based cancel flow sends cancellation notice to all contacts |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (PWA)                           │
│  HTML5 + Vanilla JS + Service Worker                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Map View │  │ SOS Btn  │  │ Sensor   │  │ Women Safety  │  │
│  │ (Leaflet)│  │          │  │ Monitor  │  │ SOS           │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────┬───────────────────────────────────────┘
                          │ REST API (CORS-open)
┌─────────────────────────▼───────────────────────────────────────┐
│                    BACKEND (FastAPI v7.0.0)                      │
│  Python 3.11 · Uvicorn · Pydantic · asyncio                    │
│                                                                  │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │ /api/services│   │  /api/sos    │   │ /api/detect          │  │
│  │ /api/hospital│   │  /api/cancel │   │ road_analyzer.py     │  │
│  │ /api/police  │   │  /api/women- │   │ (Bayesian ML engine) │  │
│  │ /api/fire    │   │   sos        │   └──────────────────────┘  │
│  │ /api/towing  │   └──────┬───────┘                            │
│  └──────┬───────┘          │                                    │
└─────────┼──────────────────┼────────────────────────────────────┘
          │                  │
   ┌──────▼──────┐    ┌──────▼───────────┐
   │ Google      │    │  Twilio          │
   │ Places API  │    │  ┌ Voice Calls   │
   │    +        │    │  ├ WhatsApp      │
   │ Overpass    │    │  └ SMS           │
   │ (fallback)  │    └──────────────────┘
   └─────────────┘
```

### Accident Detection Engine (`road_analyzer.py`)

The detection engine uses a **6-stage pipeline**:

1. **Feature Engineering** — raw sensor data → normalised sub-scores (0–10)
2. **Weighted Fusion** — weighted combination (G-force: 38%, Tilt: 28%, Δspeed: 20%, Speed context: 14%)
3. **Context Multipliers** — night driving (+15%), highway (+10%), rain (+12%), seatbelt (−20%)
4. **Bayesian Confidence** — posterior probability given prior (5% base-rate) and evidence strength
5. **Severity Classifier** — `NONE` / `MINOR` / `MODERATE` / `CRITICAL` with distinct recommendations
6. **Event History** — rolling 20-reading buffer for trend analysis and jerk detection

---

## 🛠️ Tech Stack

### Frontend
| Layer | Technology |
|---|---|
| Core | HTML5, Vanilla JavaScript |
| Maps | Leaflet.js |
| PWA | Service Worker, Web App Manifest |
| Hosting | Vercel |

### Backend
| Layer | Technology |
|---|---|
| Framework | FastAPI 0.x (Python 3.11) |
| Server | Uvicorn |
| Data Validation | Pydantic v2 |
| HTTP Client | `requests` |
| Async | `asyncio` |
| Hosting | Render.com |

### Integrations
| Service | Purpose |
|---|---|
| Google Places API | Primary source for nearby emergency services |
| OpenStreetMap Overpass | Fallback / offline-capable service data |
| Twilio (Voice) | Voice calls to family contacts |
| Twilio (WhatsApp) | WhatsApp SOS alerts |
| Twilio (SMS) | SMS SOS alerts |

---

## 📡 API Reference

Base URL: `https://infrax2026.onrender.com` (or `http://localhost:8000` locally)

### Services

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/services?lat=&lng=&radius=` | Fetch all emergency services (hospital, police, fire, towing) |
| `GET` | `/api/hospitals?lat=&lng=&radius=` | Hospitals & trauma centres only |
| `GET` | `/api/police?lat=&lng=&radius=` | Police stations only |
| `GET` | `/api/fire?lat=&lng=&radius=` | Fire stations only |
| `GET` | `/api/towing?lat=&lng=&radius=` | Towing & car repair services |

### SOS

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/sos` | Fire multi-channel SOS (Voice + WhatsApp + SMS) |
| `GET` | `/api/sos?lat=&lng=` | Legacy GET-based SOS trigger |
| `POST` | `/api/sos/cancel` | Cancel active SOS with token |
| `GET` | `/api/sos/status` | Check current SOS status |
| `POST` | `/api/women-sos` | Women Safety SOS with Pink Police integration |

### Accident Detection

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/detect` | Submit sensor data for accident analysis |
| `GET` | `/api/detect?speed_kmh=&g_force=&tilt_deg=` | GET-based accident check |

#### `POST /api/sos` — Request Body
```json
{
  "lat": 28.6139,
  "lng": 77.2090,
  "channels": ["call_112", "whatsapp", "sms", "family_call"],
  "source": "manual",
  "nearest_hospital": { "name": "AIIMS", "lat": 28.567, "lng": 77.21 }
}
```

#### `POST /api/detect` — Request Body
```json
{
  "speed_kmh": 85.0,
  "g_force": 5.2,
  "tilt_deg": 35.0,
  "delta_speed_kmh": 42.0,
  "context": { "night": false, "highway": true, "rain": false, "seatbelt": true }
}
```

#### `POST /api/detect` — Example Response
```json
{
  "accident_detected": true,
  "severity": "CRITICAL",
  "confidence": 0.923,
  "risk_score": 7.4,
  "triggers": ["Severe impact: 5.2G", "Highway driving (+10% risk)"],
  "recommendation": "🚨 CRITICAL: Call 112 immediately...",
  "model_version": "2.0.1-ensemble"
}
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- A modern browser (Chrome/Edge for full PWA + sensor support)
- [Twilio account](https://twilio.com) (for SOS alerting)
- [Google Cloud project](https://console.cloud.google.com) with **Places API** enabled

### 1. Clone the Repository

```bash
git clone https://github.com/barwarronak-maker/infraX2026.git
cd infraX2026
```

### 2. Set Up the Backend

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and fill in your keys
cp .env.example .env            # See Environment Variables section below
```

### 3. Run the Backend

```bash
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Visit `http://localhost:8000/docs` for the interactive Swagger UI.

### 4. Serve the Frontend

```bash
cd ../frontend
python3 serve.py                # or: python3 -m http.server 3000
```

Open `http://localhost:3000` in your browser.

---

## 🔑 Environment Variables

Create a `backend/.env` file with the following keys:

```env
# Google Cloud — Places API
GOOGLE_API_KEY=AIza...

# Twilio — Voice, WhatsApp & SMS
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+12525842291

# Twilio WhatsApp Sandbox (or your approved WhatsApp sender)
FROM_WHATSAPP=whatsapp:+14155238886

# Women Safety Helpline number (default: India's Pink Police / Women Helpline)
PINK_POLICE_NUMBER=1091
```

> **Note — Twilio Trial Accounts**: Each family contact number must be verified in the Twilio console. For the WhatsApp sandbox, each recipient must text `join receive-attention` to `+14155238886` first.

---

## ☁️ Deployment

### Backend → Render.com

The `render.yaml` at the project root defines the backend service:

```yaml
# Auto-deploys from the `backend/` directory
buildCommand: pip install -r requirements.txt
startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set the environment variables listed above in the **Render Dashboard → Environment** tab.

### Frontend → Vercel

The `vercel.json` at the project root deploys the `frontend/` directory with:
- **Service Worker** served with `no-cache` headers for correct PWA update behaviour
- Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`

```bash
# Deploy via Vercel CLI
npx vercel --prod
```

---

## 🗺️ Roadmap

- [x] Multi-channel SOS: Voice + WhatsApp + SMS
- [x] Offline-first PWA with Service Worker caching
- [x] Women Safety SOS with Pink Police integration
- [x] AI accident detection (Bayesian multi-factor engine)
- [x] Google Places + Overpass dual-source fallback
- [ ] Push notifications for nearby accident alerts
- [ ] AI severity assessment from live CCTV / dashcam feeds
- [ ] Direct integration with local emergency dispatch APIs (112, 108)
- [ ] Multi-language support (Hindi, Tamil, Bengali, etc.)
- [ ] Wearable device integration for automatic crash detection
- [ ] Community-sourced accident blackspot heatmap

---

## 🤝 Contributing

Contributions are greatly appreciated. Please follow these steps:

1. Fork the Project
2. Create your Feature Branch: `git checkout -b feature/AmazingFeature`
3. Commit your Changes: `git commit -m 'Add some AmazingFeature'`
4. Push to the Branch: `git push origin feature/AmazingFeature`
5. Open a Pull Request

---

## 📜 License & Contact

**License:** Distributed under the MIT License. See `LICENSE` for more information.

- **Ronak** — [GitHub @barwarronak-maker](https://github.com/barwarronak-maker)

**Project Link:** [https://github.com/barwarronak-maker/infraX2026](https://github.com/barwarronak-maker/infraX2026)

---

<div align="center">
  <sub>Built with ❤️ to save lives on India's roads.</sub>
</div>
