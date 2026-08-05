"""
Databricks Client for RoadIQ
-----------------------------
Queries the Pilot Flying J Databricks sandbox for:
- Location/stop data (dim_line_of_business_offering)
- Loyalty account info (dim_loyalty_household + dim_guest_household)
- Transaction history (fct_sale)
- Guest household summary (fct_dm_guest_household_summary)

All functions fall back to None on failure — caller handles fallback.
"""

import os
from databricks import sql as databricks_sql


def _connect():
    """Create Databricks SQL connection. Returns None if unconfigured."""
    host = os.getenv("DATABRICKS_HOST")
    http_path = os.getenv("DATABRICKS_HTTP_PATH")
    token = os.getenv("DATABRICKS_TOKEN")
    if not all([host, http_path, token]):
        return None
    try:
        return databricks_sql.connect(
            server_hostname=host,
            http_path=http_path,
            access_token=token,
        )
    except Exception as e:
        print(f"[databricks] Connection failed: {e}")
        return None


def _query(sql_text, params=None):
    """Execute query, return list of dicts. Returns None on failure."""
    conn = _connect()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(sql_text, params)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        print(f"[databricks] Query failed: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. STOPS IN CORRIDOR
# ═══════════════════════════════════════════════════════════════════════════════

def get_stops_in_corridor(min_lat, max_lat, min_lon, max_lon, driver_id=None):
    """
    Query dim_line_of_business_offering for open Pilot stops within a
    geographic bounding box.

    Returns list of dicts with standardized keys, or None on failure.
    Optionally cross-references fct_sale to flag stops the driver visited.
    """
    sql_text = """
        SELECT
            DIM_LINE_OF_BUSINESS_ID,
            STOREFRONT_BRAND,
            DIESEL_BRAND,
            CITY,
            STATE,
            ADDRESS_1,
            ADDRESS_LATITUDE,
            ADDRESS_LONGITUDE,
            INTERSTATE,
            IS_PFJ_OPERATED,
            IN_NETWORK,
            HAS_DRIVERS_LOUNGE,
            HAS_IDELAIR,
            HAS_DIESEL_MOBILE_FUELING,
            HAS_AIR_VAC,
            HAS_ATMS,
            HAS_CHECK_CASHING,
            PRIMARY_STOREFRONT_BRAND,
            LINE_OF_BUSINESS_STATUS,
            FLEET_LOCATION_ID
        FROM innovate.location.dim_line_of_business_offering
        WHERE LINE_OF_BUSINESS_STATUS = 'OPEN'
          AND PRIMARY_STOREFRONT_BRAND IN ('PILOT', 'FLYING J', 'PILOT FLYING J')
          AND ADDRESS_LATITUDE BETWEEN {min_lat} AND {max_lat}
          AND ADDRESS_LONGITUDE BETWEEN {min_lon} AND {max_lon}
    """.format(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)

    rows = _query(sql_text)
    if rows is None:
        return None

    # Get visited stops if driver_id is provided
    visited_lob_ids = set()
    if driver_id is not None:
        visit_sql = """
            SELECT DISTINCT DIM_LINE_OF_BUSINESS_ID
            FROM innovate.pos_transactions_inventory.fct_sale
            WHERE DIM_CUSTOMER_DRIVER_ID = {did}
        """.format(did=int(driver_id))
        visit_rows = _query(visit_sql)
        if visit_rows:
            visited_lob_ids = {r["DIM_LINE_OF_BUSINESS_ID"] for r in visit_rows}

    stops = []
    for r in rows:
        stops.append({
            "lob_id": r["DIM_LINE_OF_BUSINESS_ID"],
            "name": f"{r['STOREFRONT_BRAND']} {r['CITY']}",
            "brand": r["STOREFRONT_BRAND"],
            "diesel_brand": r["DIESEL_BRAND"],
            "city": r["CITY"],
            "state": r["STATE"],
            "address": r["ADDRESS_1"],
            "lat": r["ADDRESS_LATITUDE"],
            "lon": r["ADDRESS_LONGITUDE"],
            "interstate": r["INTERSTATE"],
            "is_pfj": r["IS_PFJ_OPERATED"],
            "in_network": r["IN_NETWORK"],
            "has_lounge": r["HAS_DRIVERS_LOUNGE"],
            "has_idle_air": r["HAS_IDELAIR"],
            "has_mobile_fuel": r["HAS_DIESEL_MOBILE_FUELING"],
            "has_air_vac": r["HAS_AIR_VAC"],
            "has_atms": r["HAS_ATMS"],
            "primary_brand": r["PRIMARY_STOREFRONT_BRAND"],
            "fleet_location_id": r["FLEET_LOCATION_ID"],
            "visited_before": r["DIM_LINE_OF_BUSINESS_ID"] in visited_lob_ids,
        })
    return stops


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DRIVER LOYALTY
# ═══════════════════════════════════════════════════════════════════════════════

def get_driver_loyalty(driver_id):
    """
    Query dim_loyalty_household for member tier, card type, and join with
    fct_dm_guest_household_summary for total gallons + visits.

    Returns dict with loyalty info, or None on failure.
    """
    sql_text = """
        SELECT
            lh.DIM_LOYALTY_HOUSEHOLD_ID,
            lh.LOYALTY_HOUSEHOLD_ID,
            lh.LOYALTY_FIRST_NAME,
            lh.LOYALTY_LAST_NAME,
            lh.LOYALTY_CARD_TYPE,
            lh.LOYALTY_PROGRAM,
            lh.LOYALTY_CITY,
            lh.LOYALTY_STATE,
            lh.LOYALTY_ISSUE_DATE,
            gs.TOTAL_GALLONS,
            gs.TOTAL_VISITS,
            gs.LAST_VISIT_DATE
        FROM innovate.loyalty.dim_loyalty_household lh
        LEFT JOIN innovate.loyalty.fct_dm_guest_household_summary gs
            ON lh.DIM_LOYALTY_HOUSEHOLD_ID = gs.DIM_GUEST_HOUSEHOLD_ID
        WHERE lh.DIM_LOYALTY_HOUSEHOLD_ID = {did}
        LIMIT 1
    """.format(did=int(driver_id))

    rows = _query(sql_text)
    if not rows:
        return None

    r = rows[0]
    return {
        "household_id": r["LOYALTY_HOUSEHOLD_ID"],
        "first_name": r["LOYALTY_FIRST_NAME"],
        "last_name": r["LOYALTY_LAST_NAME"],
        "loyalty_tier": r["LOYALTY_CARD_TYPE"],
        "loyalty_program": r["LOYALTY_PROGRAM"],
        "city": r["LOYALTY_CITY"],
        "state": r["LOYALTY_STATE"],
        "issue_date": str(r["LOYALTY_ISSUE_DATE"]) if r["LOYALTY_ISSUE_DATE"] else None,
        "total_gallons": round(r["TOTAL_GALLONS"], 1) if r["TOTAL_GALLONS"] else 0,
        "total_visits": r["TOTAL_VISITS"] or 0,
        "last_visit_date": str(r["LAST_VISIT_DATE"]) if r["LAST_VISIT_DATE"] else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. RECENT TRANSACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_recent_transactions(driver_id, limit=10):
    """
    Query fct_sale for a driver's recent transactions.
    Returns list of transaction dicts, or None on failure.
    """
    sql_text = """
        SELECT
            s.TRANSACTION_ID,
            s.START_DATE_TIME,
            s.DIM_LINE_OF_BUSINESS_ID,
            s.SALES_AMOUNT,
            s.SALES_QUANTITY,
            s.GROSS_PROFIT,
            s.DIM_STORE_ID,
            s.SALE_TYPE,
            loc.CITY AS STOP_CITY,
            loc.STATE AS STOP_STATE,
            loc.STOREFRONT_BRAND AS STOP_BRAND
        FROM innovate.pos_transactions_inventory.fct_sale s
        LEFT JOIN innovate.location.dim_line_of_business_offering loc
            ON s.DIM_LINE_OF_BUSINESS_ID = loc.DIM_LINE_OF_BUSINESS_ID
        WHERE s.DIM_CUSTOMER_DRIVER_ID = {did}
        ORDER BY s.DIM_DATE_ID DESC
        LIMIT {lim}
    """.format(did=int(driver_id), lim=int(limit))

    rows = _query(sql_text)
    if not rows:
        return None

    txns = []
    for r in rows:
        txns.append({
            "transaction_id": r["TRANSACTION_ID"],
            "date": r["START_DATE_TIME"],
            "location_id": r["DIM_LINE_OF_BUSINESS_ID"],
            "stop_city": r.get("STOP_CITY", ""),
            "stop_state": r.get("STOP_STATE", ""),
            "stop_brand": r.get("STOP_BRAND", ""),
            "amount": round(r["SALES_AMOUNT"], 2) if r["SALES_AMOUNT"] else 0,
            "quantity": round(r["SALES_QUANTITY"], 2) if r["SALES_QUANTITY"] else 0,
            "sale_type": r["SALE_TYPE"],
        })
    return txns


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DRIVER SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def get_driver_summary(driver_id):
    """
    Query fct_dm_guest_household_summary for total visits, gallons, last visit.
    Also queries fct_sale for average spend and most visited location.

    Returns summary dict, or None on failure.
    """
    # Base summary
    summary_sql = """
        SELECT
            DIM_GUEST_HOUSEHOLD_ID,
            HOUSEHOLD_NAME,
            TOTAL_GALLONS,
            TOTAL_VISITS,
            LAST_VISIT_DATE
        FROM innovate.loyalty.fct_dm_guest_household_summary
        WHERE DIM_GUEST_HOUSEHOLD_ID = {did}
        LIMIT 1
    """.format(did=int(driver_id))

    rows = _query(summary_sql)
    if not rows:
        return None

    r = rows[0]
    result = {
        "household_id": r["DIM_GUEST_HOUSEHOLD_ID"],
        "household_name": r["HOUSEHOLD_NAME"],
        "total_gallons": round(r["TOTAL_GALLONS"], 1) if r["TOTAL_GALLONS"] else 0,
        "total_visits": r["TOTAL_VISITS"] or 0,
        "last_visit_date": str(r["LAST_VISIT_DATE"]) if r["LAST_VISIT_DATE"] else None,
        "avg_spend": 0,
        "most_visited_location": None,
    }

    # Average spend + most visited from fct_sale
    spend_sql = """
        SELECT
            AVG(SALES_AMOUNT) as AVG_SPEND,
            COUNT(*) as TXN_COUNT
        FROM innovate.pos_transactions_inventory.fct_sale
        WHERE DIM_CUSTOMER_DRIVER_ID = {did}
    """.format(did=int(driver_id))

    spend_rows = _query(spend_sql)
    if spend_rows and spend_rows[0]["AVG_SPEND"]:
        result["avg_spend"] = round(spend_rows[0]["AVG_SPEND"], 2)

    # Most visited location
    loc_sql = """
        SELECT
            s.DIM_LINE_OF_BUSINESS_ID,
            loc.CITY,
            loc.STATE,
            loc.STOREFRONT_BRAND,
            COUNT(*) as VISIT_COUNT
        FROM innovate.pos_transactions_inventory.fct_sale s
        LEFT JOIN innovate.location.dim_line_of_business_offering loc
            ON s.DIM_LINE_OF_BUSINESS_ID = loc.DIM_LINE_OF_BUSINESS_ID
        WHERE s.DIM_CUSTOMER_DRIVER_ID = {did}
        GROUP BY s.DIM_LINE_OF_BUSINESS_ID, loc.CITY, loc.STATE, loc.STOREFRONT_BRAND
        ORDER BY VISIT_COUNT DESC
        LIMIT 1
    """.format(did=int(driver_id))

    loc_rows = _query(loc_sql)
    if loc_rows:
        lr = loc_rows[0]
        result["most_visited_location"] = f"{lr.get('STOREFRONT_BRAND', '')} {lr.get('CITY', '')}, {lr.get('STATE', '')}"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PARKING DEMAND FORECAST
# ═══════════════════════════════════════════════════════════════════════════════

def get_parking_availability(lob_ids):
    """
    Query fct_parking_demand_forecast for parking availability at given locations.
    Returns dict mapping lob_id → parking_pct_available (0-100).
    """
    if not lob_ids:
        return {}
    id_list = ",".join(str(int(x)) for x in lob_ids)
    sql_text = f"""
        SELECT
            DIM_LINE_OF_BUSINESS_ID,
            TOTAL_PARKING_SPACES,
            FORECAST_RESERVATION_QUANTITY,
            RESERVATION_RATE
        FROM innovate.loyalty.fct_parking_demand_forecast
        WHERE DIM_LINE_OF_BUSINESS_ID IN ({id_list})
          AND DIM_DATE_ID = (
              SELECT MAX(DIM_DATE_ID)
              FROM innovate.loyalty.fct_parking_demand_forecast
              WHERE DIM_LINE_OF_BUSINESS_ID IN ({id_list})
          )
    """
    rows = _query(sql_text)
    if not rows:
        return {}

    result = {}
    for r in rows:
        lob_id = r["DIM_LINE_OF_BUSINESS_ID"]
        rate = r["RESERVATION_RATE"] or 0
        # Availability = 1 - reservation rate (rate=0.5 means 50% full → 50% available)
        pct_available = round((1 - rate) * 100)
        result[lob_id] = {
            "parking_pct_available": max(0, min(100, pct_available)),
            "total_spaces": r["TOTAL_PARKING_SPACES"],
            "spaces_reserved": r["FORECAST_RESERVATION_QUANTITY"],
        }
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SHOWER WAIT TIMES
# ═══════════════════════════════════════════════════════════════════════════════

def get_shower_wait(location_ids):
    """
    Query drive_shower_utilization for average recent wait times per location.
    Returns dict mapping location_id → avg_wait_minutes.
    """
    if not location_ids:
        return {}
    id_list = ",".join(str(int(x)) for x in location_ids)
    sql_text = f"""
        SELECT
            location_id,
            AVG(wait_time_minutes) AS avg_wait,
            COUNT(*) AS sample_count
        FROM innovate.team02.drive_shower_utilization
        WHERE location_id IN ({id_list})
        GROUP BY location_id
    """
    rows = _query(sql_text)
    if not rows:
        return {}

    return {
        r["location_id"]: {
            "avg_wait_minutes": round(r["avg_wait"], 0),
            "sample_count": r["sample_count"],
        }
        for r in rows
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. FUEL PRICES
# ═══════════════════════════════════════════════════════════════════════════════

def get_fuel_prices():
    """
    Query fct_fuel_supply_price for latest active diesel prices.
    Returns dict mapping DIM_SUPPLY_PRODUCT_ID → price info.
    Since we can't easily join to location, return the most recent active prices.
    """
    sql_text = """
        SELECT
            DIM_SUPPLY_PRODUCT_ID,
            PRICE_PER_GALLON,
            GROSS_PRICE_PER_GALLON,
            CONTRACT_DISCOUNT,
            PRICE_TYPE,
            DIM_DATE_ID
        FROM innovate.price.fct_fuel_supply_price
        WHERE IS_ACTIVE = true
        ORDER BY DIM_DATE_ID DESC
        LIMIT 20
    """
    rows = _query(sql_text)
    if not rows:
        return {}

    # Return average price as a representative diesel price
    prices = [float(r["PRICE_PER_GALLON"]) for r in rows if r["PRICE_PER_GALLON"]]
    gross_prices = [float(r["GROSS_PRICE_PER_GALLON"]) for r in rows if r["GROSS_PRICE_PER_GALLON"]]
    discounts = [float(r["CONTRACT_DISCOUNT"]) for r in rows if r["CONTRACT_DISCOUNT"]]

    return {
        "avg_net_price": round(sum(prices) / len(prices), 3) if prices else None,
        "avg_gross_price": round(sum(gross_prices) / len(gross_prices), 3) if gross_prices else None,
        "avg_fleet_discount": round(sum(discounts) / len(discounts), 3) if discounts else None,
        "sample_count": len(rows),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. MOBILE OFFERS FOR DRIVER
# ═══════════════════════════════════════════════════════════════════════════════

def get_driver_offers(guest_household_id):
    """
    Query fct_guest_mobile_offers for active offers for a given driver.
    Returns list of offer dicts, or None on failure.
    """
    sql_text = """
        SELECT
            OFFER_ID,
            OFFER_TYPE,
            OFFER_VALUE,
            OFFER_EXPIRY
        FROM innovate.loyalty.fct_guest_mobile_offers
        WHERE DIM_GUEST_HOUSEHOLD_ID = {hid}
          AND OFFER_EXPIRY > CURRENT_TIMESTAMP()
        ORDER BY OFFER_VALUE DESC
        LIMIT 5
    """.format(hid=int(guest_household_id))

    rows = _query(sql_text)
    if not rows:
        return None

    return [
        {
            "offer_id": r["OFFER_ID"],
            "offer_type": r["OFFER_TYPE"],
            "offer_value": round(float(r["OFFER_VALUE"]), 2) if r["OFFER_VALUE"] else 0,
            "expires": str(r["OFFER_EXPIRY"]) if r["OFFER_EXPIRY"] else None,
        }
        for r in rows
    ]
