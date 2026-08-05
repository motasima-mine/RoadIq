# RoadIQ — Project Status

**Last updated:** 2026-08-05 ET

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

## Component Health

| Component | Status | Details |
|-----------|--------|---------|
| Flask server | ✅ | `server.py` on **port 5001** |
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
├── celonis_client.py      ← Celonis OAuth client (optional)
├── logo.svg               ← Real Pilot Flying J logo (served at /logo.svg)
├── data/                  ← Local JSON fallback data
├── prompts/               ← LLM prompt templates
├── scripts/               ← Test & utility scripts
├── .env                   ← Secrets (NEVER commit)
├── .kiro/steering/        ← AI assistant instructions (onboarding.md)
├── app.py                 ← LEGACY (Streamlit, not used)
└── README.md              ← Setup instructions
```

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

## Databricks Tables

1. `innovate.location.dim_line_of_business_offering` — ~12 OPEN Pilot/Flying J locations
2. `innovate.loyalty.dim_loyalty_household` — loyalty profiles
3. `innovate.loyalty.fct_dm_guest_household_summary` — gallons/visits
4. `innovate.pos_transactions_inventory.fct_sale` — transactions
5. `innovate.loyalty.fct_parking_demand_forecast` — parking %
6. `innovate.team02.drive_shower_utilization` — shower waits
7. `innovate.price.fct_fuel_supply_price` — diesel prices
8. `innovate.loyalty.fct_guest_mobile_offers` — personalized offers

## Brand Colors (do not change)

| Color | Hex | Used for |
|-------|-----|----------|
| Pilot Red | `#DC1730` | CTA buttons, active tab, alert banners, route line, stop markers |
| White | `#FFFFFF` | Backgrounds, card surfaces |
| Black | `#1c1c1e` | Body text, dark UI surfaces |
| Logo | `logo.svg` | Header only — do not replace with text |
