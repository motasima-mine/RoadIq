"""
Run this to verify Databricks connectivity and discover real column names.
Usage:  python test_databricks.py
"""
import os
from databricks import sql
from dotenv import load_dotenv

load_dotenv()

def run(label, query):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print('='*60)
    try:
        with sql.connect(
            server_hostname=os.getenv("DATABRICKS_HOST"),
            http_path=os.getenv("DATABRICKS_HTTP_PATH"),
            access_token=os.getenv("DATABRICKS_TOKEN"),
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                print(f"Columns: {cols}")
                print(f"Row count: {len(rows)}")
                if rows:
                    print(f"First row: {dict(zip(cols, rows[0]))}")
    except Exception as e:
        print(f"ERROR: {e}")

# Discover actual column names — LIMIT 1 so it's fast
run("dim_line_of_business_offering",
    "SELECT * FROM dim_line_of_business_offering LIMIT 1")

run("dim_loyalty",
    "SELECT * FROM dim_loyalty LIMIT 1")

run("fct_sale",
    "SELECT * FROM fct_sale LIMIT 1")

run("fct_dm_guest_household_summary",
    "SELECT * FROM fct_dm_guest_household_summary LIMIT 1")
