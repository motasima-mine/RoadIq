"""Search all catalogs/schemas/tables for anything related to 'pfj_360' or
store resource/utility/amenity data we haven't already catalogued."""
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

print("=" * 70)
print("STEP 1: All catalogs")
print("=" * 70)
cursor.execute("SHOW CATALOGS")
catalogs = [r[0] for r in cursor.fetchall()]
for c in catalogs:
    print(f"  {c}")

print("\n" + "=" * 70)
print("STEP 2: Search for 'pfj', '360', 'resource', 'utility', 'amenity' in table names")
print("=" * 70)

keywords = ["pfj", "360", "resource", "utilit", "amenit"]
matches = []

for catalog in catalogs:
    if catalog in ("system", "samples"):
        continue
    try:
        cursor.execute(f"SHOW SCHEMAS IN {catalog}")
        schemas = [r[0] for r in cursor.fetchall()]
    except Exception as e:
        print(f"  (catalog {catalog}: {e})")
        continue

    for schema in schemas:
        if schema == "information_schema":
            continue
        # Check schema name itself for keyword match
        schema_hit = any(k in schema.lower() for k in keywords)
        try:
            cursor.execute(f"SHOW TABLES IN {catalog}.{schema}")
            tables = cursor.fetchall()
        except Exception:
            continue
        for t in tables:
            tname = t[1]
            if schema_hit or any(k in tname.lower() for k in keywords):
                match = f"{catalog}.{schema}.{tname}"
                matches.append(match)
                print(f"  MATCH: {match}")

print(f"\nTotal matches: {len(matches)}")

cursor.close()
conn.close()
