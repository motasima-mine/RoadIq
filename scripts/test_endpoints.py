"""Test the server endpoints."""
import requests
import json
import urllib3
urllib3.disable_warnings()

BASE = "http://localhost:5000"

print("=== GET /api/driver ===")
r = requests.get(f"{BASE}/api/driver", verify=False)
d = r.json()
print(f"  Name: {d.get('name')}")
print(f"  Loyalty tier: {d.get('loyalty_tier')}")
print(f"  Total gallons: {d.get('total_gallons', 'N/A')}")
print(f"  Total visits: {d.get('total_visits', 'N/A')}")
print(f"  Last visit: {d.get('last_visit_date', 'N/A')}")
print(f"  Avg spend: {d.get('avg_spend', 'N/A')}")
print(f"  Most visited: {d.get('most_visited_location', 'N/A')}")
print(f"  Data source: {d.get('data_source', 'local')}")

print("\n=== POST /api/plan ===")
r = requests.post(f"{BASE}/api/plan", json={
    "from": "Nashville, TN",
    "to": "Atlanta, GA",
    "prefs": ["fuel", "shower"]
}, verify=False)
p = r.json()
print(f"  Route: {p.get('from')} → {p.get('to')}")
print(f"  Miles: {p.get('total_miles')}")
print(f"  Drive: {p.get('drive_hours')}")
print(f"  Stops found: {len(p.get('stops', []))}")
for i, s in enumerate(p.get("stops", [])):
    print(f"    Stop {i+1}: {s.get('name')} ({s.get('city')})")
    print(f"      Brand: {s.get('brand')}, Interstate: {s.get('interstate')}")
    print(f"      Lounge: {s.get('has_lounge')}, IdleAir: {s.get('has_idle_air')}")
    print(f"      Visited before: {s.get('visited_before')}")
    print(f"      PFJ: {s.get('is_pfj')}, Network: {s.get('in_network')}")
    print(f"      Parking: {s.get('parking_pct')}% ({s.get('total_spaces')} spaces)")
    print(f"      Shower wait: {s.get('shower_wait')} min")
    print(f"      Diesel: ${s.get('diesel_price')}/gal, Fleet discount: ${s.get('fleet_discount')}/gal")
print(f"  Savings: {p.get('savings')}")
print(f"  Fuel prices: {p.get('fuel_prices')}")
print(f"  Offers: {p.get('offers')}")
print(f"  AI Plan: {p.get('ai_plan', '')[:100]}...")
