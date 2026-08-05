"""Audit: what's real data vs hardcoded/fallback."""
import requests
import json
import os
import sys
import urllib3
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

print("=" * 60)
print("AUDIT: Real vs Hardcoded")
print("=" * 60)

# 1. Bedrock
print("\n1. BEDROCK (AI generation)")
try:
    import boto3
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    )
    resp = client.converse(
        modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
        messages=[{"role": "user", "content": [{"text": "Say OK in one word"}]}],
        inferenceConfig={"maxTokens": 10, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    print(f"   ✅ WORKING — response: '{text}'")
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

# 2. Databricks
print("\n2. DATABRICKS (location data)")
try:
    from databricks_client import get_stops_in_corridor
    # Nashville→Atlanta corridor
    stops = get_stops_in_corridor(33.0, 37.0, -87.0, -83.0)
    if stops:
        print(f"   ✅ WORKING — {len(stops)} stops returned from Databricks")
        for s in stops[:3]:
            print(f"      {s['name']} ({s['city']}, {s['state']}) — PFJ:{s['is_pfj']}")
    else:
        print(f"   ⚠️  NO DATA — query returned 0 stops in Nashville→Atlanta corridor")
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

# 3. OSRM (map routing)
print("\n3. OSRM (map routing)")
try:
    url = "http://router.project-osrm.org/route/v1/driving/-86.7816,36.1627;-84.3880,33.7490?overview=full&geometries=geojson"
    r = requests.get(url, timeout=10)
    data = r.json()
    if data.get("routes"):
        coords = len(data["routes"][0]["geometry"]["coordinates"])
        dist = round(data["routes"][0]["distance"] / 1609.34)
        print(f"   ✅ WORKING — route has {coords} points, {dist} miles")
    else:
        print(f"   ❌ NO ROUTE returned")
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

# 4. Parking forecast
print("\n4. PARKING FORECAST")
try:
    from databricks_client import get_parking_availability
    # Use LOB IDs that exist in the data
    from databricks import sql
    conn = sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT DIM_LINE_OF_BUSINESS_ID FROM innovate.loyalty.fct_parking_demand_forecast LIMIT 5")
    ids = [r[0] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    if ids:
        parking = get_parking_availability(ids)
        print(f"   ✅ WORKING — {len(parking)} locations with parking data")
        for lid, info in list(parking.items())[:3]:
            print(f"      LOB {lid}: {info['parking_pct_available']}% available ({info['total_spaces']} spaces)")
    else:
        print(f"   ⚠️  NO DATA in fct_parking_demand_forecast")
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

# 5. Shower wait
print("\n5. SHOWER WAIT TIMES")
try:
    from databricks_client import get_shower_wait
    from databricks import sql
    conn = sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT location_id FROM innovate.team02.drive_shower_utilization LIMIT 5")
    ids = [r[0] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    if ids:
        showers = get_shower_wait(ids)
        print(f"   ✅ WORKING — {len(showers)} locations with shower data")
        for lid, info in list(showers.items())[:3]:
            print(f"      Location {lid}: avg {info['avg_wait_minutes']} min wait")
    else:
        print(f"   ⚠️  NO DATA")
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

# 6. Fuel prices
print("\n6. FUEL PRICES")
try:
    from databricks_client import get_fuel_prices
    prices = get_fuel_prices()
    if prices and prices.get("avg_net_price"):
        print(f"   ✅ WORKING — Avg net: ${prices['avg_net_price']}/gal, Gross: ${prices['avg_gross_price']}/gal")
    else:
        print(f"   ⚠️  NO DATA")
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

# 7. Driver offers
print("\n7. DRIVER OFFERS")
try:
    from databricks_client import get_driver_offers
    offers = get_driver_offers(7)
    if offers:
        print(f"   ✅ WORKING — {len(offers)} offers for driver")
        for o in offers[:2]:
            print(f"      {o['offer_type']}: ${o['offer_value']} (expires {o['expires']})")
    else:
        print(f"   ⚠️  NO OFFERS for household_id 7 (try other IDs)")
        # Try a few other IDs
        for hid in [1, 5, 12, 20]:
            o2 = get_driver_offers(hid)
            if o2:
                print(f"   ✅ Found offers for household_id {hid}: {len(o2)} offers")
                break
except Exception as e:
    print(f"   ❌ BROKEN — {e}")

print("\n" + "=" * 60)
print("SUMMARY: What's still hardcoded in server.py")
print("=" * 60)
print("  - DEMO_DRIVER loaded from data/drivers.json (local file)")
print("  - DEMO_STOP loaded from data/locations.json (local file)")
print("  - Fallback responses if Bedrock is down")
print("  - Knoxville #198 as 'recommended' stop (static)")
