"""
Test whether load_data_driver_info accepts an ID-based filter instead of
name. The tool's own description says: "using the drivers first and last
name, OR license number" — implying a license_number param should exist
even though it's not in the documented inputSchema (which only lists
firstname/lastname/page/page_size, but has additionalProperties: true).

We also try common variants of a loyalty/household ID field name since
that's PFJ's actual internal identifier (dim_loyalty_id / loyalty_household_id).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from celonis_client import _call_tool

# Baseline: get a real license number from an unfiltered call first
baseline = _call_tool(
    "load_data_driver_info",
    {"firstname": "James", "lastname": "Okafor", "page": 0, "page_size": 5},
)
sample_license = None
if baseline:
    sample_license = baseline[0].get("O_CUSTOM_DRIVER.LICENSENUMBER")
    print(f"Baseline call returned license numbers, e.g.: {sample_license}")
    print(f"Baseline record: {baseline[0]}\n")

candidates = [
    ("license_number", sample_license),
    ("licensenumber", sample_license),
    ("license", sample_license),
    ("dim_loyalty_id", 7),
    ("dim_loyalty_household_id", 7),
    ("loyalty_household_id", 7),
    ("driver_id", 7),
    ("dim_driver_id", 7),
]

for field_name, value in candidates:
    print("=" * 70)
    print(f"Trying arg: {field_name}={value!r}")
    print("=" * 70)
    args = {"firstname": "James", "lastname": "Okafor", "page": 0, "page_size": 5, field_name: value}
    result = _call_tool("load_data_driver_info", args)
    if result is None:
        print("  -> None / call failed")
        continue
    print(f"  -> {len(result)} records")
    if result:
        pairs = {(r.get("O_CUSTOM_DRIVER.FIRSTNAME"), r.get("O_CUSTOM_DRIVER.LASTNAME"),
                  r.get("O_CUSTOM_DRIVER.LICENSENUMBER")) for r in result}
        for p in list(pairs)[:5]:
            print(f"       {p}")
    print()
