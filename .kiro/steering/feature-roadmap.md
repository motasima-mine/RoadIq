# RoadIQ — Feature Roadmap

## Status Key
- **Built** — working in the current app.py
- **Building** — planned for the 48-hour window, not yet implemented
- **Out of Scope** — mentioned in pitch narrative only, not being built

---

## Built (6 features)

### 1. My Trip View
Full trip overview on app open — fuel level, vehicle health, loyalty tier, current route. Color-coded KPI cards signal urgency at a glance.

### 2. Stops Along Your Route
All Pilot stops on the driver's route displayed as cards with parking %, shower wait, food options, fleet agreement status, diesel deals. RoadIQ Pick highlighted with star badge.

### 3. Journey Optimizer
AI-written personalized stop plan via Amazon Bedrock (Claude). Covers fuel timing, parking, shower, food, loyalty perks. Uses `prompts/journey_optimizer.txt`.

### 4. Ask RoadIQ Chat
Conversational AI co-pilot. Driver types or taps quick prompts, gets specific Pilot stop recommendations with reasoning. Uses `prompts/driver_chat.txt`.

### 5. Proactive Push Banner
On app load, RoadIQ displays an alert before the driver touches anything — fuel miles remaining, best stop name, key stats. No button click needed.

### 6. Vehicle Health Alert
If vehicle health is medium/poor, warning surfaces in Journey Optimizer tab with prompt to book inspection at recommended stop.

---

## Building Next (6 features)

### 7. Journey Planner Map
- Driver enters From/To
- Real road route renders on interactive Folium map
- Pilot stops drop as pins along route
- RoadIQ Pick highlighted
- **Tech:** Folium + OSRM routing (free, no API key)

### 8. Loyalty Personalization
- Tier-based offers pushed at recommended stop
- Platinum: free coffee + priority shower
- Gold: bonus points on diesel
- Standard: points multiplier
- **Connects:** driver spend → loyalty revenue narrative

### 9. Multi-Stop Trip Planning
- Driver sets full day's run (multiple legs)
- RoadIQ plans fuel stops across entire route
- Accounts for HOS windows, fuel thresholds, preferred timing
- **Tech:** Chained OSRM waypoints + AI planning prompt

### 10. Arrival Offer Trigger
- When driver approaches recommended stop, personalized offer auto-generates
- Free item, bonus points, or priority access
- Closes the loyalty loop inside the app
- **Trigger:** proximity to stop coordinates

### 11. My Points & Rewards
- Dedicated loyalty tab
- Current points balance, points earned this trip, active offers
- Progress bar to next reward tier

### 12. Mobile Fueling Alert
- If corridor has mobile fueling window available, banner surfaces
- Shows timing, location, estimated cost savings
- Connects to existing Pilot mobile fueling program

---

## Out of Scope (pitch narrative only)

### Driver Wellness / HOS
Fatigue detection, rest window suggestions. Requires ELD integration — future phase.

### Predictive Maintenance
Real-time fault code monitoring from telematics. Needs OBD/telematics API — future phase.

### Weather & Road Conditions
Real-time weather alerts, road closures, re-routing. Needs weather API + route deviation logic — future phase.

---

## Implementation Priority for "Building" Features
1. Journey Planner Map (highest demo impact — visual)
2. Loyalty Personalization (connects to revenue story)
3. Multi-Stop Trip Planning (differentiator)
4. Arrival Offer Trigger (closes loop)
5. My Points & Rewards (UI tab)
6. Mobile Fueling Alert (banner addition)
