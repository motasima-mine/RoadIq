# RoadIQ — Tech Stack Documentation

**Last updated:** 2026-08-04

## Overview

RoadIQ is a Flask-based web application with a mobile-style frontend, powered by AI (Amazon Bedrock) and enriched with real operational data (Databricks) and optional live location data (Celonis).

---

## Backend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Web framework | Flask | 3.1.3 | REST API + static file serving |
| Language | Python | 3.13 | Runtime |
| Config | python-dotenv | latest | Loads `.env` secrets |
| HTTP client | requests | latest | Calls to OSRM, Celonis, Nominatim |

**Entry point:** `server.py` — run with `python server.py`, serves on port 5000.

---

## AI / LLM

| Component | Technology | Details |
|-----------|-----------|---------|
| Provider | Amazon Bedrock | AWS managed LLM service |
| Model | `amazon.nova-lite-v1:0` | Active model, no inference profile required |
| SDK | boto3 | `bedrock-runtime` client, `converse()` API |
| Auth | AWS temporary credentials | Access key + secret + session token (STS) |
| Prompt design | Plain text templates in `prompts/` | Anti-hallucination rules baked in |

**Why Nova Lite instead of Claude:** Claude 3.5 Sonnet v2 (`claude-3-5-sonnet-20241022-v2:0`) reached end-of-life in this AWS account. Claude Sonnet 4.5 requires an inference profile not configured in the sandbox. Nova Lite is active and works with on-demand throughput — no extra AWS setup needed.

**SSL note:** Corporate network intercepts HTTPS traffic. Bedrock client is configured with `verify=False` and `ssl._create_unverified_context()` to bypass certificate validation issues.

---

## Data Layer

### Primary: Databricks SQL Warehouse

| Detail | Value |
|--------|-------|
| Connector | `databricks-sql-connector` (Python) |
| Host | `pfj-sandbox-dev-east.cloud.databricks.com` |
| Warehouse | SQL Warehouse via HTTP path |
| Auth | Personal access token |
| Catalog | `innovate` |

**Tables queried** (all in `innovate` catalog):

| Schema.Table | Purpose |
|-------------|---------|
| `location.dim_line_of_business_offering` | Pilot/FJ stop locations, brands, amenities |
| `loyalty.dim_loyalty_household` | Driver loyalty tier, profile info |
| `loyalty.fct_dm_guest_household_summary` | Total gallons, visit counts |
| `pos_transactions_inventory.fct_sale` | Transaction history, spend patterns |
| `loyalty.fct_parking_demand_forecast` | Real-time parking availability % |
| `team02.drive_shower_utilization` | Actual shower wait times |
| `price.fct_fuel_supply_price` | Diesel/fuel pricing with fleet discounts |
| `loyalty.fct_guest_mobile_offers` | Personalized driver offers |

**Client module:** `databricks_client.py` — 8 functions, each with graceful fallback (returns `None` on failure, caller decides fallback behavior).

### Secondary: Celonis (optional, live location data)

| Detail | Value |
|--------|-------|
| Protocol | MCP (Model Context Protocol) + REST |
| Auth | OAuth 2.0 client credentials |
| Token lifetime | ~15 minutes, auto-refreshed |
| Client module | `celonis_client.py` |

### Fallback: Local JSON

| File | Purpose |
|------|---------|
| `data/drivers.json` | 15 synthetic driver profiles (demo data) |
| `data/locations.json` | 4 fallback Pilot stop locations |
| `data/fleet_summary.json` | Fleet-level KPI summary |

**Fallback chain:** Databricks → Celonis → Local JSON. The app never crashes if an upstream service is unavailable.

---

## Mapping / Routing

| Component | Technology | Details |
|-----------|-----------|---------|
| Map rendering | Leaflet.js | Via CDN, no API key |
| Tile provider | OpenStreetMap | Free tiles |
| Routing engine | OSRM (Open Source Routing Machine) | `router.project-osrm.org` — free public instance |
| Geocoding | Nominatim | OpenStreetMap's free geocoder, city name → lat/lon |

No paid mapping APIs (Google Maps, Mapbox) are used — everything is free/open-source.

---

## Frontend

| Component | Technology | Details |
|-----------|-----------|---------|
| Structure | Single HTML file | `static/index.html` |
| Styling | Vanilla CSS | iOS-style design system, no framework |
| Fonts | Roboto (Google Fonts) | Loaded via CDN |
| Interactivity | Vanilla JavaScript | No React/Vue — fetch API calls to Flask backend |
| Map library | Leaflet.js 1.9.4 | Loaded via unpkg CDN |
| Layout | Phone-frame SPA | 430px max-width, safe-area insets for notch/home indicator |

**Screens:** Home, Find (map), RoadIQ (AI plan), Chat.

---

## Deployment

| Component | Technology | Details |
|-----------|-----------|---------|
| Containerization | Docker | `python:3.11-slim` base image |
| Orchestration | docker-compose | Single service, env_file for secrets |
| Process | Flask dev server | `debug=True` — **not production-hardened** |

**Production TODO:** Replace Flask dev server with Gunicorn/uWSGI before any real deployment. Current setup is demo/hackathon-grade.

---

## Legacy Components (not in active use)

| File | Status | Notes |
|------|--------|-------|
| `app.py` | Legacy | Original Streamlit prototype, superseded by `server.py` |
| `data_layer.py` | Superseded | Streamlit-era data loader, replaced by `databricks_client.py` |
| `.streamlit/config.toml` | Legacy | Only relevant if running `app.py` |

---

## Security Notes

- All secrets live in `.env` (gitignored, never committed)
- `.env.example` provides the template with placeholder values
- AWS credentials are temporary STS tokens (expire in 1-12 hours) — require periodic refresh
- Celonis OAuth tokens expire every ~15 minutes — auto-refreshed by `celonis_client.py`
- SSL verification is disabled for AWS/Celonis calls due to corporate proxy — **acceptable for sandbox/demo, not for production**

---

## Dependencies (requirements.txt)

```
flask
boto3
databricks-sql-connector
requests
python-dotenv
streamlit          # legacy app.py only
folium             # legacy app.py only
streamlit-folium   # legacy app.py only
```

Run `pip install -r requirements.txt` to install all dependencies.
