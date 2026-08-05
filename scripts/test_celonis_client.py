"""Test the rewritten celonis_client.py end-to-end."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from celonis_client import celonis_load_locations, celonis_load_driver

print("Testing celonis_load_locations() for Nashville->Atlanta corridor...")
route_points = [(36.1627, -86.7816), (33.7490, -84.3880)]
locations = celonis_load_locations(route_points)
if locations:
    print(f"SUCCESS: {len(locations)} OPEN locations returned")
    for loc in locations[:5]:
        print(f"  {loc}")
else:
    print("RESULT: None (no OPEN locations found or call failed)")

print()
print("Testing celonis_load_driver('James', 'Okafor')...")
driver = celonis_load_driver("James", "Okafor")
if driver:
    print(f"SUCCESS: {len(driver)} records returned")
    print(f"  First record: {driver[0]}")
else:
    print("RESULT: None")
