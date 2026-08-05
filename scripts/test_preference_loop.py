"""
End-to-end test of the chat -> extract -> Celonis write -> /api/plan loop.

1. Send a chat message with an obvious food preference.
2. Confirm the /api/ai response includes a preference_update.
3. Call /api/plan and confirm the AI-generated itinerary mentions it.
"""
import requests
import urllib3
import json
urllib3.disable_warnings()

BASE = "http://localhost:5001"

print("=" * 70)
print("STEP 1: Chat message with a food preference")
print("=" * 70)
r = requests.post(f"{BASE}/api/ai", json={
    "mode": "chat",
    "message": "By the way, I really only like stopping at places with a Wendy's, not Subway anymore.",
}, verify=False, timeout=30)
d = r.json()
print(f"Status: {r.status_code}")
print(f"Text: {d.get('text')}")
print(f"Preference update: {json.dumps(d.get('preference_update'), indent=2)}")

print("\n" + "=" * 70)
print("STEP 2: /api/plan — check if the itinerary reflects the preference")
print("=" * 70)
r2 = requests.post(f"{BASE}/api/plan", json={
    "from": "Nashville, TN", "to": "Atlanta, GA", "prefs": ["fuel"],
}, verify=False, timeout=40)
d2 = r2.json()
print(f"Status: {r2.status_code}")
print(f"AI Plan: {d2.get('ai_plan')}")
