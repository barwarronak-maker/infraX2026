import time
import math
import os
import uuid
import requests

from dotenv import load_dotenv
load_dotenv()  # Load .env before anything reads os.getenv()

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from services.call_service import make_call
from services.whatsapp_service import send_whatsapp
from services.sms_service import send_sms
from road_analyzer import analyze as analyze_accident

app = FastAPI(title="ROADSoS API", version="6.0.0")

# ─────────────────────────────────────────────
# CORS — allow all origins for hackathon demo
# ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

FAMILY_CONTACTS = [
    "+917232062340",   # Primary contact
    "+916205958187",   # Secondary contact
    # NOTE: For Twilio trial SMS, each number must be verified at:
    # twilio.com/user/account/phone-numbers/verified
    # WhatsApp sandbox: each number must send 'join receive-attention' to +14155238886
]

# ─────────────────────────────────────────────
# IN-MEMORY SOS STATE (last 10 events)
# ─────────────────────────────────────────────
sos_events: List[dict] = []   # ring-buffer of last 10 SOS events
active_sos: Optional[dict] = None  # most-recent SOS (for cancel)

# ─────────────────────────────────────────────
# STATIC FALLBACK — all service types, major Indian cities
# ─────────────────────────────────────────────
FALLBACK_SERVICES = [
    # ── Pune ───────────────────────────────────────────────────────────────────
    {"name": "Sassoon General Hospital",      "category": "hospital", "address": "Pune, Maharashtra",     "lat": 18.5178, "lng": 73.8543, "phone": "02026120009"},
    {"name": "KEM Hospital Pune",             "category": "hospital", "address": "Rasta Peth, Pune",       "lat": 18.5120, "lng": 73.8553, "phone": "02026128000"},
    {"name": "Ruby Hall Clinic",              "category": "hospital", "address": "Wanowrie, Pune",          "lat": 18.5320, "lng": 73.8820, "phone": "02026163391"},
    {"name": "Jehangir Hospital",             "category": "hospital", "address": "Nagar Road, Pune",        "lat": 18.5289, "lng": 73.8750, "phone": "02026051000"},
    {"name": "Deenanath Mangeshkar Hospital", "category": "hospital", "address": "Erandwane, Pune",         "lat": 18.5122, "lng": 73.8288, "phone": "02020660606"},
    {"name": "Pune Police Headquarters",      "category": "police",   "address": "Shivajinagar, Pune",      "lat": 18.5195, "lng": 73.8553, "phone": "100"},
    {"name": "Deccan Fire Station",           "category": "fire",     "address": "Deccan Gymkhana, Pune",   "lat": 18.5201, "lng": 73.8452, "phone": "101"},
    {"name": "Pune Towing Services",          "category": "towing",   "address": "Central Pune",            "lat": 18.5200, "lng": 73.8500, "phone": "02025536298"},

    # ── Delhi ──────────────────────────────────────────────────────────────────
    {"name": "AIIMS Delhi",                   "category": "hospital", "address": "Ansari Nagar, Delhi",     "lat": 28.5672, "lng": 77.2100, "phone": "01126588500"},
    {"name": "Safdarjung Hospital",           "category": "hospital", "address": "New Delhi",               "lat": 28.5674, "lng": 77.2090, "phone": "01126707444"},
    {"name": "RML Hospital Delhi",            "category": "hospital", "address": "Connaught Place, Delhi",  "lat": 28.6237, "lng": 77.2090, "phone": "01123404321"},
    {"name": "Delhi Police HQ",               "category": "police",   "address": "ITO, New Delhi",          "lat": 28.6304, "lng": 77.2177, "phone": "100"},
    {"name": "Connaught Place Fire Station",  "category": "fire",     "address": "Connaught Place, Delhi",  "lat": 28.6315, "lng": 77.2167, "phone": "101"},
    {"name": "Delhi Traffic Police Towing",   "category": "towing",   "address": "New Delhi",               "lat": 28.6300, "lng": 77.2150, "phone": "01125844444"},

    # ── Mumbai ─────────────────────────────────────────────────────────────────
    {"name": "KEM Hospital Mumbai",           "category": "hospital", "address": "Parel, Mumbai",           "lat": 18.9990, "lng": 72.8418, "phone": "02224107000"},
    {"name": "Nair Hospital Mumbai",          "category": "hospital", "address": "Mumbai Central",          "lat": 18.9647, "lng": 72.8258, "phone": "02223027600"},
    {"name": "Mumbai Police",                 "category": "police",   "address": "Crawford Market, Mumbai", "lat": 18.9322, "lng": 72.8418, "phone": "100"},
    {"name": "Byculla Fire Brigade",          "category": "fire",     "address": "Byculla, Mumbai",         "lat": 18.9750, "lng": 72.8350, "phone": "101"},
    {"name": "Western Express Towing",        "category": "towing",   "address": "Bandra, Mumbai",          "lat": 19.0500, "lng": 72.8500, "phone": "02228892222"},

    # ── Bengaluru ──────────────────────────────────────────────────────────────
    {"name": "St. Johns Medical College",     "category": "hospital", "address": "Koramangala, Bengaluru",  "lat": 12.9250, "lng": 77.6120, "phone": "08022064000"},
    {"name": "Bowring Hospital Bengaluru",    "category": "hospital", "address": "Shivajinagar, Bengaluru", "lat": 12.9716, "lng": 77.5946, "phone": "08025571100"},
    {"name": "Bengaluru City Police",         "category": "police",   "address": "Infantry Road, Bengaluru","lat": 12.9779, "lng": 77.5952, "phone": "100"},
    {"name": "Bengaluru Fire Services",       "category": "fire",     "address": "Central, Bengaluru",      "lat": 12.9750, "lng": 77.5900, "phone": "101"},
    {"name": "Nandi Towing Services",         "category": "towing",   "address": "MG Road, Bengaluru",      "lat": 12.9700, "lng": 77.6000, "phone": "08022221111"},

    # ── Chennai ────────────────────────────────────────────────────────────────
    {"name": "Govt Stanley Hospital Chennai", "category": "hospital", "address": "Old Jail Road, Chennai",  "lat": 13.0827, "lng": 80.2707, "phone": "04425281232"},
    {"name": "Apollo Hospitals Greams Road",  "category": "hospital", "address": "Greams Road, Chennai",    "lat": 13.0604, "lng": 80.2496, "phone": "04428290200"},
    {"name": "Chennai Police HQ",             "category": "police",   "address": "Mylapore, Chennai",       "lat": 13.0418, "lng": 80.2773, "phone": "100"},
    {"name": "Chennai Fire Brigade",          "category": "fire",     "address": "Egmore, Chennai",         "lat": 13.0500, "lng": 80.2700, "phone": "101"},
    {"name": "Chennai Traffic Towing",        "category": "towing",   "address": "Mount Road, Chennai",     "lat": 13.0600, "lng": 80.2600, "phone": "04423452365"},

    # ── Hyderabad ──────────────────────────────────────────────────────────────
    {"name": "Osmania General Hospital",      "category": "hospital", "address": "Afzal Gunj, Hyderabad",   "lat": 17.3804, "lng": 78.4716, "phone": "04024600146"},
    {"name": "Gandhi Hospital",               "category": "hospital", "address": "Secunderabad",            "lat": 17.4241, "lng": 78.5028, "phone": "04027702222"},
    {"name": "Hyderabad Police HQ",           "category": "police",   "address": "Basheerbagh, Hyderabad",  "lat": 17.3990, "lng": 78.4760, "phone": "100"},
    {"name": "Hyderabad Fire Service",        "category": "fire",     "address": "Central, Hyderabad",      "lat": 17.4000, "lng": 78.4750, "phone": "101"},
    {"name": "Cyberabad Towing",              "category": "towing",   "address": "Hitec City, Hyderabad",   "lat": 17.4400, "lng": 78.3800, "phone": "04027852400"},

    # ── Kolkata ────────────────────────────────────────────────────────────────
    {"name": "Calcutta Medical College",      "category": "hospital", "address": "College Square, Kolkata", "lat": 22.5735, "lng": 88.3639, "phone": "03322123700"},
    {"name": "SSKM Hospital",                 "category": "hospital", "address": "Bhowanipore, Kolkata",    "lat": 22.5386, "lng": 88.3444, "phone": "03322231589"},
    {"name": "Kolkata Police HQ",             "category": "police",   "address": "Lalbazar, Kolkata",       "lat": 22.5645, "lng": 88.3433, "phone": "100"},
    {"name": "Kolkata Fire Service",          "category": "fire",     "address": "Central, Kolkata",        "lat": 22.5600, "lng": 88.3500, "phone": "101"},
    {"name": "Kolkata Traffic Towing",        "category": "towing",   "address": "Park Street, Kolkata",    "lat": 22.5650, "lng": 88.3550, "phone": "03322143231"},

    # ── Ahmedabad ──────────────────────────────────────────────────────────────
    {"name": "Civil Hospital Ahmedabad",      "category": "hospital", "address": "Asarwa, Ahmedabad",       "lat": 23.0526, "lng": 72.6030, "phone": "07922683721"},
    {"name": "SVP Hospital",                  "category": "hospital", "address": "Ellisbridge, Ahmedabad",  "lat": 23.0245, "lng": 72.5721, "phone": "07926579698"},
    {"name": "Ahmedabad Police HQ",           "category": "police",   "address": "Shahibag, Ahmedabad",     "lat": 23.0300, "lng": 72.5800, "phone": "100"},
    {"name": "Ahmedabad Fire Brigade",        "category": "fire",     "address": "Danapith, Ahmedabad",     "lat": 23.0250, "lng": 72.5850, "phone": "101"},
    {"name": "Ahmedabad Towing",              "category": "towing",   "address": "Central, Ahmedabad",      "lat": 23.0200, "lng": 72.5800, "phone": "07925624100"},

    # ── Jaipur ─────────────────────────────────────────────────────────────────
    {"name": "SMS Hospital Jaipur",           "category": "hospital", "address": "JLN Marg, Jaipur",        "lat": 26.8920, "lng": 75.8198, "phone": "01412560291"},
    {"name": "Santokba Durlabhji Hospital",   "category": "hospital", "address": "Bhawani Singh Rd, Jaipur","lat": 26.8979, "lng": 75.8231, "phone": "01412566251"},
    {"name": "Payal Hospital Jaipur",         "category": "hospital", "address": "Vaishali Nagar, Jaipur",  "lat": 26.9145, "lng": 75.7437, "phone": "01412355555"},
    {"name": "Narayana Multispeciality Jaipur","category":"hospital", "address": "Sector 28, Jaipur",       "lat": 26.8480, "lng": 75.8065, "phone": "01412776600"},
    {"name": "Jaipur Police HQ",              "category": "police",   "address": "Lalkothi, Jaipur",        "lat": 26.9150, "lng": 75.8000, "phone": "100"},
    {"name": "Jaipur Police Control Room",    "category": "police",   "address": "MI Road, Jaipur",         "lat": 26.9185, "lng": 75.8076, "phone": "0141-2227-444"},
    {"name": "Jaipur Fire Brigade HQ",        "category": "fire",     "address": "Central, Jaipur",         "lat": 26.9100, "lng": 75.8050, "phone": "101"},
    {"name": "Jaipur Municipal Fire Station", "category": "fire",     "address": "Mansarovar, Jaipur",      "lat": 26.8612, "lng": 75.7720, "phone": "01412781212"},
    {"name": "Jaipur Traffic Police Towing",  "category": "towing",   "address": "MI Road, Jaipur",         "lat": 26.9000, "lng": 75.8100, "phone": "01412565656"},
    {"name": "Rajasthan Roadways Towing",     "category": "towing",   "address": "Sindhi Camp, Jaipur",     "lat": 26.9180, "lng": 75.8063, "phone": "01412204656"},

    # ── Lucknow ────────────────────────────────────────────────────────────────
    {"name": "KGMU Lucknow",                  "category": "hospital", "address": "Chowk, Lucknow",          "lat": 26.8640, "lng": 80.9150, "phone": "05222257451"},
    {"name": "SGPGI Lucknow",                 "category": "hospital", "address": "Raebareli Rd, Lucknow",   "lat": 26.7380, "lng": 80.9340, "phone": "05222440007"},
    {"name": "Lucknow Police HQ",             "category": "police",   "address": "Hazratganj, Lucknow",     "lat": 26.8500, "lng": 80.9200, "phone": "100"},
    {"name": "Lucknow Fire Station",          "category": "fire",     "address": "Hazratganj, Lucknow",     "lat": 26.8450, "lng": 80.9250, "phone": "101"},

    # ── Chandigarh ─────────────────────────────────────────────────────────────
    {"name": "PGIMER Chandigarh",             "category": "hospital", "address": "Sector 12, Chandigarh",   "lat": 30.7629, "lng": 76.7770, "phone": "01722746018"},
    {"name": "Chandigarh Police HQ",          "category": "police",   "address": "Sector 9, Chandigarh",    "lat": 30.7300, "lng": 76.7800, "phone": "100"},
    {"name": "Chandigarh Fire Service",       "category": "fire",     "address": "Sector 17, Chandigarh",   "lat": 30.7350, "lng": 76.7750, "phone": "101"},
    {"name": "Chandigarh Towing",             "category": "towing",   "address": "Sector 17, Chandigarh",   "lat": 30.7400, "lng": 76.7800, "phone": "01722749000"},

    # ── Bhopal ─────────────────────────────────────────────────────────────────
    {"name": "AIIMS Bhopal",                  "category": "hospital", "address": "Saket Nagar, Bhopal",     "lat": 23.2039, "lng": 77.4608, "phone": "07552672322"},
    {"name": "Hamidia Hospital",              "category": "hospital", "address": "Royal Market, Bhopal",    "lat": 23.2650, "lng": 77.3950, "phone": "07552540590"},
    {"name": "Bhopal Police HQ",              "category": "police",   "address": "Jahangirabad, Bhopal",    "lat": 23.2500, "lng": 77.4000, "phone": "100"},
    {"name": "Bhopal Fire Station",           "category": "fire",     "address": "MP Nagar, Bhopal",        "lat": 23.2450, "lng": 77.4050, "phone": "101"},
    {"name": "Bhopal Towing Services",        "category": "towing",   "address": "Arera Hills, Bhopal",     "lat": 23.2500, "lng": 77.4100, "phone": "07552551551"},
]

# Keep backward-compat alias for hospital-only fallback
FALLBACK_HOSPITALS = [s for s in FALLBACK_SERVICES if s["category"] == "hospital"]

# ─────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────
class SOSRequest(BaseModel):
    lat: float
    lng: float
    channels: Optional[List[str]] = None
    source: Optional[str] = "manual"
    cancel_token: Optional[str] = None
    # Frontend passes its Overpass-verified nearest hospital
    # so the backend uses the accurate local result in WhatsApp/SMS
    nearest_hospital: Optional[dict] = None

class CancelRequest(BaseModel):
    cancel_token: str
    reason: Optional[str] = "User cancelled"

class DetectRequest(BaseModel):
    speed_kmh: float = 0.0
    g_force: float = 0.0
    tilt_deg: float = 0.0

# ─────────────────────────────────────────────
# HELPER — Haversine distance (km)
# ─────────────────────────────────────────────
def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ─────────────────────────────────────────────
# HELPER — Query Overpass API for real services near user
# ─────────────────────────────────────────────
def get_services_from_overpass(lat: float, lng: float, radius: int = 8000) -> list:
    """Query Overpass for hospitals, police, fire stations, car repair near user."""
    query = f"""[out:json][timeout:10];
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
        res = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query, timeout=10
        )
        data = res.json()
        seen     = set()
        services = []
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
                "name":         name,
                "category":     cat_map[amenity],
                "address":      ", ".join(filter(None, [tags.get("addr:street"), tags.get("addr:city")])) or "Nearby",
                "lat":          slat,
                "lng":          slng,
                "phone":        tags.get("phone") or tags.get("contact:phone") or "",
                "distance_km":  round(d, 2),
                "eta_minutes":  max(3, math.ceil((d / 40) * 60)),
            })
        services.sort(key=lambda x: x["distance_km"])
        return services
    except Exception:
        return []

# ─────────────────────────────────────────────
# HELPER — Find nearest hospital: Google → Overpass → static fallback
# ─────────────────────────────────────────────
def get_nearest_hospitals(lat: float, lng: float, limit: int = 5) -> list:

    # ── 1. Try Google Places API ────────────────────────────────────────────────
    if GOOGLE_API_KEY:
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lng}",
            "radius": 10000,
            "type": "hospital",
            "key": GOOGLE_API_KEY,
        }
        try:
            res  = requests.get(url, params=params, timeout=8)
            data = res.json()
            if data.get("status") == "OK" and data.get("results"):
                hospitals = []
                for h in data["results"][:limit]:
                    hlat = h["geometry"]["location"]["lat"]
                    hlng = h["geometry"]["location"]["lng"]
                    hospitals.append({
                        "name":        h.get("name", "Unknown Hospital"),
                        "address":     h.get("vicinity", ""),
                        "lat":         hlat,
                        "lng":         hlng,
                        "phone":       h.get("formatted_phone_number", ""),
                        "rating":      h.get("rating", None),
                        "category":    "hospital",
                        "distance_km": round(haversine_km(lat, lng, hlat, hlng), 2),
                        "eta_minutes": max(3, math.ceil((haversine_km(lat, lng, hlat, hlng) / 40) * 60)),
                    })
                hospitals.sort(key=lambda x: x["distance_km"])
                return hospitals
        except Exception:
            pass

    # ── 2. Try Overpass (real live data, no API key needed) ─────────────────────
    overpass = get_services_from_overpass(lat, lng, radius=8000)
    hospitals = [s for s in overpass if s["category"] == "hospital"]
    if hospitals:
        return hospitals[:limit]

    # ── 3. No static fallback — only real live data ──────────────────────────
    return []

# ─────────────────────────────────────────────
# HELPER — Get ALL service types near user: Overpass → static fallback
# ─────────────────────────────────────────────
def get_all_services(lat: float, lng: float, limit: int = 40) -> list:
    """Query Overpass for all service types. Falls back to FALLBACK_SERVICES filtered by distance."""
    services = get_services_from_overpass(lat, lng, radius=8000)
    if services:
        # Assign stable integer ids and _dist (meters) for frontend compatibility
        for i, s in enumerate(services):
            s.setdefault("id", (hash(s["name"]) & 0x7FFFFFFF) % 900000 + 100)
            s["_dist"] = s.get("distance_km", 0) * 1000
        return services[:limit]

    # Overpass failed — fall back to static data sorted by distance to user
    print(f"[ROADSoS] Overpass returned nothing, using static fallback for ({lat},{lng})")
    for i, s in enumerate(FALLBACK_SERVICES):
        d = haversine_km(lat, lng, s["lat"], s["lng"])
        s["distance_km"] = round(d, 2)
        s["_dist"] = d * 1000
        s["id"] = s.get("id", 5000 + i)
        s["eta_minutes"] = max(3, int((d / 40) * 60))
    return sorted(FALLBACK_SERVICES, key=lambda x: x["_dist"])[:limit]

# ─────────────────────────────────────────────
# HELPER — Call with retry
# ─────────────────────────────────────────────
def call_with_retry(number: str, message: str, retries: int = 2) -> dict:
    for attempt in range(1, retries + 1):
        try:
            sid = make_call(number, message)
            return {"number": number, "status": "success", "attempt": attempt, "sid": sid}
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
    return {"number": number, "status": "failed", "attempt": retries}

# ─────────────────────────────────────────────
# HELPER — Fire a single SOS event
# ─────────────────────────────────────────────
def _fire_sos(lat: float, lng: float, channels: Optional[List[str]], source: str,
              nearest_hospital_hint: Optional[dict] = None) -> dict:
    global active_sos

    enabled = set(channels) if channels else {"call_112", "call_108", "whatsapp", "sms", "family_call", "share"}

    timestamp    = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cancel_token = str(uuid.uuid4())
    maps_link    = f"https://maps.google.com/?q={lat},{lng}"

    # Step 1 — Nearest hospital
    # Priority: frontend Overpass hint > backend Overpass > backend static fallback
    if nearest_hospital_hint and nearest_hospital_hint.get("name"):
        nearest          = nearest_hospital_hint
        nearby_hospitals = [nearest_hospital_hint]
        # Recalculate distance_km in case frontend sent stale value
        if nearest.get("lat") and nearest.get("lng"):
            d = haversine_km(lat, lng, nearest["lat"], nearest["lng"])
            nearest = {**nearest, "distance_km": round(d, 2)}
            nearby_hospitals = [nearest]
    else:
        nearby_hospitals = get_nearest_hospitals(lat, lng, limit=3)
        nearest = nearby_hospitals[0] if nearby_hospitals else None

    hospital_info = f"{nearest['name']} ({nearest['distance_km']}km away)" if nearest else "Not found"

    # Step 2 — Build messages
    voice_message = (
        f"EMERGENCY SOS ALERT from ROADSoS. "
        f"Accident detected. "
        f"Location: {maps_link}. "
        f"Nearest hospital: {hospital_info}. "
        f"Please respond immediately."
    )
    whatsapp_message = (
        f"🚨 *EMERGENCY SOS ALERT*\n\n"
        f"📍 Location: {maps_link}\n"
        f"🏥 Nearest Hospital: {hospital_info}\n"
        f"📞 Coordinates: {lat:.5f}, {lng:.5f}\n\n"
        f"_Sent via ROADSoS Emergency System_"
    )
    sms_message = (
        f"SOS ALERT - ROADSoS Emergency. "
        f"Location: {maps_link}. "
        f"Hospital: {hospital_info}."
    )

    channel_results = {}

    # ── Channel: Family Voice Calls ──────────────────────────────
    if "family_call" in enabled:
        call_results = []
        for i, num in enumerate(FAMILY_CONTACTS):
            result = call_with_retry(num, voice_message, retries=2)
            result["name"] = f"Family Contact {i + 1}"
            call_results.append(result)
        channel_results["family_call"] = {
            "channel": "family_call",
            "label": "Family Voice Calls",
            "results": call_results,
            "status": "success" if any(r["status"] == "success" for r in call_results) else "failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    else:
        channel_results["family_call"] = {"channel": "family_call", "status": "skipped"}

    # ── Channel: WhatsApp ────────────────────────────────────────
    if "whatsapp" in enabled:
        wa_results = []
        for num in FAMILY_CONTACTS:
            try:
                sid = send_whatsapp(num, whatsapp_message)
                wa_results.append({"number": num, "status": "sent", "sid": sid})
            except Exception as e:
                wa_results.append({"number": num, "status": "failed", "error": str(e)})
        channel_results["whatsapp"] = {
            "channel": "whatsapp",
            "label": "WhatsApp Alerts",
            "results": wa_results,
            "status": "success" if any(r["status"] == "sent" for r in wa_results) else "failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    else:
        channel_results["whatsapp"] = {"channel": "whatsapp", "status": "skipped"}

    # ── Channel: SMS ─────────────────────────────────────────────
    if "sms" in enabled:
        sms_results = []
        for num in FAMILY_CONTACTS:
            try:
                sid = send_sms(num, sms_message)
                sms_results.append({"number": num, "status": "sent", "sid": sid})
            except Exception as e:
                sms_results.append({"number": num, "status": "failed", "error": str(e)})
        channel_results["sms"] = {
            "channel": "sms",
            "label": "SMS Alerts",
            "results": sms_results,
            "status": "success" if any(r["status"] == "sent" for r in sms_results) else "failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    else:
        channel_results["sms"] = {"channel": "sms", "status": "skipped"}

    # ── Build final response ─────────────────────────────────────
    response = {
        "status": "SOS_ACTIVATED",
        "version": "6.0.0",
        "source": source,
        "cancel_token": cancel_token,
        "timestamp": timestamp,
        "location": {
            "lat": lat,
            "lng": lng,
            "maps_url": maps_link,
        },
        "nearest_hospital": nearest,
        "all_nearby_hospitals": nearby_hospitals,
        "channels": channel_results,
        # Backward-compatible
        "calls":        channel_results.get("family_call", {}).get("results", []),
        "whatsapp":     channel_results.get("whatsapp", {}).get("results", []),
        "message_sent": voice_message,
    }

    active_sos = response
    sos_events.insert(0, response)
    if len(sos_events) > 10:
        sos_events.pop()

    return response

# ─────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "ROADSoS running 🚀",
        "version": "6.0.0",
        "endpoints": ["/api/sos", "/api/sos/cancel", "/api/sos/status", "/api/hospitals", "/api/services", "/api/detect"],
    }

# ─────────────────────────────────────────────
# GET /api/hospitals — hospitals only (used by nearest-hospital card)
# ─────────────────────────────────────────────
@app.get("/api/hospitals")
def hospitals(lat: float = Query(...), lng: float = Query(...), limit: int = 5, response: Response = None):
    results = get_nearest_hospitals(lat, lng, limit=limit)
    if response:
        response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "status": "ok",
        "location": {"lat": lat, "lng": lng},
        "count": len(results),
        "hospitals": results,
    }

# ─────────────────────────────────────────────
# GET /api/services — ALL types: hospital + police + fire + towing
# ─────────────────────────────────────────────
@app.get("/api/services")
def services(lat: float = Query(...), lng: float = Query(...), limit: int = 40, response: Response = None):
    print(f"[ROADSoS] /api/services called: lat={lat}, lng={lng}")
    results = get_all_services(lat, lng, limit=limit)
    print(f"[ROADSoS] /api/services returning {len(results)} services")
    if response:
        response.headers["Cache-Control"] = "public, max-age=180"
    return {
        "status": "ok",
        "location": {"lat": lat, "lng": lng},
        "count": len(results),
        "services": results,
    }

# ─────────────────────────────────────────────
# GET /api/sos — legacy endpoint
# ─────────────────────────────────────────────
@app.get("/api/sos")
def sos_get(lat: float = Query(...), lng: float = Query(...)):
    return _fire_sos(lat=lat, lng=lng, channels=None, source="manual")

# ─────────────────────────────────────────────
# POST /api/sos — enhanced multi-channel SOS
# ─────────────────────────────────────────────
@app.post("/api/sos")
def sos_post(req: SOSRequest):
    return _fire_sos(
        lat=req.lat,
        lng=req.lng,
        channels=req.channels,
        source=req.source or "manual",
        nearest_hospital_hint=req.nearest_hospital,  # use frontend Overpass result
    )

# ─────────────────────────────────────────────
# POST /api/sos/cancel — cancellation alerts
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
        except Exception:
            results.append({"number": num, "whatsapp": "failed"})
        try:
            send_sms(num, cancel_sms)
        except Exception:
            pass

    active_sos = None
    return {
        "status": "SOS_CANCELLED",
        "cancel_token": req.cancel_token,
        "reason": req.reason,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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
# POST /api/detect — AI accident detection
# ─────────────────────────────────────────────
@app.post("/api/detect")
def detect_post(req: DetectRequest):
    result = analyze_accident(speed_kmh=req.speed_kmh, g_force=req.g_force, tilt_deg=req.tilt_deg)
    return {
        "status": "ok",
        "input": {"speed_kmh": req.speed_kmh, "g_force": req.g_force, "tilt_deg": req.tilt_deg},
        "analysis": result,
    }

@app.get("/api/detect")
def detect_get(speed_kmh: float = 0, g_force: float = 0, tilt_deg: float = 0):
    result = analyze_accident(speed_kmh=speed_kmh, g_force=g_force, tilt_deg=tilt_deg)
    return {
        "status": "ok",
        "input": {"speed_kmh": speed_kmh, "g_force": g_force, "tilt_deg": tilt_deg},
        "analysis": result,
    }
@app.get("/api/places")
async def get_places(lat: float, lng: float, radius: int = 8000):
    print(f"[ROADSoS] /api/places called: lat={lat}, lng={lng}, radius={radius}")

    # ── Try Google Places API if key is available ──────────────────────────
    if GOOGLE_API_KEY:
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        types_mapping = {
            "hospital": "hospital",
            "police": "police",
            "fire_station": "fire",
            "car_repair": "towing"
        }
        services = []
        for gtype, cat in types_mapping.items():
            params = {
                "location": f"{lat},{lng}",
                "radius": radius,
                "type": gtype,
                "key": GOOGLE_API_KEY,
            }
            try:
                res = requests.get(url, params=params, timeout=8)
                data = res.json()
                if data.get("status") == "OK" and data.get("results"):
                    for idx, h in enumerate(data["results"][:10]):
                        hlat = h["geometry"]["location"]["lat"]
                        hlng = h["geometry"]["location"]["lng"]
                        sid = hash(h.get("place_id", f"{cat}_{idx}")) % 1000000
                        d = haversine_km(lat, lng, hlat, hlng)
                        services.append({
                            "id": sid,
                            "name": h.get("name", "Unknown"),
                            "category": cat,
                            "address": h.get("vicinity", "Nearby"),
                            "lat": hlat,
                            "lng": hlng,
                            "phone": h.get("formatted_phone_number", ""),
                            "distance_km": round(d, 2),
                            "_dist": d * 1000,
                        })
            except Exception as e:
                print(f"[ROADSoS] Google Places error for {gtype}: {e}")
        if services:
            services.sort(key=lambda x: x.get("_dist", 999999))
            print(f"[ROADSoS] /api/places returning {len(services)} Google results")
            return {"services": services}

    # ── No Google key (or Google returned nothing) → use Overpass ─────────
    print("[ROADSoS] /api/places: No Google key or empty result, falling back to Overpass")
    overpass = get_services_from_overpass(lat, lng, radius)
    if overpass:
        for i, s in enumerate(overpass):
            s["_dist"] = s.get("distance_km", 0) * 1000
            s["id"] = (hash(s["name"]) & 0x7FFFFFFF) % 900000 + 100
        overpass.sort(key=lambda x: x.get("_dist", 999999))
        print(f"[ROADSoS] /api/places returning {len(overpass)} Overpass results")
        return {"services": overpass}

    # ── Final fallback: static data sorted by distance ────────────────────
    print("[ROADSoS] /api/places: Overpass also failed, returning static fallback")
    for i, s in enumerate(FALLBACK_SERVICES):
        d = haversine_km(lat, lng, s["lat"], s["lng"])
        s["distance_km"] = round(d, 2)
        s["_dist"] = d * 1000
        s["id"] = s.get("id", 5000 + i)
        s["eta_minutes"] = max(3, int((d / 40) * 60))
    sorted_fallback = sorted(FALLBACK_SERVICES, key=lambda x: x["_dist"])
    return {"services": sorted_fallback[:40]}
