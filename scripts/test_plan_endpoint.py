"""Test /api/plan end-to-end with the new Celonis HOS + corroboration integration."""
import requests
import urllib3
import json
urllib3.disable_warnings()

r = requests.post(
    "http://localhost:5001/api/plan",
    json={"from": "Nashville, TN", "to": "Atlanta, GA", "prefs": ["fuel", "shower"]},
    verify=False,
    timeout=40,
)
print("Status:", r.status_code)
d = r.json()
print("\nHOS block:")
print(json.dumps(d.get("hos", {}), indent=2))
print("\nAI Plan:")
print(d.get("ai_plan", ""))
print("\nStops chosen:", len(d.get("stops", [])))
