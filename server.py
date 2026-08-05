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

# In-memory cache of driver preferences learned via chat + written to Celonis.
# Celonis's trigger_action_flow_Update_Driver_Preferences is write-only in
# practice — there's no reliable read-back (load_data_driver_info's
# firstname/lastname filter doesn't work, see celonis_client.py docstring).
# This cache is what actually feeds /api/plan and /api/ai this session;
# the Celonis write is attempted in parallel so real production data (once
# the read-side bug is fixed) will already be seeded correctly.
_driver_preferences_cache = {}

# ── Bedrock ───────────────────────────────────────────────────────────────────
def _bedrock():
    import botocore.config
    # Auth: AWS_BEARER_TOKEN_BEDROCK env var (Bedrock API key) is picked up
    # automatically by boto3 — no explicit credentials needed. Falls back to
    # standard IAM credential chain (AWS_ACCESS_KEY_ID etc.) if the bearer
    # token isn't set.
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
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


def _extract_and_save_preferences(user_message, driver_id):
    """
    Use Bedrock to detect driver preferences from a chat message.
    Persists via Celonis trigger_action_flow_Update_Driver_Preferences AND
    caches in-process so /api/plan can use it immediately this session.

    Detects: food, shower, preferred stops, avoided stops, typical fuel amount.
    Returns a dict of what was saved, or None if nothing detected.
    """
    extraction_prompt = (
        f"A truck driver said this in chat: \"{user_message}\"\n\n"
        f"Extract any preferences the driver expressed. Respond with ONLY a JSON "
        f"object, no other text:\n"
        f'{{"food_preference": "<text or null>", '
        f'"shower_preference": "<text or null>", '
        f'"preferred_stop": "<stop name/brand they prefer, or null>", '
        f'"avoided_stop": "<stop name/brand they want to avoid, or null>", '
        f'"typical_fuel_gallons": <integer gallons per fill or null>}}\n'
        f"If a field wasn't mentioned, use null. "
        f"Keep extracted text short (under 15 words each)."
    )
    raw = ask_ai(extraction_prompt, max_tokens=120)
    if not raw:
        return None

    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return None
        parsed = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None

    def _val(k):
        v = parsed.get(k)
        if v is None or str(v).lower() in ("null", "none", ""):
            return None
        return v

    food       = _val("food_preference")
    shower     = _val("shower_preference")
    pref_stop  = _val("preferred_stop")
    avoid_stop = _val("avoided_stop")
    fuel_gal   = _val("typical_fuel_gallons")
    if isinstance(fuel_gal, str):
        try:
            fuel_gal = int(float(fuel_gal))
        except (ValueError, TypeError):
            fuel_gal = None

    if not any([food, shower, pref_stop, avoid_stop, fuel_gal]):
        return None

    # Update the in-process cache immediately (this is what /api/plan reads)
    cached = _driver_preferences_cache.setdefault(driver_id, {})
    if food:       cached["food_preference"]      = food
    if shower:     cached["shower_preference"]    = shower
    if pref_stop:  cached["preferred_stop"]       = pref_stop
    if avoid_stop: cached["avoided_stop"]         = avoid_stop
    if fuel_gal:   cached["typical_fuel_gallons"] = fuel_gal

    # Best-effort write to Celonis
    celonis_result = None
    try:
        from celonis_client import celonis_update_driver_preferences
        celonis_result = celonis_update_driver_preferences(
            driver_id=driver_id,
            food_preferences=food,
            shower_preferences=shower,
        )
    except Exception as e:
        print(f"[preferences] Celonis write failed: {e}")

    return {
        "food_preference":      food,
        "shower_preference":    shower,
        "preferred_stop":       pref_stop,
        "avoided_stop":         avoid_stop,
        "typical_fuel_gallons": fuel_gal,
        "celonis_synced":       celonis_result is not None,
    }

# ── Celonis ───────────────────────────────────────────────────────────────────
# Real MCP JSON-RPC client lives in celonis_client.py — this wraps it and
# adapts the field names to what the rest of server.py expects (lat/lng/city/
# state/brand keys), same shape the old code returned.
from celonis_client import celonis_load_locations as _celonis_load_locations

def celonis_stops(from_coords, to_coords):
    try:
        locations = _celonis_load_locations([from_coords, to_coords])
        if not locations:
            return None
        return [
            {
                "lat":   loc["lat"],
                "lng":   loc["lng"],
                "city":  loc["city"],
                "state": loc["state"],
                "brand": loc["brand"],
            }
            for loc in locations
        ]
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
            driver["loyalty_issue_date"] = loyalty.get("issue_date")
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
            f"Driver: {driver['name']}, Elite loyalty member.\n"
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
            f"Driver is James Okafor, Elite member (Push for Points), Nashville→Atlanta, fuel risk at 140mi remaining. "
            f"Answer this question helpfully and concisely (under 80 words): {user_msg}"
        )

    result = ask_ai(prompt)
    if result:
        pref_update = None
        if mode == "chat" and body.get("message"):
            pref_update = _extract_and_save_preferences(body["message"], driver_id=str(DEMO_DRIVER["id"]))
        response_body = {"text": result, "source": "bedrock"}
        if pref_update:
            response_body["preference_update"] = pref_update
        return jsonify(response_body)

    # Fallback
    if mode == "plan":
        fallback = (
            "• Fuel up now — you have ~140 miles left, stop at Pilot Knoxville #198 in ~95 miles.\n"
            "• Parking looks good: 78% available when you arrive (~1.5 hrs).\n"
            "• Shower wait is only 8 min — quick stop before Atlanta.\n"
            "• As an Elite member, you'll earn 2x points on this fill-up. Subway is open inside."
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

    # New journey optimizer inputs
    fuel_pct      = body.get("fuel_pct", 50)          # 0-100 %
    fuel_gal      = body.get("fuel_gal", 75)           # gallons in tank
    fuel_range_mi = body.get("fuel_range_mi", 490)     # miles to empty
    cargo_type    = body.get("cargo_type", "general")  # general/refrigerated/hazmat/oversize/flatbed
    arrive_by     = body.get("arrive_by")              # "YYYY-MM-DD HH:MM" or None

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
        def _loc_to_stop(l):
            return {
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
        # Try corridor bbox first; if still empty, use all local stops
        corridor_stops = [_loc_to_stop(l) for l in LOCATIONS
                          if (min_lat <= l["lat"] <= max_lat and min_lon <= l["lon"] <= max_lon)]
        if not corridor_stops:
            corridor_stops = [_loc_to_stop(l) for l in LOCATIONS]

    # Build optimized stop list — pick 1-3 stops spaced along route
    # Determine number of stops needed based on fuel range and route distance
    # total_miles not yet known here — use a rough estimate for stop count
    rough_miles = round(
        ((from_coords[0] - to_coords[0])**2 + (from_coords[1] - to_coords[1])**2)**0.5 * 69
    )
    # Fuel range from current level; a stop is needed every ~(range * 0.85) miles
    # (0.85 safety buffer — don't run below 15%)
    safe_range = max(fuel_range_mi * 0.85, 100)
    # num_stops_needed is finalized after HOS is resolved below; placeholder here
    num_stops_needed = max(1, int(rough_miles / max(safe_range, 1)))

    if corridor_stops:
        flat, flon = from_coords
        tlat, tlon = to_coords
        dx, dy = tlat - flat, tlon - flon
        length_sq = dx*dx + dy*dy

        def route_progress(stop):
            """0.0 = at origin, 1.0 = at destination. Negative = behind origin."""
            slat, slon = stop.get("lat", 0), stop.get("lon", 0)
            if length_sq == 0:
                return 0.0
            return ((slat - flat)*dx + (slon - flon)*dy) / length_sq

        def perp_distance_deg(stop):
            """Perpendicular distance from the stop to the route line, in degrees."""
            slat, slon = stop.get("lat", 0), stop.get("lon", 0)
            if length_sq == 0:
                return 0.0
            # cross product magnitude / line length
            return abs((slon - flon)*dx - (slat - flat)*dy) / (length_sq ** 0.5)

        # Max deviation: 0.5° ≈ 35 miles either side of the straight-line corridor
        MAX_PERP_DEG = 0.5

        # Drop stops behind origin (t < 0.05) or too far off the corridor
        corridor_stops = [
            s for s in corridor_stops
            if route_progress(s) >= 0.05 and perp_distance_deg(s) <= MAX_PERP_DEG
        ]

        # Sort by position along route first, then quality tier
        corridor_stops.sort(key=lambda s: (
            route_progress(s),
            not s.get("is_pfj", False),
            not s.get("in_network", False),
            not s.get("visited_before", False),
        ))
        chosen = corridor_stops[:num_stops_needed]
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

    # ── HOS (Hours of Service) awareness ──────────────────────────────────────
    # Priority: explicit request override (demo slider) > real Celonis driver
    # data > safe default of 0 hours driven.
    celonis_hos = None
    if "hos_hours_driven" not in body:
        try:
            from celonis_client import get_driver_hos
            first, last = DEMO_DRIVER["name"].split(" ", 1)
            celonis_hos = get_driver_hos(first, last)
        except Exception as e:
            print(f"[plan] Celonis HOS lookup failed: {e}")

    if celonis_hos:
        hos_hours_driven = celonis_hos["hours_worked_today"]
        hos_source = "celonis"
    else:
        hos_hours_driven = float(body.get("hos_hours_driven", 0))
        hos_source = "manual" if "hos_hours_driven" in body else "default"

    hos_remaining  = max(0, 11.0 - hos_hours_driven)
    hos_miles_left = round(hos_remaining * 55)  # avg 55 mph

    # Refine num_stops_needed now that hos_hours_driven is resolved
    hos_drive_miles = hos_remaining * 55
    max_between_stops = min(safe_range, hos_drive_miles) if hos_drive_miles > 0 else safe_range
    num_stops_needed = max(1, int(rough_miles / max(max_between_stops, 1)) + (1 if rough_miles % max(max_between_stops, 1) > 50 else 0))
    num_stops_needed = max(1, min(num_stops_needed, len(corridor_stops) if corridor_stops else 1))
    # Re-slice chosen with the refined count
    if corridor_stops:
        chosen = corridor_stops[:num_stops_needed]

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
            "lat":                s.get("lat"),
            "lon":                s.get("lon"),
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
            "points_multiplier":  2 if DEMO_DRIVER["loyalty_tier"] in ("Platinum", "Elite", "elite", "platinum") else 1,
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

    hos_info = (
        f"HOS: {hos_hours_driven:.1f}h driven today "
        f"({'from Celonis driver log' if hos_source == 'celonis' else hos_source}), "
        f"{hos_remaining:.1f}h remaining on the 11-hour drive limit. "
    )
    if hos_remaining <= 2:
        hos_info += "Driver is APPROACHING the legal HOS limit — a stop is required soon. "

    loyalty_info = ""
    try:
        from databricks_client import get_driver_loyalty
        loy = get_driver_loyalty(7)
        if loy:
            loyalty_info = f"Loyalty: {loy['loyalty_tier']} member, {loy['total_gallons']} lifetime gallons, {loy['total_visits']} visits. "
    except Exception:
        pass

    # Learned preferences (from chat, persisted via Celonis + local cache —
    # see _extract_and_save_preferences). Falls back to the static
    # preferred_food/shower_needed fields from data/drivers.json if nothing
    # has been learned yet this session.
    learned_prefs = _driver_preferences_cache.get(str(DEMO_DRIVER["id"]), {})
    pref_info = ""
    if learned_prefs.get("food_preference"):
        pref_info += f"Learned food preference: {learned_prefs['food_preference']}. "
    if learned_prefs.get("shower_preference"):
        pref_info += f"Learned shower preference: {learned_prefs['shower_preference']}. "
    if learned_prefs.get("preferred_stop"):
        pref_info += f"Driver prefers stopping at: {learned_prefs['preferred_stop']}. "
    if learned_prefs.get("avoided_stop"):
        pref_info += f"Driver wants to avoid: {learned_prefs['avoided_stop']} — do NOT recommend it. "
    if learned_prefs.get("typical_fuel_gallons"):
        pref_info += f"Driver typically fuels {learned_prefs['typical_fuel_gallons']} gallons per stop. "

    # Cross-check chosen stops against Celonis's independent location feed.
    # If Celonis also sees an open, PFJ/in-network location near a chosen
    # stop, that's a second-source corroboration signal worth telling the
    # driver about (higher confidence the stop is real and open right now).
    celonis_corroboration = ""
    try:
        celonis_nearby = _celonis_load_locations([from_coords, to_coords]) or []
        corroborated = sum(1 for c in celonis_nearby if c.get("is_pfj"))
        if corroborated:
            celonis_corroboration = (
                f"Celonis independently confirms {corroborated} open Pilot Flying J "
                f"location(s) along this corridor, corroborating the Databricks data. "
            )
    except Exception as e:
        print(f"[plan] Celonis corroboration check failed: {e}")

    # Build fuel, cargo, and deadline context strings for the prompt
    fuel_info = (
        f"Current fuel level: {fuel_pct}% ({fuel_gal} gal, ~{fuel_range_mi} mi range). "
        f"{'CRITICAL — must fuel before ' + str(round(fuel_range_mi * 0.85)) + ' miles. ' if fuel_pct <= 25 else ''}"
    )

    cargo_notes = {
        "general":      "",
        "refrigerated": "Cargo is REFRIGERATED — prioritize stops with reefer plug-ins or temperature-controlled dock access. ",
        "hazmat":       "Cargo is HAZMAT — only stops with hazmat approval are legal. Flag any routing restrictions. ",
        "oversize":     "Cargo is OVERSIZE — require pull-through parking with sufficient turning radius. Flag any low-clearance routes. ",
        "flatbed":      "Cargo is on a FLATBED — verify stops have open-air parking and tarping area. ",
    }
    cargo_info = cargo_notes.get(cargo_type, "")

    deadline_info = ""
    if arrive_by:
        deadline_info = (
            f"ARRIVAL DEADLINE: driver must arrive in {to_} by {arrive_by}. "
            f"Back-calculate stop timing — if stops would cause a late arrival, flag it and suggest skipping a stop or reducing dwell time. "
        )

    prompt = (
        f"You are RoadIQ, the AI journey optimizer built exclusively for Pilot Flying J. "
        f"You ONLY recommend Pilot Flying J locations — never competitors.\n"
        f"Driver: {DEMO_DRIVER['name']}. {loyalty_info}{pref_info}{hos_info}{fuel_info}"
        f"Route: {from_} to {to_} ({total_miles} miles, {drive_hours} drive). {deadline_info}"
        f"{cargo_info}"
        f"Estimated diesel: {total_gallons} gallons at ${fuel_prices.get('avg_net_price', 'N/A')}/gal fleet price "
        f"(vs ${fuel_prices.get('avg_gross_price', 'N/A')}/gal retail) = estimated {savings_str} savings.\n"
        f"Driver needs: {', '.join(prefs)}.\n"
        f"Optimized Pilot Flying J stops ({len(stops_out)} stop{'s' if len(stops_out)!=1 else ''} based on fuel range and HOS):\n{stops_text}\n"
        f"{celonis_corroboration}\n\n"
        f"Write a friendly 3-4 sentence journey briefing for James. "
        f"Highlight the Pilot Flying J stop(s), fleet pricing savings, loyalty benefit, and any HOS or fuel timing advice. "
        f"If there's a deadline, confirm whether the plan meets it. If cargo has restrictions, note them briefly. "
        f"Never mention competitors. No bullet points — flowing sentences. Under 130 words."
    )

    ai_plan = ask_ai(prompt, max_tokens=200)
    if not ai_plan:
        ai_plan = (
            f"Your {total_miles}-mile route from {from_} to {to_} has been optimized with "
            f"{len(stops_out)} Pilot stop{'s' if len(stops_out)!=1 else ''}. "
            f"As an Elite member (Push for Points) you'll earn 2x points on every fill-up, "
            f"and fleet pricing saves you an estimated {savings_str} on this trip. "
            f"Stops were chosen for parking availability and shower wait times."
        )

    # Build all_stops — every corridor stop with enrichment (not just chosen 2)
    all_stops_out = []
    for s in corridor_stops:
        lob_id = s.get("lob_id")
        park_info   = parking_data.get(lob_id, {})
        shower_info = shower_data.get(lob_id, {})
        is_chosen   = any(
            (lob_id and c.get("lob_id") == lob_id) or
            c.get("name") == s.get("name")
            for c in chosen
        )
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
            "hours_driven":    hos_hours_driven,
            "hours_remaining": hos_remaining,
            "miles_remaining": hos_miles_left,
            "source":          hos_source,  # "celonis" | "manual" | "default"
        },
        "ai_plan":       ai_plan,
        "fuel_prices":   fuel_prices,
        "offers":        driver_offers or [],
        "journey_context": {
            "fuel_pct":      fuel_pct,
            "fuel_gal":      fuel_gal,
            "fuel_range_mi": fuel_range_mi,
            "cargo_type":    cargo_type,
            "arrive_by":     arrive_by,
            "num_stops_needed": num_stops_needed,
        },
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

# ── Maintenance data (synthetic — would come from telematics in production) ───
import random, hashlib

def _maintenance_for_driver(driver_id):
    """Generate deterministic synthetic maintenance data keyed on driver_id."""
    h = int(hashlib.md5(str(driver_id).encode()).hexdigest(), 16)
    def pick(seed, lo, hi):
        return lo + (seed % (hi - lo + 1))

    def_pct   = pick(h >> 0,  8, 95)
    tire_psi  = pick(h >> 4, 88, 115)   # % of nominal; below 95 = low
    oil_life  = pick(h >> 8, 10, 100)
    miles_to_service = pick(h >> 12, 200, 28000)

    alerts = []
    if def_pct < 20:
        alerts.append({"type": "DEF", "severity": "critical",
                        "msg": f"DEF critically low — {def_pct}% remaining"})
    elif def_pct < 40:
        alerts.append({"type": "DEF", "severity": "warning",
                        "msg": f"DEF low — {def_pct}% remaining, refill at next stop"})

    if tire_psi < 92:
        alerts.append({"type": "TIRES", "severity": "warning",
                        "msg": f"Tire pressure at {tire_psi}% of nominal — inspect at next stop"})

    if oil_life < 15:
        alerts.append({"type": "OIL", "severity": "critical",
                        "msg": f"Oil life critical — {oil_life}% remaining, service needed"})
    elif oil_life < 30:
        alerts.append({"type": "OIL", "severity": "warning",
                        "msg": f"Oil life at {oil_life}% — schedule service soon"})

    if miles_to_service < 1000:
        alerts.append({"type": "SERVICE", "severity": "warning",
                        "msg": f"Scheduled service due in {miles_to_service:,} miles"})

    return {
        "def_pct":           def_pct,
        "tire_psi_pct":      tire_psi,
        "oil_life_pct":      oil_life,
        "miles_to_service":  miles_to_service,
        "alerts":            alerts,
        "has_critical":      any(a["severity"] == "critical" for a in alerts),
        "has_warning":       len(alerts) > 0,
    }

@app.route("/api/maintenance")
def api_maintenance():
    """Return maintenance status for all fleet drivers."""
    driver_id = request.args.get("driver_id")
    if driver_id:
        return jsonify(_maintenance_for_driver(int(driver_id)))
    return jsonify({str(d["id"]): _maintenance_for_driver(d["id"]) for d in DRIVERS[:15]})


# ── Nearby POI via Overpass (OpenStreetMap) ───────────────────────────────────
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Each value is a valid Overpass QL union body (nodes + ways) for the category
_POI_QUERIES = {
    "food": (
        "node['amenity'='restaurant'](around:{r},{lat},{lon});"
        "node['amenity'='fast_food'](around:{r},{lat},{lon});"
        "node['amenity'='food_court'](around:{r},{lat},{lon});"
    ),
    "cafe": (
        "node['amenity'='cafe'](around:{r},{lat},{lon});"
        "node['amenity'='coffee_shop'](around:{r},{lat},{lon});"
    ),
    "gym": (
        "node['leisure'='fitness_centre'](around:{r},{lat},{lon});"
        "node['leisure'='sports_centre'](around:{r},{lat},{lon});"
        "node['amenity'='gym'](around:{r},{lat},{lon});"
        "way['leisure'='fitness_centre'](around:{r},{lat},{lon});"
    ),
    "park": (
        "node['leisure'='park'](around:{r},{lat},{lon});"
        "node['leisure'='nature_reserve'](around:{r},{lat},{lon});"
        "way['leisure'='park'](around:{r},{lat},{lon});"
    ),
    "library": (
        "node['amenity'='library'](around:{r},{lat},{lon});"
        "way['amenity'='library'](around:{r},{lat},{lon});"
    ),
    "cinema": (
        "node['amenity'='cinema'](around:{r},{lat},{lon});"
        "way['amenity'='cinema'](around:{r},{lat},{lon});"
    ),
    "mall": (
        "node['shop'='mall'](around:{r},{lat},{lon});"
        "way['shop'='mall'](around:{r},{lat},{lon});"
        "node['shop'='department_store'](around:{r},{lat},{lon});"
    ),
    "bowling": (
        "node['leisure'='bowling_alley'](around:{r},{lat},{lon});"
        "node['leisure'='amusement_arcade'](around:{r},{lat},{lon});"
        "way['leisure'='bowling_alley'](around:{r},{lat},{lon});"
    ),
    "laundry": (
        "node['shop'='laundry'](around:{r},{lat},{lon});"
        "node['amenity'='laundry'](around:{r},{lat},{lon});"
    ),
    "pharmacy": (
        "node['amenity'='pharmacy'](around:{r},{lat},{lon});"
        "way['amenity'='pharmacy'](around:{r},{lat},{lon});"
    ),
}

# Demo fallback — realistic places found near US interstate truck stops
_DEMO_FALLBACK = {
    "food": [
        {"name": "Cracker Barrel", "dist_m": 400, "lat": 0, "lon": 0},
        {"name": "Waffle House", "dist_m": 650, "lat": 0, "lon": 0},
        {"name": "Denny's", "dist_m": 900, "lat": 0, "lon": 0},
    ],
    "cafe": [
        {"name": "Starbucks", "dist_m": 300, "lat": 0, "lon": 0},
        {"name": "Dunkin'", "dist_m": 550, "lat": 0, "lon": 0},
    ],
    "gym": [
        {"name": "Planet Fitness", "dist_m": 1800, "lat": 0, "lon": 0},
    ],
    "mall": [
        {"name": "Walmart Supercenter", "dist_m": 1200, "lat": 0, "lon": 0},
        {"name": "Dollar General", "dist_m": 700, "lat": 0, "lon": 0},
    ],
    "library": [
        {"name": "Knox County Public Library", "dist_m": 2100, "lat": 0, "lon": 0},
    ],
    "laundry": [
        {"name": "Laundromat", "dist_m": 950, "lat": 0, "lon": 0},
    ],
}


def _overpass_poi(lat, lon, radius_m=8000):
    """Query Overpass for POIs within radius_m metres of lat/lon."""
    results = {}
    any_success = False
    for cat, body_tmpl in _POI_QUERIES.items():
        body = body_tmpl.format(r=radius_m, lat=lat, lon=lon)
        query = f"[out:json][timeout:12];({body});out center 6;"
        try:
            r = requests.post(_OVERPASS_URL, data={"data": query}, timeout=15, verify=False)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            places = []
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name", "").strip()
                if not name:
                    continue
                # ways return center lat/lon; nodes return lat/lon directly
                el_lat = el.get("lat") or (el.get("center") or {}).get("lat")
                el_lon = el.get("lon") or (el.get("center") or {}).get("lon")
                if el_lat is None:
                    continue
                dist_m = round(((el_lat - lat) ** 2 + (el_lon - lon) ** 2) ** 0.5 * 111000)
                places.append({"name": name, "dist_m": dist_m, "lat": el_lat, "lon": el_lon})
            if places:
                any_success = True
                results[cat] = sorted(places, key=lambda x: x["dist_m"])[:4]
            print(f"[poi:{cat}] {len(places)} results at ({lat},{lon}) r={radius_m}m")
        except Exception as e:
            print(f"[poi:{cat}] error: {e}")

    # If Overpass returned nothing at all (proxy blocked or truly empty area), use demo data
    if not any_success:
        print("[poi] Overpass returned 0 results — using demo fallback")
        return {**_DEMO_FALLBACK, "_fallback": True}
    return results


@app.route("/api/poi", methods=["POST"])
def api_poi():
    """Return nearby POI for a rest stop location."""
    body   = request.json or {}
    lat    = body.get("lat")
    lon    = body.get("lon")
    radius = int(body.get("radius_m", 8000))
    if lat is None or lon is None:
        return jsonify({"error": "lat/lon required"}), 400
    poi = _overpass_poi(float(lat), float(lon), radius)
    return jsonify({"lat": lat, "lon": lon, "radius_m": radius, "poi": poi})


# ── Weather along route (Open-Meteo — free, no API key) ──────────────────────
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

def _weather_icon(code):
    """WMO weather code → emoji."""
    if code == 0: return "☀️"
    if code in (1, 2): return "🌤️"
    if code == 3: return "☁️"
    if code in (45, 48): return "🌫️"
    if code in (51, 53, 55, 61, 63): return "🌧️"
    if code == 65: return "🌧️"
    if code in (71, 73, 75, 77): return "❄️"
    if code in (80, 81, 82): return "🌦️"
    if code in (95, 96, 99): return "⛈️"
    return "🌡️"

def _weather_severity(wind_kmh, precip_mm, code):
    """Return 'ok' | 'caution' | 'severe'."""
    if wind_kmh > 60 or code in (95, 96, 99) or precip_mm > 10: return "severe"
    if wind_kmh > 40 or code in (71, 73, 75) or precip_mm > 3: return "caution"
    return "ok"

@app.route("/api/weather", methods=["POST"])
def api_weather():
    """
    Accepts {route_coords: [[lat,lon],...]} — samples up to 5 points along route,
    fetches Open-Meteo current + next-12h forecast per point.
    Returns list of {lat, lon, label, icon, temp_f, wind_mph, precip_in, severity, description}.
    """
    body = request.json or {}
    coords = body.get("route_coords", [])
    if not coords:
        return jsonify({"error": "route_coords required"}), 400

    # Sample 5 evenly-spaced points (origin, 25%, 50%, 75%, destination)
    n = len(coords)
    indices = [0, n//4, n//2, 3*n//4, n-1] if n >= 5 else list(range(n))
    labels  = ["Origin", "25% mark", "Midpoint", "75% mark", "Destination"]

    points = []
    for i, idx in enumerate(indices):
        lat, lon = coords[idx][0], coords[idx][1]
        try:
            r = requests.get(_WEATHER_URL, params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,precipitation,weather_code",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "forecast_days": 1,
            }, timeout=8, verify=False)
            r.raise_for_status()
            c = r.json().get("current", {})
            temp   = round(c.get("temperature_2m", 0))
            wind   = round(c.get("wind_speed_10m", 0))
            precip = round(c.get("precipitation", 0), 2)
            code   = c.get("weather_code", 0)
            # convert wind mph→kmh for severity calc
            wind_kmh = wind * 1.609
            precip_mm = precip * 25.4
            sev = _weather_severity(wind_kmh, precip_mm, code)
            icon = _weather_icon(code)
            if sev == "severe":
                desc = f"Severe conditions — {wind}mph winds"
            elif sev == "caution":
                desc = f"Use caution — {wind}mph winds{', light precip' if precip > 0 else ''}"
            else:
                desc = f"Clear driving conditions"
            points.append({
                "lat": lat, "lon": lon,
                "label": labels[i],
                "icon": icon,
                "temp_f": temp,
                "wind_mph": wind,
                "precip_in": precip,
                "severity": sev,
                "description": desc,
            })
        except Exception as e:
            print(f"[weather] point {i} failed: {e}")
            points.append({
                "lat": lat, "lon": lon, "label": labels[i],
                "icon": "🌡️", "temp_f": 72, "wind_mph": 10,
                "precip_in": 0, "severity": "ok", "description": "Weather unavailable",
            })

    worst = "severe" if any(p["severity"] == "severe" for p in points) \
            else "caution" if any(p["severity"] == "caution" for p in points) \
            else "ok"
    return jsonify({"points": points, "overall_severity": worst})


# ── Load assignment board ─────────────────────────────────────────────────────
LOADS = [
    {"id": "L001", "origin": "Nashville, TN", "destination": "Atlanta, GA",
     "cargo": "General Freight", "miles": 248, "pickup": "08:00", "deliver_by": "16:00",
     "priority": "standard", "assigned_driver": None},
    {"id": "L002", "origin": "Memphis, TN", "destination": "Charlotte, NC",
     "cargo": "Refrigerated", "miles": 541, "pickup": "06:00", "deliver_by": "20:00",
     "priority": "high", "assigned_driver": None},
    {"id": "L003", "origin": "Louisville, KY", "destination": "Atlanta, GA",
     "cargo": "Hazmat — Fuel", "miles": 427, "pickup": "07:30", "deliver_by": "18:00",
     "priority": "high", "assigned_driver": None},
    {"id": "L004", "origin": "Cincinnati, OH", "destination": "Tampa, FL",
     "cargo": "Auto Parts", "miles": 832, "pickup": "05:00", "deliver_by": "23:00",
     "priority": "standard", "assigned_driver": None},
    {"id": "L005", "origin": "Indianapolis, IN", "destination": "Birmingham, AL",
     "cargo": "Consumer Goods", "miles": 483, "pickup": "09:00", "deliver_by": "21:00",
     "priority": "standard", "assigned_driver": None},
]
# In-memory assignment state — {load_id: {"driver_id": ..., "driver_name": ...} | None}
_load_assignments = {l["id"]: None for l in LOADS}

@app.route("/api/loads")
def api_loads():
    loads = []
    for l in LOADS:
        entry = dict(l)
        assignment = _load_assignments.get(l["id"])
        if assignment:
            entry["assigned_driver"] = assignment["driver_id"]
            entry["driver_name"] = assignment["driver_name"]
        else:
            entry["assigned_driver"] = None
        loads.append(entry)
    return jsonify({"loads": loads})

@app.route("/api/loads/assign", methods=["POST"])
def api_loads_assign():
    body = request.json or {}
    load_id     = body.get("load_id")
    driver_id   = body.get("driver_id")
    driver_name = body.get("driver_name", "")
    if not load_id or load_id not in _load_assignments:
        return jsonify({"error": "invalid load_id"}), 400
    if driver_id:
        _load_assignments[load_id] = {"driver_id": driver_id, "driver_name": driver_name}
    else:
        _load_assignments[load_id] = None  # unassign
    return jsonify({"load_id": load_id, "driver_id": driver_id,
                    "driver_name": driver_name, "ok": True})


# ── Competitor stops along corridor ───────────────────────────────────────────
@app.route("/api/competitors")
def api_competitors():
    """
    Demo competitor truck stops along Nashville→Atlanta (I-24/I-75 corridor).
    Prices are representative retail diesel — updated to reflect realistic spread
    vs Pilot fleet pricing. Each competitor entry includes the nearest Pilot stop
    and what Pilot offers that the competitor does not.
    """
    try:
        from databricks_client import get_fuel_prices
        pilot_fleet = get_fuel_prices().get("avg_net_price") or 3.448
        pilot_retail = get_fuel_prices().get("avg_gross_price") or 3.545
    except Exception:
        pilot_fleet  = 3.448
        pilot_retail = 3.545

    competitors = [
        {
            "id": "loves_manchester",
            "brand": "Love's",
            "name": "Love's Travel Stop #423",
            "city": "Manchester", "state": "TN",
            "mile_marker": 110,
            "diesel_price": round(pilot_retail + 0.08, 3),  # ~$0.08 above Pilot retail
            "amenities": ["Subway", "Parking", "Showers", "CAT Scale"],
            "missing_vs_pilot": ["Fleet pricing", "MyRewards points", "2x loyalty multiplier", "Mobile fueling"],
            "nearest_pilot": {
                "name": "Pilot Cookeville #241",
                "city": "Cookeville, TN",
                "miles_away": 12,
                "diesel_price": pilot_fleet,
                "perks": ["Fleet price saves $0.18/gal vs Love's", "2× MyRewards points", "Pilot Coffee", "Shower in 8 min avg"],
            },
        },
        {
            "id": "ta_petro_chattanooga",
            "brand": "TA Petro",
            "name": "TA Petro #187",
            "city": "Chattanooga", "state": "TN",
            "mile_marker": 175,
            "diesel_price": round(pilot_retail + 0.12, 3),  # ~$0.12 above Pilot retail
            "amenities": ["Iron Skillet", "Parking", "Showers", "Laundry"],
            "missing_vs_pilot": ["Fleet pricing", "Loyalty program", "Mobile app offers", "CAT Scale"],
            "nearest_pilot": {
                "name": "Pilot Chattanooga #198",
                "city": "Chattanooga, TN",
                "miles_away": 4,
                "diesel_price": pilot_fleet,
                "perks": [f"Fleet price saves ${round(pilot_retail+0.12-pilot_fleet,2)}/gal vs TA", "Active offer: $29 bonus points", "CAT Scale on-site", "78% parking available"],
            },
        },
        {
            "id": "bp_calhoun",
            "brand": "BP",
            "name": "BP Truck Plaza",
            "city": "Calhoun", "state": "GA",
            "mile_marker": 312,
            "diesel_price": round(pilot_retail + 0.05, 3),
            "amenities": ["Hot food", "Parking"],
            "missing_vs_pilot": ["Fleet pricing", "Showers", "Loyalty rewards", "CAT Scale", "Mobile fueling"],
            "nearest_pilot": {
                "name": "Pilot Calhoun #312",
                "city": "Calhoun, GA",
                "miles_away": 2,
                "diesel_price": pilot_fleet,
                "perks": [f"Fleet price saves ${round(pilot_retail+0.05-pilot_fleet,2)}/gal vs BP", "Full-service showers", "MyRewards 2× points", "DoorDash delivery inside"],
            },
        },
    ]

    pilot_advantage = round(
        sum(c["diesel_price"] - pilot_fleet for c in competitors) / len(competitors), 3
    )

    return jsonify({
        "competitors": competitors,
        "pilot_fleet_price": pilot_fleet,
        "avg_competitor_price": round(sum(c["diesel_price"] for c in competitors) / len(competitors), 3),
        "avg_pilot_advantage": pilot_advantage,
    })


# ── Fleet savings vs competitor benchmark ─────────────────────────────────────
@app.route("/api/fleet_savings")
def api_fleet_savings():
    """
    Compare Pilot fleet price vs national average diesel benchmark.
    Returns per-driver and fleet-total weekly savings estimate.
    """
    NATIONAL_AVG = 3.689  # $/gal national average diesel benchmark
    WEEKLY_GALLONS_PER_DRIVER = 180  # average for long-haul
    try:
        from databricks_client import get_fuel_prices
        prices = get_fuel_prices()
        pilot_price = prices.get("avg_net_price") or 3.448
    except Exception:
        pilot_price = 3.448

    per_gal_savings = round(NATIONAL_AVG - pilot_price, 3)
    per_driver_weekly = round(per_gal_savings * WEEKLY_GALLONS_PER_DRIVER, 2)
    fleet_weekly = round(per_driver_weekly * 15, 2)
    fleet_annual = round(fleet_weekly * 52, 0)

    return jsonify({
        "pilot_price":        round(pilot_price, 3),
        "benchmark_price":    NATIONAL_AVG,
        "per_gal_savings":    per_gal_savings,
        "weekly_gal_per_driver": WEEKLY_GALLONS_PER_DRIVER,
        "per_driver_weekly":  per_driver_weekly,
        "fleet_size":         15,
        "fleet_weekly":       fleet_weekly,
        "fleet_annual":       int(fleet_annual),
        "benchmark_label":    "National avg diesel",
    })


# ── serve SPA ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/logo.svg")
def logo():
    return send_from_directory(_base, "logo.svg")


# ── Return load opportunities ──────────────────────────────────────────────────
# Simulates a load board query seeded from the driver's current destination.
# In production this would pull from a TMS/load-board API (e.g. DAT, Truckstop).
# Key insight: we can show NET earnings = gross rate − Pilot fuel cost on the
# return lane, which only RoadIQ can calculate accurately.

_RETURN_LOADS = [
    {
        "id": "RL001", "origin": "Atlanta, GA", "destination": "Nashville, TN",
        "cargo": "Consumer Goods", "miles": 248,
        "gross_rate": 920, "fuel_gal": 37, "window_closes_min": 180,
        "urgency": "high", "loads_competing": 4,
    },
    {
        "id": "RL002", "origin": "Atlanta, GA", "destination": "Charlotte, NC",
        "cargo": "Auto Parts", "miles": 244,
        "gross_rate": 1040, "fuel_gal": 36, "window_closes_min": 340,
        "urgency": "medium", "loads_competing": 2,
    },
    {
        "id": "RL003", "origin": "Atlanta, GA", "destination": "Memphis, TN",
        "cargo": "Refrigerated", "miles": 393,
        "gross_rate": 1480, "fuel_gal": 59, "window_closes_min": 480,
        "urgency": "low", "loads_competing": 7,
    },
]

@app.route("/api/return_loads")
def api_return_loads():
    """
    Returns ranked return-load opportunities from the driver's current
    destination, with net earnings calculated using real Pilot fuel prices.
    """
    from databricks_client import get_fuel_prices
    try:
        fp = get_fuel_prices()
        pilot_price = fp.get("avg_net_price") or fp.get("avg_gross_price") or 3.45
    except Exception:
        pilot_price = 3.45

    results = []
    for load in _RETURN_LOADS:
        fuel_cost = round(load["fuel_gal"] * pilot_price, 2)
        net_earn  = round(load["gross_rate"] - fuel_cost, 2)
        cpm       = round(load["gross_rate"] / load["miles"], 2)  # cents per mile (gross)
        net_cpm   = round(net_earn / load["miles"], 2)
        results.append({
            **load,
            "pilot_price_per_gal": round(pilot_price, 3),
            "pilot_fuel_cost":     fuel_cost,
            "net_earnings":        net_earn,
            "gross_cpm":           cpm,
            "net_cpm":             net_cpm,
        })

    # Sort by net earnings descending
    results.sort(key=lambda x: x["net_earnings"], reverse=True)

    # Opportunity cost: best load's net_cpm × typical dwell minutes
    best = results[0]
    opp_cost_per_hour = round(best["net_cpm"] * best["miles"] / (best["miles"] / 55), 2)

    return jsonify({
        "loads": results,
        "pilot_price": round(pilot_price, 3),
        "opportunity_cost_per_hour": opp_cost_per_hour,
        "best_window_closes_min": best["window_closes_min"],
    })

@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(_base, filename)

@app.route("/tiles/<int:z>/<int:x>/<int:y>.png")
def proxy_tile(z, x, y):
    """Proxy OSM tiles through Flask so corporate network / SSL issues don't block the browser."""
    import urllib.request, ssl
    ctx = ssl._create_unverified_context()
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RoadIQ/1.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            data = resp.read()
        return app.response_class(data, status=200, mimetype="image/png",
                                  headers={"Cache-Control": "public,max-age=86400"})
    except Exception:
        # Return a 1x1 transparent PNG so the map doesn't hang on missing tiles
        import base64
        empty = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        return app.response_class(empty, status=200, mimetype="image/png")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5002))
    print(f"RoadIQ running at http://localhost:{port}")
    app.run(debug=True, port=port, host="0.0.0.0")
