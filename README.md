# RoadIQ — Pilot Flying J Journey Optimizer

AI-powered route planning that helps truck drivers find the best Pilot stop based on fuel level, parking availability, shower wait, loyalty tier, and real-time data.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up .env (copy from .env.example, fill in credentials)
cp .env.example .env

# Run the server
python server.py
# → http://localhost:5002
```

## Architecture

```
Browser (static/index.html — phone-style SPA)
    │
    ├── GET /api/driver    → driver profile + real loyalty data from Databricks
    ├── GET /api/route     → OSRM route geometry + Pilot stop pins
    ├── POST /api/plan     → optimized stops + AI journey plan
    └── POST /api/ai       → chat / journey plan from Amazon Bedrock
    │
server.py (Flask, port 5000)
    ├── Amazon Bedrock (Nova Lite) — AI text generation
    ├── Databricks SQL (innovate catalog) — location, loyalty, pricing, parking
    ├── OSRM — free road routing
    └── Celonis MCP — live Pilot location data (optional)
```

## Data Sources (all from Databricks)

| Table | What it provides |
|-------|-----------------|
| `innovate.location.dim_line_of_business_offering` | Pilot stop locations, amenities, brands |
| `innovate.loyalty.dim_loyalty_household` | Driver loyalty tier, profile |
| `innovate.loyalty.fct_dm_guest_household_summary` | Total gallons, visits |
| `innovate.pos_transactions_inventory.fct_sale` | Transaction history |
| `innovate.loyalty.fct_parking_demand_forecast` | Real parking availability % |
| `innovate.team02.drive_shower_utilization` | Real shower wait times |
| `innovate.price.fct_fuel_supply_price` | Real diesel prices |
| `innovate.loyalty.fct_guest_mobile_offers` | Personalized offers |

## Environment Variables

See `.env.example` for the full template. Key ones:

- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` — Bedrock access
- `BEDROCK_MODEL_ID` — currently `amazon.nova-lite-v1:0`
- `DATABRICKS_HOST` / `DATABRICKS_HTTP_PATH` / `DATABRICKS_TOKEN` — SQL warehouse
- `CELONIS_CLIENT_ID` / `CELONIS_CLIENT_SECRET` — optional Celonis MCP

## For AI Assistants (Claude, Kiro, Cursor)

Read `.kiro/steering/onboarding.md` before making any changes. It has:
- Which file is the active server (server.py, NOT app.py)
- The API contract
- Rules for updating documentation after changes

**After making changes**, update:
1. `.kiro/steering/onboarding.md` — if architecture changed
2. `PROJECT_STATUS.md` — what's working, what's not
3. This README — if the API or setup instructions changed

## Team

Built for Pilot Travel Centers Innovate 2026 hackathon (48-hour build).
