# RoadIQ — Project Context

## What is RoadIQ
RoadIQ is an AI-powered journey optimization feature for the Pilot Flying J driver app. It helps truck drivers make smarter stop decisions by combining real-time trip data (fuel level, vehicle health, parking availability) with LLM-powered recommendations personalized to each driver's route, preferences, and loyalty tier.

## Business Goal
Increase Pilot Flying J stop capture rate by routing more drivers to Pilot locations instead of competitors. The before/after model: fleet goes from 9 Pilot stops + 6 competitor stops → 13 Pilot stops + 2 competitor stops on the same routes.

## Target Users
- **Primary:** Over-the-road truck drivers using the Pilot Flying J mobile app
- **Secondary:** Fleet managers (future phase — fleet dashboard view exists but is secondary)

## Innovate 2026 Submission
This is a 48-hour build for the Pilot Travel Centers Innovate 2026 hackathon. Scope is intentionally tight — demo quality, not production hardened.

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Flask (server.py) — REST API |
| Frontend | Static HTML SPA (static/index.html) — phone-frame UI |
| LLM | Amazon Bedrock — Claude 3.5 Sonnet v2 |
| LLM SDK | boto3 bedrock-runtime Converse API |
| Data | Databricks (innovate.location.dim_line_of_business_offering) + local JSON fallback |
| Locations | Celonis OAuth API (live Pilot stops) |
| Maps | Leaflet.js (frontend) + OSRM (free routing) |
| Deployment | Docker (python:3.11-slim), docker-compose |
| Config | python-dotenv, .env for secrets |

## Data Sources — What We Use
- `data/drivers.json` — 15 synthetic driver profiles (route, fuel, loyalty, prefs)
- `data/locations.json` — 4 Pilot stop locations with real-time-like forecasts
- `data/fleet_summary.json` — fleet-level KPIs for the dashboard view

### Databricks SQL Warehouse (primary data source)
- **Host:** pfj-sandbox-dev-east.cloud.databricks.com
- **HTTP Path:** /sql/1.0/warehouses/2ff99aaeaf52a661
- **Auth:** Personal access token via DATABRICKS_TOKEN env var
- **Tables:** roadiq.drivers, roadiq.locations, roadiq.fleet_summary
- **Connector:** databricks-sql-connector (Python)

### Local JSON (fallback)
If Databricks is unreachable (offline demo, no token), the app falls back to local JSON files in `data/`. This is automatic via `data_layer.py`.

## AWS Configuration
- Region: us-east-1 (Amazon sandbox)
- Service: Amazon Bedrock
- Model: anthropic.claude-3-5-sonnet-20241022-v2:0
- Auth: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY via .env

## App Structure
```
roadiq/
├── app.py                  # Main Streamlit app (single-file)
├── data/
│   ├── drivers.json        # Driver profiles
│   ├── locations.json      # Pilot stop data
│   └── fleet_summary.json  # Fleet KPIs
├── prompts/
│   ├── journey_optimizer.txt   # Journey plan prompt
│   ├── driver_chat.txt         # Ask RoadIQ chat prompt
│   ├── driver_recommendation.txt # Stop recommendation engine prompt
│   ├── revenue_insight.txt     # (fleet view — future)
│   └── store_alert.txt         # (store manager view — future)
├── .streamlit/
│   └── config.toml         # Streamlit production config
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .env                    # (gitignored — real secrets)
└── .kiro/steering/         # Project instructions for AI assistant
```

## Brand Design
- Pilot Flying J brand colors: Red #DC1730, White #FFFFFF, Black #000000
- Typography: Inter (Google Fonts)
- Dark-mode cards on white page background
- Mobile-first layout within Streamlit constraints

## Demo Driver
The default demo runs as **James Okafor** (driver ID 7):
- Route: Nashville, TN → Atlanta, GA
- Status: fuel_risk (140 miles remaining)
- Tier: Platinum
- Needs: oversized parking, shower, prefers Subway
- Recommended stop: Pilot Knoxville #198

## Key Constraints
1. **No external APIs beyond Bedrock** — no paid map APIs, no weather APIs, no traffic APIs
2. **No Databricks calls** — all data is local JSON for this demo
3. **All LLM responses must be grounded** — prompts explicitly forbid inventing locations, prices, or stats not provided in context
4. **48-hour build window** — ship features, not infrastructure
5. **Single Streamlit app** — no microservices, no backend API layer
