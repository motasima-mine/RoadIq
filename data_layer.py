"""
RoadIQ Data Layer
-----------------
Provides get_drivers() and get_locations() used by app.py.

Driver data comes from local JSON.
Location data comes from Databricks (innovate.location.dim_line_of_business_offering).
Falls back to local JSON if Databricks is unavailable.
"""

import json
import os


def _json_path(filename):
    """Resolve path to a data file relative to this module."""
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "data", filename)


def get_drivers():
    """
    Read data/drivers.json and return as a list of driver dicts.

    Raises:
        FileNotFoundError: if data/drivers.json is missing
    """
    path = _json_path("drivers.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Driver data not found at {path}. "
            f"Ensure data/drivers.json exists in the roadiq folder."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_databricks_connection():
    """Create a Databricks SQL connection. Returns None if not configured."""
    try:
        from databricks import sql as databricks_sql

        host = os.getenv("DATABRICKS_HOST")
        http_path = os.getenv("DATABRICKS_HTTP_PATH")
        token = os.getenv("DATABRICKS_TOKEN")

        if not all([host, http_path, token]):
            return None

        return databricks_sql.connect(
            server_hostname=host,
            http_path=http_path,
            access_token=token,
        )
    except Exception:
        return None


def get_locations():
    """
    Fetch Pilot stop locations from Databricks.
    Falls back to local JSON if Databricks is unavailable.

    Returns: dict keyed by location id
    """
    conn = _get_databricks_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT STOREFRONT_BRAND, CITY, STATE,
                       ADDRESS_LATITUDE, ADDRESS_LONGITUDE,
                       HAS_DRIVERS_LOUNGE, HAS_IDELAIR,
                       HAS_DIESEL_MOBILE_FUELING, IS_PFJ_OPERATED,
                       DIESEL_BRAND, ADDRESS_1, INTERSTATE,
                       LINE_OF_BUSINESS_STATUS
                FROM innovate.location.dim_line_of_business_offering
                WHERE LINE_OF_BUSINESS_STATUS = 'OPEN'
            """)
            cols = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            locations = []
            for row in rows:
                r = dict(zip(cols, row))
                locations.append({
                    "id": f"{r['CITY']}_{r['ADDRESS_LATITUDE']:.3f}",
                    "name": f"{r['STOREFRONT_BRAND']} {r['CITY']}",
                    "brand": r["STOREFRONT_BRAND"],
                    "city": f"{r['CITY']}, {r['STATE']}",
                    "state": r["STATE"],
                    "lat": r["ADDRESS_LATITUDE"],
                    "lon": r["ADDRESS_LONGITUDE"],
                    "address": r["ADDRESS_1"],
                    "interstate": r["INTERSTATE"],
                    "diesel_brand": r["DIESEL_BRAND"],
                    "has_lounge": r["HAS_DRIVERS_LOUNGE"],
                    "has_idle_air": r["HAS_IDELAIR"],
                    "has_mobile_fuel": r["HAS_DIESEL_MOBILE_FUELING"],
                    "is_pfj": r["IS_PFJ_OPERATED"],
                    "source": "databricks",
                })
            if locations:
                return {loc["id"]: loc for loc in locations}
        except Exception as e:
            print(f"[data_layer] Databricks query failed: {e}")

    # Fallback to local JSON
    path = _json_path("locations.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Location data not found at {path}. "
            f"Ensure data/locations.json exists in the roadiq folder."
        )
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {loc["id"]: loc for loc in raw}
