"""Test get_pfj360_food_offerings() against real Pilot/FJ stop LOB IDs."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from databricks_client import get_stops_in_corridor, get_pfj360_food_offerings

# Get real Pilot stops (global search since sandbox corridor lat/lons are synthetic)
stops = get_stops_in_corridor(-90, 90, -180, 180, driver_id=7)
print(f"Found {len(stops) if stops else 0} Pilot/FJ stops")

if stops:
    lob_ids = [s["lob_id"] for s in stops]
    food = get_pfj360_food_offerings(lob_ids)
    print(f"\n{len(food)} of {len(lob_ids)} stops have food offering data:\n")
    for s in stops:
        offerings = food.get(s["lob_id"])
        if offerings:
            print(f"  {s['name']} ({s['city']}, {s['state']}) [lob_id={s['lob_id']}]")
            print(f"    Food: {', '.join(offerings)}")
