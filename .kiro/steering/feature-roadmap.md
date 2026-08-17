# RoadIQ — Feature Roadmap

## Status Key
- **Built** — working in the current server.py / index.html
- **Building** — planned for the 48-hour window, not yet implemented
- **Out of Scope** — mentioned in pitch narrative only, not being built

---

## Built (20 features — as of 2026-08-05)

### 1. My Trip View
Full trip overview on app open — fuel level, vehicle health, loyalty tier, current route. Color-coded KPI cards signal urgency at a glance.

### 2. Stops Along Your Route
All Pilot stops on the driver's route displayed as cards with parking %, shower wait, food options, fleet agreement status, diesel deals. RoadIQ Pick highlighted with star badge.

### 3. Journey Optimizer
AI-written personalized stop plan via Amazon Bedrock (Claude). Covers fuel timing, parking, shower, food, loyalty perks. Uses `prompts/journey_optimizer.txt`.

### 4. Ask RoadIQ Chat
Conversational AI co-pilot. Driver types or taps quick prompts, gets specific Pilot stop recommendations with reasoning. Verified prompts: food nearby, book parking (PFJ-XXXXX code), stop frequency (55 mph calc), points earnings, off-topic guardrail redirect.

### 5. Proactive Push Banner
On app load, RoadIQ displays an alert before the driver touches anything — fuel miles remaining, best stop name, key stats. No button click needed.

### 6. Vehicle Health Alert
If vehicle health is medium/poor, warning surfaces in Journey Optimizer tab with prompt to book inspection at recommended stop.

### 7. Journey Planner Map (SVG)
Driver enters From/To. SVG route renders instantly with stop pins. Dark background, Pilot red route line. No tiles — renders on any network. Verified routes: Knoxville→Dallas, Nashville→Miami, Nashville→Atlanta. 27 stops in locations.json covering I-40W, I-75, I-75S, I-65 corridors.

### 8. Loyalty Push-for-Elite
Elite threshold at 1,200 gal/month. Gold progress bar, monthly estimate from lifetime Databricks gallons / months. Badges and subtitle update dynamically.

### 9. Weather Ribbon
5-point Open-Meteo weather across route — severity-coded chips, banner on caution/severe. No API key.

### 10. 3-Way Stop Filter + Competitor View
Optimized / All Stops / Competitors toggle. Competitor cards show what Pilot has that they don't; green "Pilot wins" sub-card.

### 11. Return Load Opportunities
After planning a trip, shows 3 ranked return loads from the drop-off city. Net earnings = gross_rate − (gallons × real Pilot fleet price). Route-aware via `_last_plan`.

### 12. Proactive Re-Route Alert
15s after plan resolves, randomizes from 3 scenarios (parking spike / price jump / shower wait). Show Alternatives or Keep My Plan.

### 13. Parking/Shower Reservation
PFJ-XXXXX reservation code in stop advice modal. Triggers Celonis preference write-back silently.

### 14. Repeat Route Memory
localStorage stores last 10 trips. Banner + one-tap auto-plan after ≥2 runs on same route.

### 15. Celonis Preference Write-Back (5 fields)
Chat → extract food/shower/preferred_stop/avoided_stop/typical_gallons → cache + Celonis write → injected into next /api/plan Bedrock prompt.

### 16. Fleet Insights Bar
3 cards: Missed Pilot Stops, Est. Missed Savings ($), On Pilot Streak. Computed from `_driver_intel()` across all 15 drivers.

### 17. Driver Intel Badges
Each driver row: HOS badge (green/amber/red), last stop badge (Pilot ✅ / competitor ❌ + name), Pilot streak badge.

### 18. Smart Assign
⚡ Smart Assign button per unassigned load. `/api/fleet/suggest` ranks top-5 drivers by HOS/fuel/Pilot alignment/tier. Modal shows score, reason, and confirms assignment.

### 19. Driver Push Notification
Slide-in banner after assignment: "✅ Load Assigned" + "View Optimized Route →" CTA. Auto-builds trip. Auto-dismisses after 8s.

### 20. RoadIQ Tab Dynamic Rewrite
`updateRoadIQTab(stop, from, to)` — no hardcoded text. Pre-trip: "Plan a trip" placeholder. Post-trip: route title, fuel/tier/miles badges, first stop card. "View My Plan →" scrolls to plan results.

---

## Out of Scope / Future Phase

### Multi-Stop Trip Planning
Chained OSRM waypoints, HOS-aware multi-leg route. Future phase.

### Arrival Offer Trigger
Proximity-based personalized offers. Needs geofence trigger. Future phase.

### Weigh Station Locations
Static FHWA JSON overlaid as pins on SVG map. Discussed, not built.

### Fuel Price Trend Sparkline
Historical `fct_fuel_supply_price` delta or ML prediction. Future phase.

### Driver Wellness / HOS
Fatigue detection. Requires ELD integration. Future phase.

### Predictive Maintenance
Real-time fault codes from telematics. Needs OBD API. Future phase.
