"""Inspect the most promising PFJ 360 store resource/amenity/utility tables."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from databricks import sql

conn = sql.connect(
    server_hostname=os.getenv("DATABRICKS_HOST"),
    http_path=os.getenv("DATABRICKS_HTTP_PATH"),
    access_token=os.getenv("DATABRICKS_TOKEN"),
)
cursor = conn.cursor()

tables = [
    "dev.location.corpdata_location_amenity",
    "dev.location.pfj360_offering",
    "dev.location.pfj360_offeringattribute",
    "dev.location.pfj360_siteattributebridge",
    "dev.location.pfj360ods_parking_parking",
    "dev.location.pfj360_storehours",
    "dev.location.pfj360ods_location_truckstop",
    "dev.location.gpss_pfj360_location",
    "dev.location.pfj360_b2bsite",
]

for table in tables:
    print("\n" + "=" * 70)
    print(f"TABLE: {table}")
    print("=" * 70)
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"Row count: {count}")

        cursor.execute(f"SELECT * FROM {table} LIMIT 1")
        cols = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        print(f"Columns ({len(cols)}):")
        for c in cols:
            val = dict(zip(cols, row)).get(c, None) if row else None
            print(f"  {c:40s} = {repr(val)[:60]}")
    except Exception as e:
        print(f"  ERROR: {e}")

cursor.close()
conn.close()
