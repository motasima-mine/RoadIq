"""
Test celonis_update_driver_preferences() against the real Celonis MCP
action-flow tool.

This IS a write operation — it will actually call
trigger_action_flow_Update_Driver_Preferences with our demo driver's ID.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from celonis_client import celonis_update_driver_preferences

# Demo driver James Okafor — using driver id 7 (our app's DEMO_DRIVER id) as
# the Driver_ID for now since we haven't confirmed what ID space this tool
# expects. This is a discovery test.
result = celonis_update_driver_preferences(
    driver_id="7",
    food_preferences="Subway, Wendy's",
    shower_preferences="Quick shower, prefers clean stalls",
)

if result:
    print("SUCCESS:")
    print(result)
else:
    print("RESULT: None (call failed or tool returned an error — check stderr above)")
