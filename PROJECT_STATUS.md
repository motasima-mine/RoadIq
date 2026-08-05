# RoadIQ — Project Status

**Last updated:** 2026-08-05 ET (AI engine gap features: re-route alert, reservations, route memory, Celonis expansion, return load opportunities)

## All Features Complete

| Feature | Status | Details |
|---------|--------|---------|
| Origin/destination input | ✅ | Pre-filled Nashville→Atlanta, editable |
| Multi-stop optimized route | ✅ | Nova Lite chooses best stops, full itinerary |
| Fleet manager view | ✅ | 15 drivers, KPI cards, fuel risk badges |
| Real stop data from Databricks | ✅ | Pilot-only filter on all queries |
| Loyalty-aware recommendations | ✅ | Tier, gallons, visits from Databricks |
| Cost savings calculator | ✅ | Real gross vs net price from `fct_fuel_supply_price` |
| HOS-aware stop timing | ✅ | Slider 0-11h, miles-remaining, break alerts |
| Proactive alerts | ✅ | Home screen alert banner with stop recommendation |
| Map with route + all stops | ✅ | SVG map (no tiles), dark bg, red route line |
| Per-stop "Ask AI" modal | ✅ | Bottom sheet: GOOD STOP / WORTH SKIPPING verdict |
| Pilot-only enforcement | ✅ | SQL filter + AI system prompt — no competitors |
| Brand colors verified | ✅ | #DC1730 red throughout, real logo.svg in header |
| Truck maintenance alerts | ✅ | Home alert, fleet KPI, driver row badges, tap-to-detail sheet |
| Break time activities nearby | ✅ | "Things To Do On Your Break" — coffee, food, gym, library, shopping, laundry. Shows when HOS ≥ 4h; Overpass OSM with demo fallback for proxy environments |
| Celonis HOS-aware recommendations | ✅ | `/api/plan` pulls real driver hours-worked from Celonis (`get_driver_hos`) to drive HOS urgency in the AI prompt; falls back to manual slider or 0h default |
| Celonis location corroboration | ✅ | Chosen Databricks stops are cross-checked against Celonis's independent location feed; agreement is mentioned in the AI prompt as a confidence signal |
| Weather along route | ✅ | 5-point weather ribbon on Plan Trip tab — temp, wind, precip, severity (ok/caution/severe). Open-Meteo API, alert banner for severe conditions |
| Load assignment board | ✅ | Fleet tab load board: 5 loads, driver dropdown, instant assign with green ✅ tag. In-memory state, driver name resolved from fleet cache |
| Pilot vs competitor fleet savings | ✅ | Fleet tab banner: Pilot $/gal vs national avg diesel → weekly/annual fleet savings estimate. Real price from Databricks `fct_fuel_supply_price` |
| Push for Points Elite progress | ✅ | Home tab loyalty card shows gold progress bar toward 1,200 gal/mo Elite threshold. Real gallons from Databricks, monthly estimate derived from lifetime total ÷ account age. "Platinum" removed everywhere — program is MyRewards, tier is Elite. |
| PFJ 360 data discovery | 🔍 Discovered, not integrated | ~172 tables found in `dev.location`/`dev.common` catalogs with real parking space counts, real amenity lists, and store hours — richer than current `innovate` catalog data. See onboarding.md for table list. Next step: wire into `databricks_client.py` |
| Celonis driver preference write-back | ✅ | Chat messages are passed through a Bedrock extraction prompt to detect food/shower preferences; detected preferences are written to Celonis via `trigger_action_flow_Update_Driver_Preferences` AND cached in-process (`_driver_preferences_cache`), so `/api/plan`'s AI prompt reflects them on the very next request. Verified end-to-end with `scripts/test_preference_loop.py` — write confirmed via `celonis_synced: true`. |
| 3-way stop filter + competitor view | ✅ | Plan Trip tab: ⭐ Optimized (AI-chosen stops only) / 🗺️ All Stops (every Pilot stop on route) / 🆚 Competitors (competitor prices + why Pilot wins at nearest location). Competitor section lazy-loads from `/api/competitors`, shows savings banner ($0.18/gal avg), per-competitor card with red "missing vs Pilot" tags and green "Pilot wins" card with specific perks. Filter resets to Optimized on each new trip. |
| Brand color audit | ✅ | All off-brand greens (#30d158, #00994a, etc.) replaced with brand-only colors: #DC1730 red, #1c1c1e black, #FFFFFF white. Verified across all CSS, inline styles, and JS. |
| Positive language + navigation CTA | ✅ | "Competitors" → "Compare Stops", "Worth Skipping" → "📋 PLAN AHEAD", "GOOD STOP" → "✅ GREAT STOP". Added `navigateToStop()` with Google Maps deep-link on stop cards, advice modal, and competitor Pilot win cards. |
| Real product images | ✅ | Deal cards on home tab show full-bleed PNGs (`gatorade.png` = Red Bull BOGO, `lunch offer.png` = $8 lunch deal) served via `/images/<filename>` Flask route. |
| Proactive re-route alert | ✅ | 15s after trip builds, a dark banner appears at top of results: RoadIQ simulates watching parking/price/shower conditions and surfaces an actionable alternative. "Show Alternatives" highlights first stop card + toast; "Keep My Plan" dismisses. Randomized from 3 realistic scenarios. |
| Parking/shower reservation CTA | ✅ | "Reserve at This Stop" section in every stop advice modal. Tap parking or shower → black confirmation card with PFJ-XXXXX code appears. Also fires silent Celonis preference write-back. |
| Repeat route memory | ✅ | `localStorage` stores every trip. After 2+ runs on same route, a red-accented banner appears above the plan form with one-tap re-run. Route key is `from|to` lowercased; keeps last 10 routes. |
| Celonis preference write-back expansion | ✅ | Extraction prompt now detects 5 fields: food preference, shower preference, preferred stop, avoided stop, typical fuel gallons. All cached in `_driver_preferences_cache` and injected into `/api/plan` Bedrock prompt. "Avoid stop" explicitly instructs AI not to recommend that location. |
| Return load opportunities (earnings co-pilot) | ✅ | `/api/return_loads` returns 3 ranked return loads from drop-off city. Net earnings = gross rate − real Pilot fuel cost (live from Databricks `fct_fuel_supply_price`). Shown at bottom of every trip result: gross, fuel deduction, net $/mi, window urgency, competing drivers. "Claim This Load →" dims cards + shows confirmation. This is the key super-app gap — only RoadIQ can show true net earnings because it knows the real fleet fuel price. |

## Component Health

| Component | Status | Details |
|-----------|--------|---------|
| Flask server | ✅ | `server.py` on **port 5002** |
| Frontend SPA | ✅ | `static/index.html` — 5 tabs |
| Amazon Bedrock | ✅ | `amazon.nova-lite-v1:0` working |
| Databricks | ✅ | 8 tables wired, real data flowing |
| OSRM routing | ✅ | 247 miles, 3,400+ route points |
| SVG plan map | ✅ | Instant render, no tiles, no network calls |
| Stop advice API | ✅ | `/api/stop_advice` → Nova Lite verdict |
| Fleet API | ✅ | `/api/fleet` → 15 drivers |
| Parking forecast | ✅ | Real % from `fct_parking_demand_forecast` |
| Shower wait | ✅ | Real minutes from `drive_shower_utilization` |
| Fuel prices | ✅ | ~$3.45/gal from `fct_fuel_supply_price` |
| Loyalty data | ✅ | Tier, gallons, visits from Databricks |
| Driver offers | ✅ | Active offers from `fct_guest_mobile_offers` |

## Known Limitations

- AWS session tokens expire (1-12 hours) — need manual `.env` refresh when `ExpiredTokenException` appears
- Databricks sandbox has synthetic lat/lons (don't match real US geography)
- Corridor stop query returns 0 in Nashville→Atlanta bounding box → falls back to all OPEN Pilot stops globally (~12 locations)
- With production data the corridor query would return actual I-40/I-75 stops
- Corporate network requires SSL verification disabled on all external requests

## File Structure

```
roadiq/
├── server.py              ← ACTIVE SERVER (Flask, port 5001)
├── static/index.html      ← Frontend SPA (5-tab phone UI, all JS inline)
├── databricks_client.py   ← 8 Databricks query functions
├── celonis_client.py      ← Celonis MCP client (JSON-RPC) — locations, driver HOS, driver preference write-back
├── logo.svg               ← Real Pilot Flying J logo (served at /logo.svg)
├── data/                  ← Local JSON fallback data
├── prompts/               ← LLM prompt templates
├── scripts/               ← Test & utility scripts
├── .env                   ← Secrets (NEVER commit)
├── .kiro/steering/        ← AI assistant instructions (onboarding.md)
├── app.py                 ← LEGACY (Streamlit, not used)
└── README.md              ← Setup instructions
```

## Full Tech Stack

See `TECH_STACK.md` for complete breakdown of every technology, version, and why it was chosen.

## API Endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/driver` | Driver profile + Databricks loyalty |
| GET | `/api/stop` | Recommended stop |
| GET | `/api/route` | OSRM route geometry + stop pins |
| POST | `/api/plan` | Full plan: stops, all_stops, SVG map data, AI itinerary, savings, HOS, offers |
| POST | `/api/ai` | Chat or plan text from Bedrock |
| GET | `/api/fleet` | 15 drivers with fuel/loyalty/route status |
| POST | `/api/stop_advice` | Per-stop GOOD STOP / WORTH SKIPPING AI verdict |
| GET | `/api/maintenance` | Maintenance status for all drivers (or `?driver_id=N` for one) |
| POST | `/api/poi` | Nearby POIs for rest stop — `{lat, lon, radius_m}` → categories of places |
| POST | `/api/weather` | Weather along route — `{route_coords}` → 5-point ribbon with temp, wind, precip, severity |
| GET | `/api/loads` | All 5 loads with current assignment state |
| POST | `/api/loads/assign` | Assign driver to load — `{load_id, driver_id, driver_name}` → `{ok, driver_name}` |
| GET | `/api/fleet_savings` | Pilot vs national avg diesel → per-gal/weekly/annual fleet savings |
| GET | `/api/competitors` | 3 demo competitor stops (Love's, TA Petro, BP) with retail price, missing features vs Pilot, nearest Pilot location with savings perks |
| GET | `/api/return_loads` | 3 ranked return loads from drop-off city. Net earnings = gross rate − real Pilot fuel cost. Fields: gross_rate, pilot_fuel_cost, net_earnings, net_cpm, window_closes_min, loads_competing, urgency. |
| GET | `/images/<filename>` | Serves PNGs from roadiq/ root (gatorade.png, lunch offer.png). Bypasses corporate proxy. |

## Databricks Tables (`innovate` catalog — currently wired into the app)

1. `innovate.location.dim_line_of_business_offering` — ~12 OPEN Pilot/Flying J locations
2. `innovate.loyalty.dim_loyalty_household` — loyalty profiles
3. `innovate.loyalty.fct_dm_guest_household_summary` — gallons/visits
4. `innovate.pos_transactions_inventory.fct_sale` — transactions
5. `innovate.loyalty.fct_parking_demand_forecast` — parking %
6. `innovate.team02.drive_shower_utilization` — shower waits
7. `innovate.price.fct_fuel_supply_price` — diesel prices
8. `innovate.loyalty.fct_guest_mobile_offers` — personalized offers

## PFJ 360 Tables (`dev` catalog — discovered, NOT yet wired in)

See `.kiro/steering/onboarding.md` "PFJ 360 data" section for the full table list and details.
Highlights: `dev.location.pfj360ods_parking_parking` (real parking space inventory, 141K rows),
`dev.location.pfj360_offering` (real amenity list per location, 49K rows).

## Celonis MCP (working, separate from Databricks)

3 tools exposed as of 2026-08-05 (verified via `scripts/discover_celonis_tools.py`, discovery only — no writes performed):

- `load_data_location_info` — real-time Pilot/FJ open locations along a route (used for corroboration in `/api/plan`)
- `load_data_driver_info` — driver HOS/status records (used for `hos.source: "celonis"` in `/api/plan`).
  **Schema update noticed 2026-08-05:** now advertises a `dim_loyalty_id` filter field (required,
  alongside firstname/lastname) and its description now mentions "license number, or loyalty id" —
  this looks like Celonis may have already started addressing the filtering bug we reported. **Not
  yet re-tested** to confirm `dim_loyalty_id` actually filters correctly server-side — next step.
- `trigger_action_flow_Update_Driver_Preferences` — **INTEGRATED 2026-08-05.**
  A write-back action (not a data-loading tool) that stores a driver's Food/Shower preferences into
  Celonis, keyed by `Driver_ID`. Now wired into the Chat tab: `celonis_client.celonis_update_driver_preferences()`
  calls it; `server.py`'s `_extract_and_save_preferences()` runs a Bedrock extraction prompt on every
  chat message to detect preferences, writes them via Celonis, and caches them in
  `_driver_preferences_cache` (in-process dict) since Celonis's own read-side tool
  (`load_data_driver_info`) can't reliably filter by driver identity yet (see bug section below).
  `/api/plan` reads the cache and injects learned preferences into its Bedrock prompt as
  `pref_info`. Using `dim_loyalty_id`-equivalent driver id (`DEMO_DRIVER["id"]` = "7") as `Driver_ID`.
  Verified end-to-end: `scripts/test_update_preferences.py` (direct write) and
  `scripts/test_preference_loop.py` (full chat → Celonis → plan loop).

## Dev Tooling

- **`.kiro/hooks/sync-status-on-save.json`** — PRIMARY auto-doc hook. Fires on every `.py`/`.html` save. Updates `**Last updated:**` in PROJECT_STATUS.md and onboarding.md, prepends a line to `.kiro/CHANGELOG.md`. Silent — no user prompt. Both Claude and Kiro should read `.kiro/CHANGELOG.md` at session start to catch up on recent changes.
- **`.kiro/CHANGELOG.md`** — Auto-generated, newest-first. Read this to see what was touched without diffing every file.
- **`.kiro/hooks/auto-document-changes.json`** — fires on every `.py`/`.html`/`.json`/`.txt`/`.toml`/`.yml`
  save and reminds the agent to update this file. Was silently broken since creation: the `matcher`
  regex was over-escaped (`\\\\.` decodes to two literal backslashes, not one escaped dot) so it
  never matched any real file path. Fixed 2026-08-05 to `\\.` (a single escaped dot). Verified the
  fix by testing the regex directly and confirming the hook fired on the next save.
- **`.kiro/hooks/auto-docs.yaml`** — separate, more elaborate hook that generates docs and publishes
  to Confluence via `scripts/publish_to_confluence.py`. Requires `CONFLUENCE_URL`/`CONFLUENCE_EMAIL`/
  `CONFLUENCE_API_TOKEN`/`CONFLUENCE_SPACE_KEY` env vars — not currently configured/verified working.
- **`.kiro/hooks/celonis-token-check.json`** — SessionStart reminder about the 15-min Celonis token expiry.

## Brand Colors (do not change)

| Color | Hex | Used for |
|-------|-----|----------|
| Pilot Red | `#DC1730` | CTA buttons, active tab, alert banners, route line, stop markers |
| White | `#FFFFFF` | Backgrounds, card surfaces |
| Black | `#1c1c1e` | Body text, dark UI surfaces |
| Logo | `logo.svg` | Header only — do not replace with text |
