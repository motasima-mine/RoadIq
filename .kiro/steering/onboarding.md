# RoadIQ — Onboarding Context (read this first)

## For any AI agent or developer joining this project

This file is the single source of truth for project state. If you're
Claude, Kiro, Cursor, or a human — read this before making changes.

## Current State

**Last updated:** 2026-08-05 ET

### Active server: `server.py` (Flask)
- NOT app.py (Streamlit is legacy/backup)
- Run with: `python server.py` → http://localhost:5001
- **Port is 5001** (changed from 5000 — ghost PID issue on dev machine)
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

### Celonis MCP (optional)
- OAuth client credentials flow
- Token URL: https://ai-context-model-pilot-pov.us-2.celonis.cloud/oauth2/token
- Used for live Pilot location data as alternative to Databricks

### API Contract
| Method | Path | Body / Params | Returns |
|--------|------|---------------|---------|
| GET | `/api/driver` | — | Driver profile + Databricks loyalty data |
| GET | `/api/stop` | — | Recommended stop |
| GET | `/api/route` | — | OSRM route coords + stop pins |
| POST | `/api/plan` | `{from, to, prefs, hos_hours_driven}` | `{stops, all_stops, route_coords, from_coords, to_coords, itinerary, savings_detail, hos, offers}` |
| POST | `/api/ai` | `{mode: "plan"\|"chat", message}` | `{text, source}` |
| GET | `/api/fleet` | — | 15 drivers with loyalty tier, fuel_pct, fuel_miles, route |
| POST | `/api/stop_advice` | `{stop, from, to, prefs, hos_hours_driven}` | `{advice}` — GOOD STOP or WORTH SKIPPING verdict |

### `/api/plan` response shape (important for frontend)
```json
{
  "stops": [...],           // AI-chosen stops (2-3)
  "all_stops": [...],       // ALL corridor Pilot stops (for map + picker)
  "route_coords": [[lat,lon], ...],  // OSRM full geometry
  "from_coords": [lat, lon],
  "to_coords": [lat, lon],
  "itinerary": "...",       // AI-generated text
  "savings_detail": {...},  // retail/fleet/per_gal/gallons/total
  "hos": { "hours_driven": 0, "remaining": 11.0, "miles_left": 605 },
  "offers": [...]           // active Databricks offers for this driver
}
```

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
2. **Plan Trip** — Origin/destination input, HOS slider, prefs chips → SVG map + itinerary + stop picker
3. **Fleet** — 15-driver fleet manager with KPI cards, fuel risk badges, loyalty tiers
4. **RoadIQ** — AI journey plan tab (legacy `/api/ai` endpoint)
5. **Chat** — Free-form Bedrock chat with quick prompts

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
- `databricks_client.py` — All Databricks queries (8 functions)
- `celonis_client.py` — Celonis OAuth + API
- `.env` — Secrets (NEVER commit — contains AWS + Databricks + Celonis tokens)
- `logo.svg` — Real Pilot Flying J logo (SVG wrapping base64 PNG)
- `scripts/test_endpoints.py` — Integration test
- `scripts/audit_real_vs_hardcoded.py` — Verify what's real
- `.kiro/steering/onboarding.md` — THIS FILE
- `PROJECT_STATUS.md` — Current build status
