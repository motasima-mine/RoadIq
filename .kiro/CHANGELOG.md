# RoadIQ Auto-Changelog
_Auto-updated on every .py/.html save. Newest first._

- 2026-08-05 — saved celonis_client.py, server.py, scripts/test_update_preferences.py, scripts/test_preference_loop.py — integrated Celonis trigger_action_flow_Update_Driver_Preferences write-back into the Chat tab
- 2026-08-05 — saved databricks_client.py, server.py, scripts/test_pfj360_food.py, scripts/test_chat_food_grounding.py — root-caused chat tab's "can't answer food questions" as a missing-grounding bug (not a Celonis data gap); added `get_pfj360_food_offerings()` (dev.location.pfj360_offering, join key DIM_LINE_OF_BUSINESS_ID==LocationID) and `_build_chat_stops_context()` to ground /api/ai chat mode in real stop/food/parking/shower data
- 2026-08-05 — saved scripts/test_celonis_dim_loyalty_id_filter.py — re-tested load_data_driver_info now that dim_loyalty_id is a required schema field; confirmed it still doesn't filter server-side (identical output regardless of name/ID combo)
- 2026-08-14 — saved scripts/_tmp_check_all.py
- 2026-08-14 — saved scripts/_tmp_check_bedrock.py
- 2026-08-14 — saved scripts/_tmp_check_stops_quality.py
- 2026-08-14 — saved scripts/_tmp_check_nash_dallas.py
- 2026-08-14 — saved scripts/_tmp_check_plan_dallas.py
- 2026-08-14 — saved server.py — fixed /api/plan on main: (1) scaled MAX_PERP_DEG with route length instead of a fixed 0.5deg/35mi corridor, which was rejecting every stop on long diagonal routes like Nashville->Dallas; (2) validate Databricks stop coordinates are real US lat/lon before treating corridor_stops as non-empty, since a single scrambled row (e.g. "CONOCO FORT MYERS" landing in Montana) was silently blocking the data/locations.json fallback while still failing the corridor filter, leaving zero stops. Verified both Nashville->Dallas (Memphis/Little Rock/Texarkana/Dallas) and Nashville->Atlanta (Atlanta North) now return correct stops.
- 2026-08-14 — saved scripts/_tmp_check_knox_miami.py
