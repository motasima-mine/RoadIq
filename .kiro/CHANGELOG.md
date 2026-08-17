# RoadIQ Auto-Changelog
_Auto-updated on every .py/.html save. Newest first._

- 2026-08-17 09:42 — saved server.py — fixed chat prompt saying driver is "Gold MyRewards member" earning 4x as Elite (contradicted points_multiplier logic and fallback text elsewhere in the file, both of which use Elite=2x); now consistently "Elite MyRewards member" earning 2x everywhere
- 2026-08-17 09:36 — saved scripts/_tmp_check_experimental.py

- 2026-08-05 — Fleet Intelligence: added `/api/fleet/suggest` POST endpoint; `_driver_intel()` deterministic HOS/last-stop/streak/missed-savings; fleet insights bar (missed Pilot stops, est. savings, streak counts); Smart Assign modal with AI-ranked top-5 drivers + reasoning; driver push notification banner with "View Optimized Route →" CTA; driver rows show HOS badge (green/amber/red), last stop badge (Pilot ✅ / competitor ❌), pilot streak badge

- 2026-08-05 — RoadIQ tab dynamic rewrite: replaced hardcoded "James Okafor · Nashville → Atlanta" and "Pilot Knoxville #198" static HTML with id-driven elements; added `updateRoadIQTab(stop, from, to)` called from `updateHomeAlert()` and localStorage restore; "View My Plan →" CTA now goes to `switchTab('plan')` + scrolls to plan-results

- 2026-08-05 — Plan Trip fuel slider now seeded from real driver `fuel_pct` via `fetch('/api/driver')` callback; was always defaulting to 50%

- 2026-08-05 — Chat route-context fix: `_build_chat_stops_context()` fully rewritten to use `_last_plan` coords for dynamic corridor bbox; US lat/lon validation on Databricks stops; route-keyed cache busts when route changes; fixes wrong-city responses after Nashville→Dallas plan

- 2026-08-05 — saved celonis_client.py, server.py, scripts/test_update_preferences.py, scripts/test_preference_loop.py — integrated Celonis trigger_action_flow_Update_Driver_Preferences write-back into the Chat tab
- 2026-08-05 — saved databricks_client.py, server.py, scripts/test_pfj360_food.py, scripts/test_chat_food_grounding.py — root-caused chat tab's "can't answer food questions" as a missing-grounding bug (not a Celonis data gap); added `get_pfj360_food_offerings()` (dev.location.pfj360_offering, join key DIM_LINE_OF_BUSINESS_ID==LocationID) and `_build_chat_stops_context()` to ground /api/ai chat mode in real stop/food/parking/shower data
- 2026-08-05 — saved scripts/test_celonis_dim_loyalty_id_filter.py — re-tested load_data_driver_info now that dim_loyalty_id is a required schema field; confirmed it still doesn't filter server-side (identical output regardless of name/ID combo)
