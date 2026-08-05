"""
Re-test of Celonis load_data_driver_info now that dim_loyalty_id is a
documented, required schema field (added 2026-08-05).

QUESTION: does dim_loyalty_id actually filter server-side now, or is the
underlying bug (firstname/lastname ignored) still present with a new
parameter that's equally ignored?

RESULT (2026-08-05): still broken. Three calls with different
firstname/lastname/dim_loyalty_id combinations -- including one fake ID
and one real driver name (James Okafor) -- all return byte-for-byte
identical records. The server-side filter is a no-op regardless of which
argument combination is sent. dim_loyalty_id being in the schema now is a
documentation/schema change only, not a behavior fix.

Do NOT wire dim_loyalty_id into celonis_client.celonis_load_driver() based
on the schema alone -- it has no effect. Re-run this script after Celonis
reports a fix before changing that assumption.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from celonis_client import _call_tool

r1 = _call_tool("load_data_driver_info", {
    "firstname": "Zzyzx", "lastname": "Nonexistent99",
    "dim_loyalty_id": "AAAA-does-not-exist", "page": 0, "page_size": 10,
})
r2 = _call_tool("load_data_driver_info", {
    "firstname": "Zzyzx", "lastname": "Nonexistent99",
    "dim_loyalty_id": "BBBB-also-fake", "page": 0, "page_size": 10,
})
r3 = _call_tool("load_data_driver_info", {
    "firstname": "James", "lastname": "Okafor",
    "dim_loyalty_id": "AAAA-does-not-exist", "page": 0, "page_size": 10,
})

print("Different dim_loyalty_id, same name -> identical output:", r1 == r2)
print("Different name, same dim_loyalty_id -> identical output:", r1 == r3)

if r1 == r2 == r3:
    print("\nCONFIRMED: dim_loyalty_id (and firstname/lastname) are still "
          "not applied as a server-side filter, despite the schema update.")
else:
    print("\nCHANGED BEHAVIOR DETECTED -- re-investigate, the bug may be "
          "fixed. Do not assume this result without re-checking manually.")
