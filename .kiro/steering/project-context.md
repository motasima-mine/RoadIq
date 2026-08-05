# RoadIQ — Project Context

## What is RoadIQ
RoadIQ is an AI-powered journey optimization feature for the Pilot Flying J driver app. It helps truck drivers make smarter stop decisions by combining real-time trip data (fuel level, vehicle health, parking availability) with LLM-powered recommendations personalized to each driver's route, preferences, and loyalty tier.

## Business Goal
Increase Pilot Flying J stop capture rate by routing more drivers to Pilot locations instead of competitors. The before/after model: fleet goes from 9 Pilot stops + 6 competitor stops → 13 Pilot stops + 2 competitor stops on the same routes.

## Target Users
- **Primary:** Over-the-road truck drivers using the Pilot Flying J mobile app
- **Secondary:** Fleet managers (Fleet tab — fully built)

## Innovate 2026 Submission
This is a 48-hour build for the Pilot Travel Centers Innovate 2026 hackathon. Scope is intentionally tight — demo quality, not production hardened.

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Flask `server.py` — REST API on **port 5002** |
| Frontend | Static HTML SPA `static/index.html` — phone-frame UI, 5 tabs |
| LLM | Amazon Bedrock — `amazon.nova-lite-v1:0` |
| LLM SDK | boto3 bedrock-runtime Converse API |
| Data | Databricks (`innovate` catalog, 8 tables) + local JSON fallback |
| Live stops | Celonis MCP JSON-RPC (`load_data_location_info`) |
| Maps | Leaflet.js + OSM tiles proxied via Flask `/tiles/{z}/{x}/{y}.png` |
| Routing | OSRM (`router.project-osrm.org`, no API key) |
| Deployment | Docker (python:3.11-slim), docker-compose |
| Config | python-dotenv, `.env` for secrets |

> **Legacy:** `app.py` (Streamlit) exists as backup only. Active server is `server.py`.

## Data Sources
- `data/drivers.json` — 15 synthetic driver profiles
- `data/locations.json` — 15 Pilot stop locations (local fallback when Databricks returns 0 corridor hits)
- `data/fleet_summary.json` — fleet-level KPIs

### Databricks SQL Warehouse (primary)
- **Host:** pfj-sandbox-dev-east.cloud.databricks.com
- **HTTP Path:** /sql/1.0/warehouses/2ff99aaeaf52a661
- **Auth:** Personal access token via `DATABRICKS_TOKEN` env var
- **Catalog:** `innovate`
- **Pilot-only filter:** `AND PRIMARY_STOREFRONT_BRAND IN ('PILOT', 'FLYING J', 'PILOT FLYING J')`

### Local JSON fallback
If Databricks corridor query returns 0 stops (sandbox lat/lons are synthetic), server falls back to `data/locations.json` (15 stops across Nashville→Dallas, I-40, I-75 corridors).

## AWS Configuration
- Region: us-east-1
- Service: Amazon Bedrock
- Model: `amazon.nova-lite-v1:0`
- Auth: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` via `.env`
- AWS session tokens expire (1–12h) — refresh `.env` when `ExpiredTokenException` appears

## Corporate Network Constraint
All external HTTP calls use `verify=False` + `ssl._create_unverified_context()`. This applies to Databricks, OSRM, Celonis, Open-Meteo, Overpass, and the OSM tile proxy.

## App Structure
```
roadiq/
├── server.py                  # ACTIVE Flask server (port 5002)
├── static/
│   └── index.html             # Frontend SPA (5-tab phone UI, all JS inline)
│   └── images/                # Product images (gatorade.png, lunch offer.png)
├── databricks_client.py       # 8 Databricks query functions
├── celonis_client.py          # Celonis MCP JSON-RPC client
├── data/                      # Local JSON fallback
├── prompts/                   # LLM prompt templates
├── scripts/                   # Test & utility scripts
├── logo.svg                   # Real Pilot Flying J logo
├── .env                       # Secrets (NEVER commit)
├── .kiro/steering/            # AI assistant instructions
├── app.py                     # LEGACY Streamlit app (not used)
└── README.md
```

## Brand Design
- Red `#DC1730`, White `#FFFFFF`, Black/near-black `#1c1c1e`
- Typography: Inter (Google Fonts)
- Mobile-first, 390px phone-frame layout

## Demo Driver
Default demo: **James Okafor** (driver ID 7)
- Route: Nashville, TN → Atlanta, GA
- Status: fuel_risk (140 miles remaining)
- Tier: MyRewards / Elite
- Needs: oversized parking, shower, prefers Subway

## Key Constraints
1. **Pilot-only** — SQL filter + AI prompt both enforce Pilot/Flying J stops only
2. **No invented data** — LLM only reasons over data passed in the prompt
3. **SSL verify=False everywhere** — corporate proxy blocks standard TLS verification
4. **48-hour build window** — ship features, not infrastructure
5. **Single SPA** — all frontend JS inline in `static/index.html`
