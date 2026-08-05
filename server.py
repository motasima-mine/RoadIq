import json
import os
import urllib3
import boto3
import requests
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Disable SSL verification for corporate proxy environments
os.environ["AWS_CA_BUNDLE"] = ""
os.environ["CURL_CA_BUNDLE"] = ""
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

app = Flask(__name__, static_folder="static")

# ── data ──────────────────────────────────────────────────────────────────────
_base = os.path.dirname(__file__)

with open(os.path.join(_base, "data", "drivers.json")) as f:
    DRIVERS = json.load(f)

with open(os.path.join(_base, "data", "locations.json")) as f:
    LOCATIONS = json.load(f)

DEMO_DRIVER = next(d for d in DRIVERS if d["id"] == 7)
DEMO_STOP   = next(l for l in LOCATIONS if l["id"] == "knoxville_198")

# ── Bedrock ───────────────────────────────────────────────────────────────────
def _bedrock():
    import botocore.config
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        verify=False,
        config=botocore.config.Config(
            retries={"max_attempts": 2, "mode": "standard"}
        ),
    )

def ask_ai(prompt_text, max_tokens=450):
    try:
        model_id = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
        r = _bedrock().converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt_text}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.7},
        )
        return r["output"]["message"]["content"][0]["text"]
    except Exception as e:
        print(f"[bedrock] AI call failed: {e}")
        return None  # caller handles fallback

# ── Celonis ───────────────────────────────────────────────────────────────────
_token_cache = {"token": None, "expires_at": 0}

def _celonis_token():
    import time
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["token"]
    r = requests.post(
        os.getenv("CELONIS_TOKEN_URL"),
        data={"grant_type": "client_credentials",
              "client_id": os.getenv("CELONIS_CLIENT_ID"),
              "client_secret": os.getenv("CELONIS_CLIENT_SECRET")},
        timeout=10, verify=False,
    )
    r.raise_for_status()
    data = r.json()
    import time
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]

def celonis_stops(from_coords, to_coords):
    try:
        token = _celonis_token()
        lats = [from_coords[0], to_coords[0]]
        lons = [from_coords[1], to_coords[1]]
        base = os.getenv("CELONIS_TOKEN_URL", "").replace("/oauth2/token", "")
        r = requests.get(
            f"{base}/api/locations",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_lat": min(lats)-1.5, "max_lat": max(lats)+1.5,
                    "min_lon": min(lons)-1.5, "max_lon": max(lons)+1.5},
            timeout=15, verify=False,
        )
        r.raise_for_status()
        raw = r.json()
        records = raw if isinstance(raw, list) else raw.get("data", [])
        out = []
        for loc in records:
            if loc.get("O_CUSTOM_LINEOFBUSINESS.LINEOFBUSINESSSTATUS") != "OPEN":
                continue
            out.append({
                "lat":   loc.get("O_CUSTOM_LINEOFBUSINESS.ADDRESSLATITUDE"),
                "lng":   loc.get("O_CUSTOM_LINEOFBUSINESS.ADDRESSLONGITUDE"),
                "city":  loc.get("O_CUSTOM_LINEOFBUSINESS.CITY", ""),
                "state": loc.get("O_CUSTOM_LINEOFBUSINESS.STATE", ""),
                "brand": loc.get("O_CUSTOM_LINEOFBUSINESS.STOREFRONTBRAND", ""),
            })
        return out if out else None
    except Exception as e:
        print(f"[celonis] {e}")
        return None

# ── OSRM route ────────────────────────────────────────────────────────────────
def osrm_route(from_coords, to_coords):
    try:
        url = (f"http://router.project-osrm.org/route/v1/driving/"
               f"{from_coords[1]},{from_coords[0]};{to_coords[1]},{to_coords[0]}"
               f"?overview=full&geometries=geojson")
        r = requests.get(url, timeout=10)
        coords = r.json()["routes"][0]["geometry"]["coordinates"]
        return [[c[1], c[0]] for c in coords]
    except Exception:
        return None

# ── API routes ────────────────────────────────────────────────────────────────
@app.route("/api/driver")
def api_driver():
    """Return demo driver enriched with real Databricks loyalty data."""
    driver = dict(DEMO_DRIVER)  # copy so we don't mutate global
    try:
        from databricks_client import get_driver_loyalty, get_driver_summary
        # Use DIM_LOYALTY_HOUSEHOLD_ID = 7 for demo (James Okafor)
        loyalty = get_driver_loyalty(7)
        if loyalty:
            driver["loyalty_tier"] = loyalty["loyalty_tier"]
            driver["total_gallons"] = loyalty["total_gallons"]
            driver["total_visits"] = loyalty["total_visits"]
            driver["last_visit_date"] = loyalty["last_visit_date"]
            driver["loyalty_program"] = loyalty["loyalty_program"]
            driver["data_source"] = "databricks"

        summary = get_driver_summary(7)
        if summary:
            driver["avg_spend"] = summary["avg_spend"]
            driver["most_visited_location"] = summary["most_visited_location"]
    except Exception as e:
        print(f"[api_driver] Databricks enrichment failed: {e}")
        driver["data_source"] = "local"

    return jsonify(driver)

@app.route("/api/stop")
def api_stop():
    return jsonify(DEMO_STOP)

@app.route("/api/route")
def api_route():
    # Nashville → Knoxville → Atlanta
    nash  = (36.1627, -86.7816)
    knox  = (35.9606, -83.9207)
    atl   = (33.7490, -84.3880)
    leg1  = osrm_route(nash, knox)
    leg2  = osrm_route(knox, atl)
    coords = (leg1 or []) + (leg2 or [])
    stops = celonis_stops(nash, atl) or [
        {"lat": DEMO_STOP["lat"], "lng": DEMO_STOP["lon"],
         "name": DEMO_STOP["name"], "city": DEMO_STOP["city"]}
    ]
    return jsonify({"route": coords, "stops": stops,
                    "recommended": DEMO_STOP})

@app.route("/api/ai", methods=["POST"])
def api_ai():
    body   = request.json or {}
    mode   = body.get("mode", "plan")
    driver = DEMO_DRIVER
    stop   = DEMO_STOP

    if mode == "plan":
        prompt = (
            f"You are RoadIQ, an AI co-pilot for Pilot Flying J truck drivers.\n"
            f"Driver: {driver['name']}, Platinum loyalty member.\n"
            f"Route: {driver['current_location']} → {driver['destination']}\n"
            f"Fuel remaining: {driver['fuel_remaining_miles']} miles. Status: FUEL RISK.\n"
            f"Recommended stop: {stop['name']} in {stop['city']}\n"
            f"  - Parking: {stop['parking_forecast_pct']}% available\n"
            f"  - Shower wait: {stop['shower_wait_min']} min\n"
            f"  - Food: {stop['food_available']}\n"
            f"  - Fleet fuel agreement: Yes\n\n"
            f"Give a concise, friendly journey plan in 3-4 bullet points. "
            f"Include fuel stop timing, parking tip, and a loyalty perk reminder. "
            f"Keep it under 120 words. Use plain text, no markdown."
        )
    else:
        user_msg = body.get("message", "")
        prompt = (
            f"You are RoadIQ, Pilot Flying J's AI driver assistant. "
            f"Driver is James Okafor, Platinum member, Nashville→Atlanta, fuel risk at 140mi remaining. "
            f"Answer this question helpfully and concisely (under 80 words): {user_msg}"
        )

    result = ask_ai(prompt)
    if result:
        return jsonify({"text": result, "source": "bedrock"})

    # Fallback
    if mode == "plan":
        fallback = (
            "• Fuel up now — you have ~140 miles left, stop at Pilot Knoxville #198 in ~95 miles.\n"
            "• Parking looks good: 78% available when you arrive (~1.5 hrs).\n"
            "• Shower wait is only 8 min — quick stop before Atlanta.\n"
            "• As a Platinum member, you'll earn 2x points on this fill-up. Subway is open inside."
        )
    else:
        fallback = "I'm here to help with your route, fuel stops, parking, and loyalty rewards. What do you need?"
    return jsonify({"text": fallback, "source": "fallback"})

# ── geocode city string to lat/lon via Nominatim ─────────────────────────────
_geo_cache = {}
def geocode(place):
    if place in _geo_cache:
        return _geo_cache[place]
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": place, "format": "json", "limit": 1},
            headers={"User-Agent": "RoadIQ/1.0"},
            timeout=8, verify=False,
        )
        data = r.json()
        if data:
            result = (float(data[0]["lat"]), float(data[0]["lon"]))
            _geo_cache[place] = result
            return result
    except Exception:
        pass
    return None

# ── Trip Planner ──────────────────────────────────────────────────────────────
@app.route("/api/plan", methods=["POST"])
def api_plan():
    body  = request.json or {}
    from_ = body.get("from", "Nashville, TN")
    to_   = body.get("to", "Atlanta, GA")
    prefs = body.get("prefs", ["fuel"])

    # Geocode endpoints
    from_coords = geocode(from_) or (36.1627, -86.7816)
    to_coords   = geocode(to_)   or (33.7490, -84.3880)

    # Bounding box for stop corridor
    min_lat = min(from_coords[0], to_coords[0]) - 0.5
    max_lat = max(from_coords[0], to_coords[0]) + 0.5
    min_lon = min(from_coords[1], to_coords[1]) - 0.5
    max_lon = max(from_coords[1], to_coords[1]) + 0.5

    # Try Databricks first, fall back to local JSON
    corridor_stops = None
    parking_data = {}
    shower_data = {}
    fuel_prices = {}
    driver_offers = None
    try:
        from databricks_client import (
            get_stops_in_corridor, get_parking_availability,
            get_shower_wait, get_fuel_prices, get_driver_offers
        )
        corridor_stops = get_stops_in_corridor(min_lat, max_lat, min_lon, max_lon, driver_id=7)

        # If corridor returns nothing (sandbox has synthetic coords), get all open stops
        if not corridor_stops:
            corridor_stops = get_stops_in_corridor(-90, 90, -180, 180, driver_id=7)

        # Enrich with parking, shower, fuel, offers
        if corridor_stops:
            lob_ids = [s["lob_id"] for s in corridor_stops if s.get("lob_id")]
            location_ids = [s.get("lob_id") for s in corridor_stops]  # location_id maps to lob_id in sandbox

            parking_data = get_parking_availability(lob_ids) or {}
            shower_data = get_shower_wait(location_ids) or {}

        fuel_prices = get_fuel_prices() or {}
        driver_offers = get_driver_offers(7) or get_driver_offers(5) or []
    except Exception as e:
        print(f"[plan] databricks unavailable: {e}")

    # Fall back to local locations.json
    if not corridor_stops:
        corridor_stops = [
            {
                "name": l["name"],
                "city": l["city"],
                "lat": l["lat"],
                "lon": l["lon"],
                "has_lounge": True,
                "has_idle_air": False,
                "has_mobile_fuel": False,
                "is_pfj": True,
                "in_network": True,
                "brand": "PILOT",
                "diesel_brand": "PILOT",
                "interstate": "",
                "visited_before": False,
                "parking_forecast_pct": l.get("parking_forecast_pct", 75),
                "shower_wait_min": l.get("shower_wait_min", 10),
                "food_available": l.get("food_available", ""),
                "fleet_fuel_agreement": l.get("fleet_fuel_agreement", False),
            }
            for l in LOCATIONS
            if (min_lat <= l["lat"] <= max_lat and min_lon <= l["lon"] <= max_lon)
        ]

    # Build optimized stop list — pick 1-3 stops spaced along route
    # Sort by latitude proximity to origin, pick up to 2
    if corridor_stops:
        corridor_stops.sort(key=lambda s: abs(
            s.get("lat", 0) - from_coords[0]
        ))
        # Prefer PFJ-operated, in-network stops; then visited-before stops
        corridor_stops.sort(key=lambda s: (
            not s.get("is_pfj", False),
            not s.get("in_network", False),
            not s.get("visited_before", False),
        ))
        chosen = corridor_stops[:2]
    else:
        chosen = []

    # Estimate total miles via OSRM
    try:
        r = requests.get(
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{from_coords[1]},{from_coords[0]};{to_coords[1]},{to_coords[0]}"
            f"?overview=false",
            timeout=8
        )
        route_data = r.json()
        total_meters = route_data["routes"][0]["distance"]
        total_miles  = round(total_meters / 1609.34)
        drive_secs   = route_data["routes"][0]["duration"]
        drive_hours  = f"{int(drive_secs//3600)}h {int((drive_secs%3600)//60)}m"
    except Exception:
        total_miles  = 250
        drive_hours  = "~4h"

    total_gallons = round(total_miles / 6.5)  # avg 6.5 mpg heavy truck

    # HOS awareness
    hos_hours_driven = float(body.get("hos_hours_driven", 0))
    hos_remaining    = max(0, 11.0 - hos_hours_driven)
    hos_miles_left   = round(hos_remaining * 55)  # avg 55 mph

    # Build stops response
    stops_out = []
    for i, s in enumerate(chosen):
        name = s.get("name", "Pilot Stop")
        city = s.get("city", "")
        mile_marker = round(total_miles * (i + 1) / (len(chosen) + 1))
        lob_id = s.get("lob_id")

        # Real parking from forecast
        park_info = parking_data.get(lob_id, {})
        parking_pct = park_info.get("parking_pct_available", s.get("parking_forecast_pct", 75))
        total_spaces = park_info.get("total_spaces")

        # Real shower wait
        shower_info = shower_data.get(lob_id, {})
        shower_wait = shower_info.get("avg_wait_minutes", s.get("shower_wait_min", 10))

        # Real fuel price
        diesel_price = fuel_prices.get("avg_net_price")
        fleet_discount = fuel_prices.get("avg_fleet_discount", 0)

        stops_out.append({
            "name":               name,
            "city":               city,
            "mile_marker":        mile_marker,
            "reason":             "Fuel + rest break",
            "brand":              s.get("brand", "PILOT"),
            "diesel_brand":       s.get("diesel_brand", ""),
            "interstate":         s.get("interstate", ""),
            "has_lounge":         s.get("has_lounge", False),
            "has_idle_air":       s.get("has_idle_air", False),
            "has_mobile_fuel":    s.get("has_mobile_fuel", False),
            "is_pfj":             s.get("is_pfj", False),
            "in_network":         s.get("in_network", False),
            "visited_before":     s.get("visited_before", False),
            "parking_pct":        parking_pct,
            "total_spaces":       total_spaces,
            "shower_wait":        shower_wait,
            "diesel_price":       diesel_price,
            "fleet_discount":     fleet_discount,
            "food":               s.get("food_available", ""),
            "fleet_deal":         bool(s.get("fleet_fuel_agreement") or s.get("in_network")),
            "points_multiplier":  2 if DEMO_DRIVER["loyalty_tier"] == "Platinum" else 1,
        })

    # Savings estimate using real fleet vs gross price when available
    net_price   = fuel_prices.get("avg_net_price") or 0
    gross_price = fuel_prices.get("avg_gross_price") or (net_price + 0.10)
    price_diff  = round(gross_price - net_price, 3) if net_price else 0.08
    savings_amt = round(total_gallons * price_diff, 2)
    savings_str = f"${savings_amt:.0f}" if savings_amt else "$0"

    # Flag stops that require a break due to HOS
    for s in stops_out:
        s["hos_break_required"] = (
            hos_remaining < 2 or
            (s.get("mile_marker", 0) > hos_miles_left)
        )

    # Build AI prompt with real stop data
    stops_text = "\n".join([
        f"  Stop {i+1}: {s['name']}, {s['city']} at mile {s['mile_marker']}"
        f" — parking {s['parking_pct']}%, shower {s['shower_wait']} min, {s['food']}"
        for i, s in enumerate(stops_out)
    ]) or "  No Pilot stops found in corridor"

    hos_info = ""
    if body.get("hos_hours_driven"):
        hrs = body["hos_hours_driven"]
        hos_remaining = max(0, 11 - float(hrs))
        hos_info = f"HOS: {hrs}h driven today, {hos_remaining:.1f}h remaining on 11-hour limit. "

    loyalty_info = ""
    try:
        from databricks_client import get_driver_loyalty
        loy = get_driver_loyalty(7)
        if loy:
            loyalty_info = f"Loyalty: {loy['loyalty_tier']} member, {loy['total_gallons']} lifetime gallons, {loy['total_visits']} visits. "
    except Exception:
        pass

    prompt = (
        f"You are RoadIQ, the AI journey optimizer built exclusively for Pilot Flying J. "
        f"You ONLY recommend Pilot Flying J locations — never competitors.\n"
        f"Driver: {DEMO_DRIVER['name']}. {loyalty_info}{hos_info}"
        f"Route: {from_} to {to_} ({total_miles} miles, {drive_hours} drive).\n"
        f"Estimated diesel: {total_gallons} gallons at ${fuel_prices.get('avg_net_price', 'N/A')}/gal fleet price "
        f"(vs ${fuel_prices.get('avg_gross_price', 'N/A')}/gal retail) = estimated {savings_str} savings.\n"
        f"Driver needs: {', '.join(prefs)}.\n"
        f"Optimized Pilot Flying J stops:\n{stops_text}\n\n"
        f"Write a friendly 3-4 sentence journey briefing for James. "
        f"Highlight the Pilot Flying J stop(s), fleet pricing savings, loyalty benefit, and any HOS timing advice. "
        f"Never mention competitors. No bullet points — flowing sentences. Under 110 words."
    )

    ai_plan = ask_ai(prompt, max_tokens=200)
    if not ai_plan:
        ai_plan = (
            f"Your {total_miles}-mile route from {from_} to {to_} has been optimized with "
            f"{len(stops_out)} Pilot stop{'s' if len(stops_out)!=1 else ''}. "
            f"As a {DEMO_DRIVER['loyalty_tier']} member you'll earn 2x points on every fill-up, "
            f"and fleet pricing saves you an estimated {savings_str} on this trip. "
            f"Stops were chosen for parking availability and shower wait times."
        )

    # Build all_stops — every corridor stop with enrichment (not just chosen 2)
    all_stops_out = []
    for s in corridor_stops:
        lob_id = s.get("lob_id")
        park_info   = parking_data.get(lob_id, {})
        shower_info = shower_data.get(lob_id, {})
        is_chosen   = any(c.get("lob_id") == lob_id for c in chosen)
        all_stops_out.append({
            "lob_id":         lob_id,
            "name":           s.get("name", "Pilot Stop"),
            "city":           s.get("city", ""),
            "state":          s.get("state", ""),
            "lat":            s.get("lat"),
            "lon":            s.get("lon"),
            "brand":          s.get("brand", "PILOT"),
            "interstate":     s.get("interstate", ""),
            "is_chosen":      is_chosen,
            "visited_before": s.get("visited_before", False),
            "has_lounge":     s.get("has_lounge", False),
            "has_idle_air":   s.get("has_idle_air", False),
            "has_mobile_fuel": s.get("has_mobile_fuel", False),
            "parking_pct":    park_info.get("parking_pct_available", s.get("parking_forecast_pct", 75)),
            "shower_wait":    shower_info.get("avg_wait_minutes", s.get("shower_wait_min", 10)),
            "diesel_price":   fuel_prices.get("avg_net_price"),
            "fleet_deal":     bool(s.get("in_network")),
        })

    # Get OSRM route geometry for the map
    route_coords = []
    try:
        rr = requests.get(
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{from_coords[1]},{from_coords[0]};{to_coords[1]},{to_coords[0]}"
            f"?overview=full&geometries=geojson",
            timeout=8
        )
        coords = rr.json()["routes"][0]["geometry"]["coordinates"]
        route_coords = [[c[1], c[0]] for c in coords]
    except Exception:
        pass

    return jsonify({
        "from":          from_,
        "to":            to_,
        "from_coords":   list(from_coords),
        "to_coords":     list(to_coords),
        "total_miles":   total_miles,
        "drive_hours":   drive_hours,
        "total_gallons": total_gallons,
        "stops":         stops_out,
        "all_stops":     all_stops_out,
        "route_coords":  route_coords,
        "savings":       savings_str,
        "savings_detail": {
            "fleet_price":   net_price,
            "retail_price":  round(gross_price, 3),
            "savings_per_gal": round(price_diff, 3),
            "total_gallons": total_gallons,
            "total_savings": savings_amt,
        },
        "hos": {
            "hours_driven":   hos_hours_driven,
            "hours_remaining": hos_remaining,
            "miles_remaining": hos_miles_left,
        },
        "ai_plan":       ai_plan,
        "fuel_prices":   fuel_prices,
        "offers":        driver_offers or [],
    })

@app.route("/api/stop_advice", methods=["POST"])
def api_stop_advice():
    """Driver picks a specific stop — AI evaluates if it's good or bad for them."""
    body     = request.json or {}
    stop     = body.get("stop", {})
    from_    = body.get("from", "")
    to_      = body.get("to", "")
    prefs    = body.get("prefs", ["fuel"])
    hos_hrs  = body.get("hos_hours_driven", 0)

    loyalty_info = ""
    try:
        from databricks_client import get_driver_loyalty
        loy = get_driver_loyalty(7)
        if loy:
            loyalty_info = f"{loy['loyalty_tier']} member, {loy['total_gallons']} lifetime gallons. "
    except Exception:
        pass

    park  = stop.get("parking_pct", "N/A")
    shwr  = stop.get("shower_wait", "N/A")
    price = f"${stop['diesel_price']:.3f}/gal" if stop.get("diesel_price") else "fleet pricing"
    vis   = "Yes — you've stopped here before." if stop.get("visited_before") else "No."
    fleet = "Yes" if stop.get("fleet_deal") else "No"
    hos_remaining = max(0, 11 - float(hos_hrs))

    prompt = (
        f"You are RoadIQ, Pilot Flying J's AI co-pilot. Be direct and honest.\n"
        f"Driver: {DEMO_DRIVER['name']}. {loyalty_info}"
        f"Route: {from_} to {to_}. Driver needs: {', '.join(prefs)}.\n"
        f"HOS: {hos_hrs}h driven today, {hos_remaining:.1f}h remaining.\n\n"
        f"The driver is considering stopping at: {stop.get('name','this stop')}, {stop.get('city','')}, {stop.get('state','')}.\n"
        f"  - Diesel price: {price}\n"
        f"  - Parking available: {park}%\n"
        f"  - Shower wait: {shwr} min\n"
        f"  - Fleet deal: {fleet}\n"
        f"  - Visited before: {vis}\n"
        f"  - Drivers' lounge: {'Yes' if stop.get('has_lounge') else 'No'}\n\n"
        f"Give a SHORT verdict (2-3 sentences max): Is this a good stop for this driver right now? "
        f"State clearly GOOD STOP or WORTH SKIPPING, then the one or two most important reasons. "
        f"Be specific — mention the actual numbers. No fluff."
    )

    result = ask_ai(prompt, max_tokens=120)
    if not result:
        park_ok = (stop.get("parking_pct") or 0) > 50
        result = (
            f"{'GOOD STOP' if park_ok else 'WORTH SKIPPING'} — "
            f"Parking at {park}%, shower wait {shwr} min, diesel at {price}."
        )
    return jsonify({"advice": result, "stop_name": stop.get("name", "")})

@app.route("/api/fleet")
def api_fleet():
    """Return fleet summary: all drivers with loyalty data from Databricks."""
    fleet = []
    try:
        from databricks_client import get_driver_loyalty
        # Pull real loyalty data for each driver in our demo fleet
        for d in DRIVERS[:15]:
            loy = get_driver_loyalty(d["id"])
            entry = {
                "id":          d["id"],
                "name":        d["name"],
                "route":       d.get("current_location", "Unknown") + " → " + d.get("destination", "Unknown"),
                "fuel_pct":    min(100, round(d.get("fuel_remaining_miles", 300) / 6)),
                "fuel_miles":  d.get("fuel_remaining_miles", 300),
                "status":      "fuel_risk" if d.get("fuel_remaining_miles", 999) < 150 else "ok",
                "loyalty_tier":  loy["loyalty_tier"]  if loy else d.get("loyalty_tier", "Standard"),
                "total_gallons": loy["total_gallons"]  if loy else 0,
                "total_visits":  loy["total_visits"]   if loy else 0,
            }
            fleet.append(entry)
    except Exception as e:
        print(f"[api_fleet] {e}")
        fleet = [
            {
                "id": d["id"], "name": d["name"],
                "route": d.get("current_location","") + " → " + d.get("destination",""),
                "fuel_pct": min(100, round(d.get("fuel_remaining_miles",300)/6)),
                "fuel_miles": d.get("fuel_remaining_miles", 300),
                "status": "fuel_risk" if d.get("fuel_remaining_miles",999) < 150 else "ok",
                "loyalty_tier": d.get("loyalty_tier","Standard"),
                "total_gallons": 0, "total_visits": 0,
            }
            for d in DRIVERS[:15]
        ]

    at_risk = [f for f in fleet if f["status"] == "fuel_risk"]
    return jsonify({
        "drivers": fleet,
        "summary": {
            "total":    len(fleet),
            "at_risk":  len(at_risk),
            "on_route": len(fleet),
        }
    })

# ── serve SPA ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/logo.svg")
def logo():
    return send_from_directory(_base, "logo.svg")

if __name__ == "__main__":
    print("RoadIQ running at http://localhost:5000")
    port = int(os.getenv("PORT", 5001))
    app.run(debug=True, port=port, host="0.0.0.0")
