# RoadIQ — Known Issues & Hard-Won Fixes

Read this before touching server.py or index.html.
These bugs have been fixed once. Don't reintroduce them.

---

## 1. Corridor stops returning 0 for long/diagonal routes
**Symptom:** "No stops found in this corridor" for routes like Nashville→Dallas.  
**Root cause:** `MAX_PERP_DEG = 0.5` (fixed ~35mi) is too tight for long diagonal routes.  
**Fix:** Scale with route length: `MAX_PERP_DEG = min(2.0, max(0.5, route_len_deg * 0.20))`  
**File:** `server.py` around line 517

---

## 2. Return loads showing wrong origin city
**Symptom:** Driver going Nashville→Dallas sees loads from Atlanta.  
**Root cause:** `_RETURN_LOADS` was a hardcoded list with `origin: "Atlanta, GA"`.  
**Fix:** `_RETURN_LOADS_BY_CITY` dict keyed by destination city. `/api/return_loads` reads `_last_plan["to"]` (set on every `/api/plan` call) and picks the matching load set.  
**File:** `server.py` — `_last_plan`, `_RETURN_LOADS_BY_CITY`, `api_return_loads()`

---

## 3. Chat answering questions about the wrong route
**Symptom:** Driver planned Nashville→Dallas, chat says "Knoxville is 95 miles ahead" or mentions Fort Myers, FL.  
**Root cause:** Chat prompt hardcoded `Nashville→Atlanta`. Also, `_build_chat_stops_context()` queries a fixed Nashville→Atlanta bbox from Databricks — if that returns nothing, fallback is `LOCATIONS` which has no geographic filter.  
**Fix:** Chat prompt now reads `_last_plan["from/to"]` for route context.  
**Full fix:** `_build_chat_stops_context()` now uses `_last_plan` coords to build a dynamic corridor bbox and filters `LOCATIONS` to that corridor. Cache busts when route changes. Databricks stops validated against US lat bounds (24–50°N) before use — synthetic-coord stops are rejected.  
**File:** `server.py` — `/api/ai` chat branch

---

## 4. Static images (gatorade.png, lunch offer.png) returning 404
**Symptom:** Deal cards on Home tab show broken images.  
**Root cause:** `/images/<filename>` route used `send_from_directory(_base, filename)` where `_base` is the repo root, but images live in `static/images/`.  
**Fix:** `send_from_directory(os.path.join(_base, "static", "images"), filename)`  
**File:** `server.py` — `serve_image()`

---

## 5. Home tab hardcoded to Knoxville / Nashville→Atlanta
**Symptom:** Home alert always shows "Pilot Knoxville #198 ~95 miles" even when user planned a different route.  
**Root cause:** Alert banner HTML was static text.  
**Fix:** Pre-trip state ("Ready to optimize your route"). After `buildTrip()` resolves, `updateHomeAlert(data)` populates from real `/api/plan` response. Persisted to `localStorage` key `roadiq_last_home_alert`.  
**File:** `static/index.html` — `updateHomeAlert()`, home alert HTML

---

## 6. OSM tiles hanging / blocking browser
**Symptom:** Leaflet map tiles time out, browser hangs on corporate network.  
**Root cause:** Corporate network blocks direct calls to `tile.openstreetmap.org`.  
**Fix:** Flask proxy endpoint `/tiles/{z}/{x}/{y}.png` using `ssl._create_unverified_context()`. Returns 1×1 transparent PNG on failure — never hangs.  
**File:** `server.py` — `proxy_tile()`

---

## 7. Navigation "Go" button blocked
**Symptom:** `window.open('https://maps.google.com/...')` blocked in preview webview.  
**Fix:** `navigateToStop()` shows an in-app toast with a tappable `<a>` link instead.  
**File:** `static/index.html` — `navigateToStop()`

---

## Rules
- After fixing any bug, add it here.
- After any refactor, check this file to make sure you haven't reintroduced a listed fix.
- `_last_plan` is the single source of truth for the active route — always read it in `/api/return_loads` and `/api/ai` chat mode.
