"""
Evidence-gathering script: prove that load_data_driver_info does not filter
by the firstname/lastname arguments passed to it.

Calls the tool with three totally different names and compares results.
If the tool filtered correctly, each call should return different (or empty)
results specific to that name. If it's broken, all three calls return the
same (or randomly different) unfiltered dataset.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from celonis_client import celonis_load_driver

test_names = [
    ("James", "Okafor"),        # a real driver name in our system
    ("Zzyzx", "Nonexistent99"),  # a name that should NOT exist in any dataset
    ("Zzyzx", "Nonexistent99"),  # same nonexistent name called AGAIN
]

results = []
for first, last in test_names:
    print(f"\n{'='*70}")
    print(f"Calling load_data_driver_info(firstname={first!r}, lastname={last!r})")
    print(f"{'='*70}")
    records = celonis_load_driver(first, last)
    if records is None:
        print("  -> None (no records / call failed)")
        results.append(None)
        continue
    print(f"  -> {len(records)} records returned")
    # Show first 3 distinct firstname/lastname pairs actually in the response
    seen = set()
    for r in records:
        pair = (r.get("O_CUSTOM_DRIVER.FIRSTNAME"), r.get("O_CUSTOM_DRIVER.LASTNAME"))
        seen.add(pair)
    print(f"  -> distinct (firstname, lastname) pairs in response: {len(seen)}")
    for pair in list(seen)[:5]:
        print(f"       {pair}")
    results.append(records)

print(f"\n{'='*70}")
print("CONCLUSION")
print(f"{'='*70}")
if results[1] is not None and len(results[1]) > 0:
    print("BUG CONFIRMED: A query for a name that cannot possibly exist in any")
    print("real dataset ('Zzyzx Nonexistent99') still returned records.")
    print("This proves the 'firstname'/'lastname' arguments are not being")
    print("applied as a filter server-side — the tool returns an unfiltered")
    print("(or randomly sampled) set of driver records regardless of input.")
else:
    print("Could not reproduce — nonexistent name returned no records.")
    print("(If this happens, the filtering may actually be working now.)")

if results[1] is not None and results[2] is not None:
    same_data = results[1] == results[2]
    print(f"\nCalling the SAME nonexistent name twice returned "
          f"{'IDENTICAL' if same_data else 'DIFFERENT'} data both times.")
    if not same_data:
        print("This further suggests the tool is returning a random/rotating")
        print("sample of the underlying table rather than a filtered query result.")
