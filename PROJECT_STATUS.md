# RoadIQ — Project Status

_Last updated: 2026-08-17 09:50 ET — merged experimental into main (excluding Nova Sonic voice prototype); verified /api/driver, /api/plan (Nashville->Dallas), /api/ai chat, /api/competitors, /api/fleet all working post-merge_

## Current Build: All 8 Hackathon Features ✅ + Fleet Intelligence ✅

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | Home tab proactive alert | ✅ Done | Dynamic — updates after buildTrip(); persisted to localStorage |
| 2 | Plan Trip (SVG map + itinerary) | ✅ Done | Nashville→Dallas verified; dynamic bbox fix for long routes |
| 3 | AI Journey Optimizer (Nova Lite) | ✅ Done | Real Databricks data; anti-hallucination prompt |
| 4 | Chat tab | ✅ Done | Grounded in real corridor stops via `_build_chat_stops_context()` |
| 5 | Return Load Opportunities | ✅ Done | Route-aware (`_last_plan`); Dallas loads after Nashville→Dallas plan |
| 6 | Fleet tab (15 drivers) | ✅ Done | KPI cards, fuel risk, loyalty tiers, savings banner |
| 7 | Load Assignment Board | ✅ Done | Smart Assign with AI-ranked driver suggestions |
| 8 | RoadIQ tab | ✅ Done | Fully dynamic — no more hardcoded Knoxville/Nashville→Atlanta |
| 9 | Maintenance tab | ✅ Done | DEF%, tire PSI, oil life, alerts |
| 10 | Weather ribbon | ✅ Done | Open-Meteo, 5-point severity, no API key |
| 11 | 3-way stop filter + Competitor view | ✅ Done | Optimized / All Stops / Competitors |
| 12 | Push-for-Elite loyalty progress | ✅ Done | Monthly gal estimate, gold progress bar |
| 13 | Proactive re-route alert | ✅ Done | 15s delay, 3 scenarios, dismiss/show-alternatives |
| 14 | Parking/shower reservation CTA | ✅ Done | PFJ-XXXXX code, Celonis write-back |
| 15 | Repeat route memory | ✅ Done | localStorage, pre-fills form after ≥2 runs |
| 16 | Celonis preference write-back | ✅ Done | 5 fields (food, shower, preferred/avoided stop, gallons) |
| 17 | Fleet Smart Assign | ✅ Done | `/api/fleet/suggest` — HOS/fuel/Pilot-alignment scoring, ranked modal |
| 18 | Driver push notification | ✅ Done | Slide-in banner, "View Optimized Route →" auto-builds trip |
| 19 | Fleet insights bar | ✅ Done | Missed Pilot Stops, Est. Missed Savings, On Pilot Streak cards |
| 20 | PFJ 360 food offerings | ✅ Done | `dev.location.pfj360_offering` via `get_pfj360_food_offerings()` |

## Known Issues / Open Items

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | Celonis `load_data_driver_info` name filter broken | Medium | Open — Celonis bug, not ours |
| 2 | `_extract_and_save_preferences()` false-positives on questions | Low | Open — cosmetic only |
| 3 | Chat latency ~11–20s (2 Databricks + 2 Bedrock calls) | Low | Open — demo acceptable |
| 4 | AWS session tokens expire (1–12h) | Operational | Refresh `.env` when `ExpiredTokenException` |
| 5 | Load assignments reset on server restart | Low | In-memory only — demo intentional |

## Active Server

```
python server.py   →   http://localhost:5002
```

## API Endpoints (complete list)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/driver` | Driver profile + loyalty |
| GET | `/api/stop` | Recommended stop |
| GET | `/api/route` | OSRM route + stop pins |
| POST | `/api/plan` | Full trip plan |
| POST | `/api/ai` | Chat + journey plan (Bedrock) |
| GET | `/api/fleet` | 15-driver roster with HOS/fuel/intel |
| POST | `/api/fleet/suggest` | AI-ranked top-5 drivers for a load |
| POST | `/api/stop_advice` | Per-stop GOOD/SKIP verdict |
| GET | `/api/maintenance` | Vehicle health data |
| POST | `/api/poi` | Nearby POIs |
| POST | `/api/weather` | Route weather ribbon |
| GET | `/api/loads` | Load board (5 demo loads) |
| POST | `/api/loads/assign` | Assign driver to load |
| GET | `/api/fleet_savings` | Pilot vs national avg savings |
| GET | `/api/return_loads` | Return load opps from drop-off city |
| GET | `/api/competitors` | Competitor stop comparison data |
| GET | `/tiles/<z>/<x>/<y>.png` | OSM tile proxy |
| GET | `/images/<filename>` | Static image proxy |
