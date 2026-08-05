# RoadIQ — Onboarding Context (read this first)

## For any AI agent or developer joining this project

This file is the single source of truth for project state. If you're
Claude, Kiro, Cursor, or a human — read this before making changes.

## Current State

**Last updated:** 2026-08-05 ET (AI engine gap features: re-route alert, reservations, route memory, Celonis expansion, return load opportunities)

### Active server: `server.py` (Flask)
- NOT app.py (Streamlit is legacy/backup)
- Run with: `python server.py` → http://localhost:5002
- **Port is 5002** (changed from 5001 — ghost PID issue on dev machine)
- Frontend: `static/index.html` (SPA, phone-frame UI, 5-tab layout)

### AI Model
- Service: Amazon Bedrock
- Model: `amazon.nova-lite-v1:0` (active, no inference profile needed)
- SSL: Corporate proxy requires `verify=False` + `ssl._create_unverified_context`
- Old models (claude-3-5-sonnet-20241022) are RETIRED — do not use

### Data: ALL from Databricks (no hardcoded values)
- Host: pfj-sandbox-dev-east.cloud.databricks.com
- Catalog: `innovate`
- Tables in use:
  - `location.dim_line_of_business_offering` — stops, amenities, brands
  - `loyalty.dim_loyalty_household` — driver loyalty profile
  - `loyalty.fct_dm_guest_household_summary` — gallons, visits
  - `pos_transactions_inventory.fct_sale` — transaction history
  - `loyalty.fct_parking_demand_forecast` — real parking %
  - `team02.drive_shower_utilization` — real shower wait times
  - `price.fct_fuel_supply_price` — real diesel prices (~$3.45/gal)
  - `loyalty.fct_guest_mobile_offers` — personalized offers
- **Pilot-only filter** on all stop queries:
  `AND PRIMARY_STOREFRONT_BRAND IN ('PILOT', 'FLYING J', 'PILOT FLYING J')`
- Note: Sandbox has synthetic data (lat/lons don't match real US geography)
- Corridor bounding box query returns 0 hits → falls back to all OPEN stops globally

### PFJ 360 data — discovered, NOT yet integrated (2026-08-05)
Beyond the `innovate` catalog, the `dev` catalog contains ~172 tables under `dev.location` and
`dev.common` matching "pfj360"/"resource"/"amenity" — this is a much richer, more granular data
source than what `/api/plan` currently uses. Discovered via `scripts/search_pfj360.py`, inspected
via `scripts/inspect_pfj360_tables.py` and `scripts/decode_pfj360_references.py`. Key tables:

| Table | Rows | What it gives (vs. current `innovate` catalog data) |
|-------|------|------------------------------------------------------|
| `dev.location.pfj360ods_parking_parking` | 141,461 | Real per-space parking inventory by type (Truck/Gas/Diesel/RV/Bobtail) and Active/Inactive status — replaces the forecast-based `fct_parking_demand_forecast` estimate with actual counts |
| `dev.location.pfj360_offering` + `pfj360_offeringattribute` | 49,483 + 24,916 | Real amenity list per location: Showers (Active/Total Qty), ATM, CAT Scale, Air Vac, Mobile Fueling, Wifi, Pilot Coffee, DoorDash/GrubHub/Uber Eats, Lottery, Check Cashing |
| `dev.location.gpss_pfj360_location` | 12,785 | Master location table — full address, real lat/lon, store brand, 24hr flag |
| `dev.location.pfj360_storehours` | 19,328 | Real open/close hours by day of week |
| `dev.location.corpdata_location_amenity` | 30,297 | Location→amenity ID mapping (needs a reference table to decode `AMENITY_ID`, not yet found) |
| `dev.location.pfj360ods_location_truckstop` | 9,626 | Truck-stop master data — brand, diesel brand, status |

**Not yet wired into `databricks_client.py` or `/api/plan`.** This is the next natural upgrade:
replace forecast-based parking % and boolean shower/amenity flags with real PFJ 360 counts. Join
key is `LocationID` across most of these tables.

### Map Routing
- OSRM (free, no API key): router.project-osrm.org
- Returns real road geometry (3,400+ coordinate points Nashville→Atlanta)
- SSL verify=False required on all OSRM requests (corporate proxy)

### Plan Map (Trip Planner tab)
- **SVG-based, no tiles** — renders instantly with zero network calls
- `renderPlanMap(data)` in index.html draws route polyline + stop pins as inline SVG
- Dark background (`#1c1c1e`), Pilot red (`#DC1730`) route line
- Chosen stops: red circle + label; all others: grey circle
- Origin: white dot; Destination: green dot
- No Leaflet dependency for plan map (Leaflet only used on Routes tab)

### Celonis MCP (working — real JSON-RPC protocol)
- OAuth client credentials flow — MUST include `scope=mcp-asset.tools:execute` param
- Token URL: https://ai-context-model-pilot-pov.us-2.celonis.cloud/oauth2/token
- MCP server URL: https://ai-context-model-pilot-pov.us-2.celonis.cloud/studio-copilot/api/v1/mcp-servers/mcp/64c73b17-5383-4263-a6aa-58de560edf6d
- Protocol: JSON-RPC 2.0, SSE-framed responses (`event: message\ndata: {...}`)
- Handshake: `initialize` → `notifications/initialized` → `tools/call`
- Tools available: `load_data_location_info` (route → open Pilot/FJ locations), `load_data_driver_info` (firstname/lastname → driver HOS/status records)
- Implementation: `celonis_client.py` — do not use plain REST GET, this server only speaks MCP JSON-RPC
- Used for live Pilot location data as alternative/supplement to Databricks

### Celonis + Bedrock recommendation pipeline (how they connect)
Celonis and Databricks are DATA sources; Bedrock is the REASONING layer. Neither
data source talks to the LLM directly — server.py retrieves facts from both,
assembles a structured text context, then hands that to Bedrock (RAG pattern).

`/api/plan` flow:
1. Geocode from/to, build corridor bounding box
2. Pull stops from Databricks (`get_stops_in_corridor`) — parking %, shower wait, fuel price, loyalty
3. Pull driver HOS from Celonis (`get_driver_hos(firstname, lastname)`) — real hours-worked-today,
   used unless the caller explicitly overrides with `hos_hours_driven` in the request body
4. Cross-check chosen stops against Celonis's independent `load_data_location_info` feed for a
   "second source corroboration" signal (mentioned in the AI prompt when it agrees)
5. All of the above gets composed into one prompt string sent to `ask_ai()` (Bedrock)
6. Bedrock is instructed to only reason over what's in the prompt — never invent stops/prices

`hos_hours_driven` priority order: explicit request body value > real Celonis driver log > 0 default.
Response includes `hos.source` = `"celonis"` | `"manual"` | `"default"` so the frontend/tests can
tell which path was used.

### Celonis MCP tools — full inventory (verified 2026-08-05, discovery only)
Run `scripts/discover_celonis_tools.py` to re-list live. 3 tools currently exposed:

1. **`load_data_location_info`** — `{route (required), page, page_size}` → open Pilot/FJ locations
2. **`load_data_driver_info`** — schema as of 2026-08-05:
   `{lastname (required), firstname (required), dim_loyalty_id (required), page, page_size}`.
   Description now says: *"filtering the data using the drivers first and last name, license
   number, or loyalty id"*. This is a CHANGE from what we tested earlier (see bug section below) —
   `dim_loyalty_id` is now a documented, required field. **Not yet re-tested** whether it actually
   filters correctly server-side now — do that before relying on it.
3. **`trigger_action_flow_Update_Driver_Preferences`** — **INTEGRATED 2026-08-05.** A write-back tool
   (not data-loading):
   ```json
   {
     "Driver_ID": "string (required) — prompt the driver for it if not available",
     "Food_Preferences": "string (optional) — restaurants driver prefers at stops",
     "Shower_Preferences": "string (optional) — frequency/cleanliness preference"
   }
   → { "execution_result": "string" }
   ```
   Purpose per its description: *"store additional context you gain by chatting with the driver."*
   See "Celonis driver preference write-back (integrated)" section below for the full implementation.

### Celonis `load_data_driver_info` — confirmed bug + no ID workaround (2026-08-05)
- **Bug:** `firstname`/`lastname` args are not applied as a filter server-side. Calling with a
  name that cannot exist in any dataset ("Zzyzx Nonexistent99") returns the exact same 50 records,
  every time, byte-for-byte identical — not even random sampling.
  Reproduction: `scripts/test_celonis_filter_bug.py`
- **No ID workaround exists.** Tried passing `license_number`, `dim_loyalty_id`,
  `dim_loyalty_household_id`, `loyalty_household_id`, `driver_id`, `dim_driver_id` — every one is
  rejected server-side with `Extra inputs are not permitted [type=extra_forbidden]` (a strict
  Pydantic validator), despite the tool's advertised JSON schema claiming `additionalProperties: true`.
  The tool's own description text says "first and last name, **or license number**" — that's
  inaccurate; license_number is not accepted. Reproduction: `scripts/test_celonis_id_filters.py`
- **Ask for Celonis:** add a real filter parameter (ideally `dim_loyalty_household_id`, PFJ's actual
  identifier) to `load_data_driver_info`, and fix the description/schema to match real behavior.
- Until fixed, this tool cannot look up a specific driver by identity — `get_driver_hos()` is
  written correctly for when server-side filtering works, but can't be demoed accurately today.

### API Contract
| Method | Path | Body / Params | Returns |
|--------|------|---------------|---------|
| GET | `/api/driver` | — | Driver profile + Databricks loyalty data |
| GET | `/api/stop` | — | Recommended stop |
| GET | `/api/route` | — | OSRM route coords + stop pins |
| POST | `/api/plan` | `{from, to, prefs, hos_hours_driven}` | `{stops, all_stops, route_coords, from_coords, to_coords, itinerary, savings_detail, hos, offers}` |
| POST | `/api/ai` | `{mode: "plan"\|"chat", message}` | `{text, source}` + optional `preference_update: {food_preference, shower_preference, celonis_synced}` when mode=chat and a preference was detected |
| GET | `/api/fleet` | — | 15 drivers with loyalty tier, fuel_pct, fuel_miles, route |
| POST | `/api/stop_advice` | `{stop, from, to, prefs, hos_hours_driven}` | `{advice}` — GOOD STOP or WORTH SKIPPING verdict |
| GET | `/api/maintenance` | `?driver_id=N` (optional) | Maintenance data: DEF%, tire PSI%, oil life%, miles to service, alerts array |
| POST | `/api/poi` | `{lat, lon, radius_m}` | Nearby POIs by category (food/cafe/gym/park/library/cinema/mall/bowling/laundry/pharmacy). Falls back to demo data if Overpass unreachable. |
| POST | `/api/weather` | `{route_coords: [[lat,lon],...]}` | 5-point weather ribbon: `{points:[{lat,lon,label,icon,temp_f,wind_mph,precip_in,severity,description}], overall_severity}`. severity: ok/caution/severe. Open-Meteo, no API key. |
| GET | `/api/loads` | — | `{loads: [{id,origin,destination,cargo,miles,pickup,deliver_by,priority,assigned_driver,driver_name}]}` |
| POST | `/api/loads/assign` | `{load_id, driver_id, driver_name}` | `{ok, load_id, driver_id, driver_name}`. In-memory state, resets on server restart. |
| GET | `/api/fleet_savings` | — | `{pilot_price, benchmark_price, per_gal_savings, per_driver_weekly, fleet_weekly, fleet_annual, drivers, weekly_gallons}` |

### `/api/plan` response shape (important for frontend — verified against actual code 2026-08-05)
```json
{
  "from": "Nashville, TN", "to": "Atlanta, GA",
  "from_coords": [lat, lon], "to_coords": [lat, lon],
  "total_miles": 246, "drive_hours": "4h 37m", "total_gallons": 38,
  "stops": [...],           // AI-chosen stops (top 2), enriched with parking/shower/price/HOS flags
  "all_stops": [...],       // ALL corridor Pilot stops (for map + picker)
  "route_coords": [[lat,lon], ...],  // OSRM full geometry
  "savings": "$4",
  "savings_detail": { "fleet_price":..., "retail_price":..., "savings_per_gal":..., "total_gallons":..., "total_savings":... },
  "hos": { "hours_driven": 11.89, "hours_remaining": 0, "miles_remaining": 0, "source": "celonis" },
  "ai_plan": "...",         // AI-generated journey briefing text
  "fuel_prices": { "avg_net_price":..., "avg_gross_price":..., "avg_fleet_discount":..., "sample_count":... },
  "offers": [...]           // active Databricks offers for this driver
}
```
Note: `hos.source` is `"celonis"` (real driver log), `"manual"` (caller passed `hos_hours_driven`
in the request body), or `"default"` (neither available, defaults to 0h driven).

### `/api/stop_advice` — per-stop AI verdict
- Prompt instructs Nova Lite to return "GOOD STOP" or "WORTH SKIPPING" in 2-3 sentences
- Frontend colors verdict: green (`#d1fae5`) = GOOD STOP, red (`#fee2e2`) = WORTH SKIPPING
- Modal is a bottom sheet (`#advice-overlay` + `#advice-sheet`)

### Key Constraints
1. **Pilot-only** — AI prompt + SQL filter both enforce Pilot/Flying J stops only, never competitors
2. No hardcoded data — everything from Databricks or computed
3. Always fall back gracefully if any service is down
4. AWS session tokens expire — refresh `.env` when `ExpiredTokenException` appears in logs
5. Phone-frame UI targets 390px width, mobile-first
6. Anti-hallucination: LLM only sees data passed in the prompt

### Brand Colors (official Pilot Flying J)
- **Red:** `#DC1730` — primary brand color, used for: CTA buttons, active tab, route line, chosen stop markers, alert banners, AI labels
- **White:** `#FFFFFF` — backgrounds, card surfaces
- **Black:** `#000000` / near-black `#1c1c1e` — body text, dark surfaces
- UI utility only (not brand): `#30d158` (green = OK), `#ff9500` (orange = caution)
- Logo: `logo.svg` in `roadiq/` directory, served at `/logo.svg`, 373×153px

### 5-Tab Navigation
1. **Home** — Proactive alert, fuel bar, quick links, loyalty card, deals
2. **Plan Trip** — Origin/destination input, HOS slider, prefs chips → SVG map + itinerary + stop picker + weather ribbon + **3-way stop filter** (⭐ Optimized / 🗺️ All Stops / 🆚 Competitors)
3. **Fleet** — 15-driver fleet manager with KPI cards, fuel risk badges, loyalty tiers; fleet savings banner (Pilot vs national avg diesel); load assignment board (5 loads, assign driver → instant green tag)
4. **RoadIQ** — AI journey plan tab (legacy `/api/ai` endpoint)
5. **Chat** — Free-form Bedrock chat with quick prompts

### Weather Along Route — implementation notes
- **Endpoint:** `POST /api/weather` — called by `buildTrip()` in frontend after `/api/plan` resolves
- **Input:** `{route_coords: [[lat,lon], ...]}` — the full OSRM geometry from `/api/plan`
- **Sampling:** picks 5 points from route_coords (indices 0%, 25%, 50%, 75%, 100%) labeled Origin / 25% Mark / Midpoint / 75% Mark / Destination
- **Data source:** Open-Meteo `https://api.open-meteo.com/v1/forecast` — free, no API key, no corporate proxy issues (SSL verify=False still applied)
- **Per-point fetch:** `current=temperature_2m,wind_speed_10m,precipitation,weather_code` — returns metric units, server converts to °F and mph
- **Severity logic:** `ok` (default) → `caution` (wind > 40 km/h OR precip > 3mm) → `severe` (wind > 60 km/h OR precip > 10mm OR WMO code ≥ 61 [rain/snow/storm])
- **Frontend:** `#weather-section` shown after plan resolves; `.wx-chip` per point, `.wx-alert-banner` for caution/severe overall_severity
- **WMO codes mapped:** 0=Clear ☀️, 1-3=Partly Cloudy ⛅, 45-48=Foggy 🌫️, 51-67=Rain 🌧️, 71-77=Snow ❄️, 80-82=Showers 🌦️, 95-99=Storm ⛈️

### 3-Way Stop Filter + Competitor View — implementation notes
- **Filter bar:** rendered below the AI itinerary in `#plan-results`, three buttons: ⭐ Optimized / 🗺️ All Stops / 🆚 Competitors
- **Optimized mode (default):** shows only stops where `is_chosen === true` in `renderAllStops()`
- **All Stops mode:** shows every Pilot stop returned by `/api/plan` (`all_stops` array)
- **Competitors mode:** lazily fetches `/api/competitors` on first click (cached per trip via `dataset.loaded` flag); clears on new trip in `buildTrip()`
- **`/api/competitors` endpoint:** returns 3 demo stops (Love's Manchester TN mi 110, TA Petro Chattanooga TN mi 175, BP Calhoun GA mi 312). Each has: brand, name, city, state, mile_marker, diesel_price (Pilot retail + markup), amenities_missing_vs_pilot (list of strings), nearest_pilot object {name, city, miles_away, diesel_price, perks[]}
- **Competitor card UI:** red left border, brand label, retail price in red, missing features as red `× Tag` chips, green "Pilot wins" sub-card with nearest Pilot name + fleet price + green checkmark perks list
- **Summary banner:** dark banner showing avg Pilot savings vs competitors on this route (e.g. `$0.180/gal`)
- **`askAboutStop(id)`:** now accepts `lob_id` string (preferred) or numeric index fallback — avoids index mismatch when filter hides some stops
- **Filter resets** to 'optimized' and competitor cache clears each time `buildTrip()` is called

### Load Assignment Board — implementation notes
- **Endpoints:** `GET /api/loads` + `POST /api/loads/assign`
- **State:** in-memory `_load_assignments` dict — resets on server restart (demo only, no DB persistence)
- **Assignment flow:** frontend `renderLoadBoard()` populates driver dropdown from `_fleetDrivers` cache; `assignLoad(loadId)` resolves driver name from `_fleetDrivers` client-side and POSTs `{load_id, driver_id, driver_name}` so server doesn't need a Databricks lookup on assign
- **Re-render:** `loadLoadBoard(true)` skips driver re-fetch (uses `_fleetDrivers` cache), re-fetches only `/api/loads` for instant update
- **Visual states:** unassigned = dropdown + red Assign button; assigned = green `✅ driver name` tag; high priority = red left border + HIGH PRIORITY badge
- **5 demo loads:** L001 Nashville→Atlanta (General Freight), L002 Memphis→Charlotte (Refrigerated, HIGH), L003 Louisville→Atlanta (Hazmat Fuel, HIGH), L004 Cincinnati→Tampa (Auto Parts), L005 Indianapolis→Birmingham (Consumer Goods)

### Fleet Savings Banner — implementation notes
- **Endpoint:** `GET /api/fleet_savings`
- **Benchmark:** `NATIONAL_AVG = 3.689` $/gal (hardcoded national avg diesel — update periodically)
- **Pilot price:** pulled live from `fct_fuel_supply_price` via `get_fuel_prices()` (same call `/api/plan` uses)
- **Formula:** `per_gal_savings = national_avg - pilot_price`; `fleet_weekly = per_gal_savings × 180 gal/driver/week × 15 drivers`; `fleet_annual = fleet_weekly × 52`
- **At current prices (~$3.448 Pilot vs $3.689 national):** $0.241/gal → $650.70/week → $33,836/year
- **Frontend:** dark card at top of Fleet tab, green `$XXX.X` headline, 4 sub-stats row (Pilot $/gal, Natl Avg $/gal, Savings/gal, Annual Est.)

### Celonis driver preference write-back (integrated 2026-08-05)
Makes the Chat tab stateful: preferences mentioned in conversation now persist and influence
future `/api/plan` recommendations, within the current server process.

**Pipeline:**
1. Driver sends a chat message → `POST /api/ai {mode: "chat", message: "..."}`
2. After Bedrock generates the chat reply, `server.py`'s `_extract_and_save_preferences(user_message, driver_id)`
   runs a SEPARATE, small Bedrock call: a JSON-only extraction prompt asking "does this message
   express a food or shower preference?" → `{"food_preference": "..."|null, "shower_preference": "..."|null}`
3. If either is non-null:
   - Cache is updated immediately: `_driver_preferences_cache[driver_id]["food_preference"/"shower_preference"]`
   - `celonis_client.celonis_update_driver_preferences(driver_id, food, shower)` is called (best-effort;
     failure here does NOT block the cache update or the chat response)
4. `/api/ai` response includes `preference_update: {food_preference, shower_preference, celonis_synced}`
   when something was detected (omitted otherwise)
5. On the next `/api/plan` call, `pref_info` is built from `_driver_preferences_cache` and injected
   into the Bedrock itinerary prompt alongside `loyalty_info` and `hos_info`

**Why there's an in-process cache alongside the Celonis write:** Celonis's OWN read-side tool
(`load_data_driver_info`) cannot reliably filter/read back by driver identity yet (see bug section
above) — so relying purely on writing-then-reading-back from Celonis would not work today. The
cache is what actually powers the feature THIS session; the Celonis write is real and verified
(returns `{"execution_result": "Action flow executed successfully"}`), and will pay off once
Celonis's read-side filtering is fixed or once a real backing store reads from Celonis in production.

**Driver_ID used:** `str(DEMO_DRIVER["id"])` = `"7"` (this app's local driver id, NOT confirmed to be
the same identifier space as `dim_loyalty_id` — that mapping is still an open question, but the
write succeeds regardless of which ID space Celonis's backing store actually keys on internally).

**Functions added:**
- `celonis_client.celonis_update_driver_preferences(driver_id, food_preferences=None, shower_preferences=None)`
  → `{"execution_result": str}` or `None` on failure
- `celonis_client._call_tool_raw(tool_name, arguments)` → `(text_block, is_error)` — new shared
  primitive since action-flow tools return plain text/dict, not a JSON list like data-loading tools
- `server._extract_and_save_preferences(user_message, driver_id)` → preference update dict or `None`

**Verified with:**
- `scripts/test_update_preferences.py` — direct write, confirms Celonis accepts the call
- `scripts/test_preference_loop.py` — full loop: chat message → extraction → Celonis write →
  cache → next `/api/plan` call's prompt includes the learned preference (confirmed via
  `pref_info` string construction; whether Bedrock's 110-word summary explicitly names the
  preference in every response is generation variance, not a plumbing bug — the prompt text is
  reliably correct)

### AI Engine Gap Features (added 2026-08-05)
Five features closing the gap between "stop recommendation tool" and "AI-powered journey optimizer":

**1. Proactive Re-Route Alert**
- 15s after `renderTrip()` resolves, `scheduleRerouteAlert(data)` fires a `setTimeout`
- Randomizes from 3 scenarios: parking spike, price jump, shower wait spike — using first stop name
- Dark `.reroute-banner` card at top of `#plan-results` with pulsing red dot, 2 action buttons
- "Show Alternatives" scrolls/highlights first stop card + toast; "Keep My Plan" dismisses
- Timer cleared on each new trip build (no stale alerts)

**2. Parking/Shower Reservation CTA**
- `reserve-section` shown in every stop advice modal when opened via `askAboutStop()`
- `makeReservation(type)` generates PFJ-XXXXX code, shows aligned `.reserve-confirm` black card
- Also fires `POST /api/ai` with a preference message → triggers Celonis write-back silently

**3. Repeat Route Memory**
- `saveRouteMemory(from, to)` stores trips in `localStorage` key `roadiq_recent_routes` (max 10)
- `checkRepeatRoute()` called on page load — shows banner only after ≥2 runs on same route
- `loadRepeatRoute()` pre-fills form inputs and calls `buildTrip()` instantly
- Route key: `(from + '|' + to).toLowerCase()`

**4. Celonis Preference Write-Back Expansion**
- `_extract_and_save_preferences()` now detects 5 fields (was 2):
  `food_preference`, `shower_preference`, `preferred_stop`, `avoided_stop`, `typical_fuel_gallons`
- All 5 injected into `/api/plan` Bedrock prompt via `pref_info`
- `avoided_stop` explicitly tells AI: "do NOT recommend this location"
- Bedrock extraction prompt now allows 120 tokens (was 80) to fit all 5 fields

**5. Return Load Opportunities (earnings co-pilot)**
- New endpoint: `GET /api/return_loads`
- Returns 3 ranked loads from drop-off city, sorted by net_earnings descending
- Net earnings = gross_rate − (fuel_gal × real Pilot fleet price from Databricks)
- Response includes: `gross_rate`, `pilot_fuel_cost`, `net_earnings`, `gross_cpm`, `net_cpm`, `window_closes_min`, `loads_competing`, `urgency`, `opportunity_cost_per_hour`
- Frontend `loadReturnOpps()` called at end of `renderTrip()` — lazy, non-blocking
- "Claim This Load →" dims cards, shows `.load-claimed-confirm` confirmation bar
- **Key differentiator:** only RoadIQ knows the real fleet fuel price, so only RoadIQ can show true net earnings (not just gross rate like DAT/Truckstop)

### Push for Points Elite — loyalty tier implementation
- **Program name:** MyRewards (real value from Databricks `LOYALTY_CARD_TYPE`)
- **Elite threshold:** 1,200 gallons/month — `ELITE_THRESHOLD = 1200` constant in `index.html`
- **"Platinum" removed everywhere** — all server.py prompts, frontend badges, and AI chat now use "Elite". `loyalty_tier` from Databricks may return "MyRewards" (program name, not tier level) — frontend normalizes `.replace(/platinum/i, 'Elite')`
- **Monthly gallon estimate:** Databricks `total_gallons` is lifetime cumulative. Monthly = `total_gallons / months_since_issue_date`. `loyalty_issue_date` is now passed through `/api/driver` response from `loyalty["issue_date"]`
- **Frontend elements:** `#elite-progress-card` (gold-bordered card), `#elite-fill` (gold gradient bar, transitions to width%), `#elite-gal-done` / `#elite-gal-left` labels. Hidden if `total_gallons === 0`.
- **States:** in-progress (red "N gal to Elite") vs achieved (green "✅ Elite achieved!")
- **Loyalty card subtitle** dynamically shows "N gal away from Elite" while not yet achieved; switches to "2× points on every fill-up" once achieved

### What is NOT yet built (next opportunities)
- **Weigh station locations** — static JSON from FHWA (discussed, not built). Would show as pins on SVG map or listed in itinerary for the corridor.
- **Fuel price trend sparkline** — "is price going up tomorrow?" prediction. Would require historical `fct_fuel_supply_price` rows by date, simple delta or ML model.
- **PFJ 360 integration** — replace `innovate` catalog parking/shower/amenity data with richer `dev` catalog PFJ 360 tables (see PFJ 360 section above). Join key: `LocationID`.
- **Persistent load assignments** — currently in-memory. Production would need a DB table or Celonis action flow.
- **Frontend UI for preference updates** — `/api/ai` chat now returns `preference_update` when detected, but `static/index.html`'s chat handler doesn't yet surface this to the driver (e.g. a small toast "Got it — I'll remember you prefer Wendy's"). Currently silent/backend-only.
- **Re-test Celonis `dim_loyalty_id` filtering** — schema now accepts it as a required field; unconfirmed whether it actually filters server-side (see Celonis bug section).

## Rules for making changes

1. After ANY change, update this file AND `PROJECT_STATUS.md`
2. If you add a new API endpoint, add it to the API Contract table
3. If you change data sources, update the Data section
4. Test changes with `python scripts/test_endpoints.py`
5. If Bedrock model changes, update the AI Model section
6. Do NOT switch from SVG plan map back to tiled Leaflet — tiles block screenshot renderer

## Key files
- `server.py` — Flask backend (all endpoints)
- `static/index.html` — Frontend SPA (5 tabs, all JS inline)
- `databricks_client.py` — All Databricks queries (8 functions, `innovate` catalog only so far)
- `celonis_client.py` — Celonis MCP JSON-RPC client (locations + driver HOS)
- `.env` — Secrets (NEVER commit — contains AWS + Databricks + Celonis tokens)
- `logo.svg` — Real Pilot Flying J logo (SVG wrapping base64 PNG)
- `scripts/test_endpoints.py` — Integration test for `/api/*` endpoints
- `scripts/test_plan_endpoint.py` — Integration test for `/api/plan` + HOS + Celonis corroboration
- `scripts/test_celonis_filter_bug.py` — Reproduces the driver-name-filter bug (evidence for Celonis)
- `scripts/test_celonis_id_filters.py` — Proves no ID param works as a driver filter (evidence for Celonis)
- `scripts/discover_celonis_tools.py` — Lists all Celonis MCP tools + full schemas (discovery only, no writes)
- `scripts/audit_real_vs_hardcoded.py` — Verify what's real
- `scripts/search_pfj360.py` — Discovers all PFJ 360 tables across catalogs
- `scripts/inspect_pfj360_tables.py` — Inspect PFJ 360 table columns/values
- `scripts/test_celonis_client.py` — Basic Celonis client smoke test (locations + driver call)
- `scripts/list_bedrock_models.py` — Lists available Bedrock models in this AWS account (use when `ResourceNotFoundException` appears — model may have been retired)
- `scripts/test_bedrock.py` — Minimal Bedrock connectivity smoke test
- `scripts/refresh_celonis_token.ps1` — Manually refresh a Celonis OAuth token for debugging
- `scripts/test_update_preferences.py` — Direct test of `celonis_update_driver_preferences()` write
- `scripts/test_preference_loop.py` — Full end-to-end test: chat → extraction → Celonis write → `/api/plan` prompt
- `.kiro/steering/onboarding.md` — THIS FILE
- `PROJECT_STATUS.md` — Current build status
- `.kiro/CHANGELOG.md` — Auto-generated newest-first log of every .py/.html save. **Read this first** when resuming a session to see what changed without opening every file.
- `.kiro/hooks/sync-status-on-save.json` — PostFileSave hook: silently updates timestamps in PROJECT_STATUS.md + onboarding.md and appends to CHANGELOG.md on every .py/.html save. No manual "update docs" command needed.
