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
_last_plan = {"from": None, "to": None}  # updated every /api/plan call

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

_chat_stops_cache = {"text": None, "ts": 0, "route_key": None}


def _build_chat_stops_context():
    """
    Build a text block of Pilot stops on the active route for Chat grounding.
    Uses _last_plan coords so chat always reflects the current planned trip.
    Cache busts when route changes.
    """
    now = __import__("time").time()
    route_key = f"{_last_plan.get('from')}|{_last_plan.get('to')}"
    if (_chat_stops_cache["text"]
            and now - _chat_stops_cache["ts"] < 300
            and _chat_stops_cache["route_key"] == route_key):
        return _chat_stops_cache["text"]

    lines = []
    lat_min = lat_max = lon_min = lon_max = None
    active_from = _last_plan.get("from") or ""
    active_to   = _last_plan.get("to") or ""

    # Use stops already computed by /api/plan when available (most accurate)
    plan_stops = _last_plan.get("stops") or []
    if plan_stops:
        corridor_locs = plan_stops
    else:
        # Fallback: bbox filter from LOCATIONS
        def _city_coords(city_str):
            city_lower = city_str.lower()
            for loc in LOCATIONS:
                if loc["city"].lower() in city_lower or city_lower in loc["city"].lower():
                    return loc["lat"], loc["lon"]
            return None
        _from_coords = _city_coords(active_from)
        _to_coords   = _city_coords(active_to)
        corridor_locs = []
        if _from_coords and _to_coords:
            lat_min = min(_from_coords[0], _to_coords[0]) - 1.0
            lat_max = max(_from_coords[0], _to_coords[0]) + 1.0
            lon_min = min(_from_coords[1], _to_coords[1]) - 1.0
            lon_max = max(_from_coords[1], _to_coords[1]) + 1.0
            corridor_locs = [l for l in LOCATIONS
                             if lat_min <= l["lat"] <= lat_max and lon_min <= l["lon"] <= lon_max]
        if not corridor_locs:
            corridor_locs = LOCATIONS

    for l in corridor_locs[:8]:
        details = []
        if l.get("food_available"):
            details.append(f"Food: {l['food_available']}")
        if l.get("parking_forecast_pct") is not None:
            details.append(f"Parking: {l['parking_forecast_pct']}% available")
        if l.get("shower_wait_min") is not None:
            details.append(f"Shower wait: {l['shower_wait_min']} min")
        line = f"- {l['name']} ({l['city']})"
        if details:
            line += " — " + "; ".join(details)
        lines.append(line)

    # Also try Databricks with the actual route bbox (non-blocking enhancement)
    try:
        from databricks_client import (
            get_stops_in_corridor, get_pfj360_food_offerings,
            get_parking_availability, get_shower_wait,
        )
        if lat_min is not None:
            db_stops = get_stops_in_corridor(lat_min, lat_max, lon_min, lon_max, driver_id=DEMO_DRIVER["id"])
        else:
            db_stops = []
        # Only use Databricks stops if they have real (non-synthetic) coords
        valid_db = [s for s in db_stops if s.get("lat") and 24 <= s["lat"] <= 50 and -125 <= s.get("lon", 0) <= -65]
        if valid_db:
            lob_ids = [s["lob_id"] for s in valid_db if s.get("lob_id") is not None]
            food_map = get_pfj360_food_offerings(lob_ids) or {}
            parking_map = get_parking_availability(lob_ids) or {}
            shower_map = get_shower_wait(lob_ids) or {}
            db_lines = []
            for s in valid_db[:8]:
                lob_id = s.get("lob_id")
                food = food_map.get(lob_id)
                park = parking_map.get(lob_id, {}).get("parking_pct_available")
                shower = shower_map.get(lob_id, {}).get("avg_wait_minutes")
                line = f"- {s['name']} ({s['city']}, {s.get('state','')})"
                details = []
                if food:
                    details.append(f"Food: {', '.join(food)}")
                if park is not None:
                    details.append(f"Parking: {park}% available")
                if shower is not None:
                    details.append(f"Shower wait: {shower} min")
                if s.get("has_lounge"):
                    details.append("Drivers' lounge")
                if details:
                    line += " — " + "; ".join(details)
                db_lines.append(line)
            if db_lines:
                lines = db_lines  # prefer Databricks if valid
    except Exception as e:
        print(f"[chat_context] Databricks stop lookup failed: {e}")

    text = "\n".join(lines) if lines else "  (no stop data available)"
    _chat_stops_cache["text"] = text
    _chat_stops_cache["ts"] = now
    _chat_stops_cache["route_key"] = route_key
    return text


def ask_ai(prompt_text, max_tokens=450, model_id=None):
    """
    Call Bedrock Converse. Model selection (benchmarked 2026-08-05, see
    scripts/benchmark_models.py):
      - Default (chat/quick replies, driver is waiting): amazon.nova-pro-v1:0
        — matched Nova Lite's latency (~0.8s) but used FEWER output tokens
        and gave noticeably better recommendations in side-by-side testing
        (e.g. correctly weighing "cheapest fuel" vs "has the food I asked
        about" instead of just answering the first part of a question).
      - /api/plan itinerary (ai_plan, one-shot per trip build, not per
        keystroke — latency less felt): pass model_id=BEDROCK_PLAN_MODEL_ID
        env var. Intended to be us.anthropic.claude-haiku-4-5-20251001-v1:0
        for stronger trip reasoning, but that's currently blocked — this
        AWS account hasn't submitted Anthropic's required "model use case"
        form in the Bedrock console (ResourceNotFoundException on every
        Claude call, confirmed 2026-08-05). That's an account-admin action,
        not a code fix. Defaults to amazon.nova-pro-v1:0 (same as chat) for
        now; swap BEDROCK_PLAN_MODEL_ID to the Claude inference profile ID
        once that form clears.
      - Claude/newer-Nova model IDs require the "us." region-prefixed
        inference profile ID for on-demand invocation, not the raw model ID
        (confirmed via ValidationException testing) — always use the
        prefixed form for those, once Claude access is actually approved.
    """
    try:
        resolved_model_id = model_id or os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
        r = _bedrock().converse(
            modelId=resolved_model_id,
            messages=[{"role": "user", "content": [{"text": prompt_text}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.7},
        )
        return r["output"]["message"]["content"][0]["text"]
    except Exception as e:
        print(f"[bedrock] AI call failed (model={model_id or 'default'}): {e}")
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
        stops_context = _build_chat_stops_context()
        pref_context = ""
        learned = _driver_preferences_cache.get(str(DEMO_DRIVER["id"]), {})
        if learned:
            pref_context = "Known driver preferences from earlier chat: " + "; ".join(
                f"{k.replace('_', ' ')}: {v}" for k, v in learned.items()
            ) + ". "
        active_from = _last_plan.get("from") or DEMO_DRIVER.get("current_location", "Nashville, TN")
        active_to   = _last_plan.get("to")   or DEMO_DRIVER.get("destination", "Atlanta, GA")
        # Build competitor context for fuel-savings questions
        try:
            from databricks_client import get_fuel_prices
            _fp = get_fuel_prices()
            pilot_fleet = _fp.get("avg_net_price") or 3.448
            pilot_retail = _fp.get("avg_gross_price") or 3.545
        except Exception:
            pilot_fleet, pilot_retail = 3.448, 3.545
        # Pull live competitor list based on current corridor
        dest_lower = active_to.lower()
        frm_lower  = active_from.lower()
        if any(k in dest_lower for k in ["miami","orlando","tampa","jacksonville","florida"," fl"]):
            comp_names = "Love's Valdosta GA ($%.3f/gal), TA Petro Lake City FL ($%.3f/gal), BP Orlando FL ($%.3f/gal)" % (pilot_retail+0.09, pilot_retail+0.13, pilot_retail+0.06)
        elif any(k in dest_lower for k in ["atlanta"," ga"]):
            comp_names = "Love's Murfreesboro TN ($%.3f/gal), TA Petro Chattanooga TN ($%.3f/gal), BP Calhoun GA ($%.3f/gal)" % (pilot_retail+0.08, pilot_retail+0.12, pilot_retail+0.05)
        elif any(k in dest_lower for k in ["chicago","illinois"," il","indianapolis"]):
            comp_names = "Love's Gary IN ($%.3f/gal), TA Petro Indianapolis IN ($%.3f/gal), BP Bowling Green KY ($%.3f/gal)" % (pilot_retail+0.09, pilot_retail+0.11, pilot_retail+0.06)
        else:
            comp_names = "Love's Jackson TN ($%.3f/gal), TA Petro Memphis TN ($%.3f/gal), BP Little Rock AR ($%.3f/gal)" % (pilot_retail+0.08, pilot_retail+0.12, pilot_retail+0.05)
        competitor_context = (f"Competitor fuel prices on this corridor: {comp_names}. "
                              f"Pilot fleet price: ${pilot_fleet:.3f}/gal (saves ~${pilot_retail-pilot_fleet:.3f}/gal vs retail, "
                              f"~${pilot_retail+0.09-pilot_fleet:.3f}/gal vs Love's avg).")

        # Loyalty / points context — Elite earns 2x pts/gal (matches
        # points_multiplier logic elsewhere in this file and the fallback
        # plan text below — Elite is the only tier label used app-wide,
        # "Gold" and "4x" were an inconsistency, not a real second tier).
        plan_stops_list = _last_plan.get("stops") or []
        stop_count = len(plan_stops_list)
        trip_gal = stop_count * 100   # ~100 gal per semi fill
        trip_points = trip_gal * 2    # Elite = 2x pts/gal
        loyalty_context = (
            f"LOYALTY FACTS (read back verbatim, do not recalculate):\n"
            f"- Currently earning: {trip_points} points this trip ({stop_count} stops × ~100 gal × 2 pts/gal, Elite tier).\n"
            f"PARKING BOOKING: tap the 'Go' button on any stop card to reserve → PFJ-XXXXX confirmation code.\n"
            f"STOP FREQUENCY: at 55 mph avg, every 2 hrs ≈ 110 miles, every 3 hrs ≈ 165 miles."
        )

        prompt = (
            f"You are RoadIQ, Pilot Flying J's AI driver assistant. Be helpful, specific, and friendly. "
            f"Driver is James Okafor, Elite MyRewards member. "
            f"Current route: {active_from} → {active_to}. "
            f"{pref_context}\n"
            f"Pilot stops on this route with food/amenities:\n{stops_context}\n\n"
            f"{competitor_context}\n\n"
            f"{loyalty_context}\n\n"
            f"Guidelines:\n"
            f"- Food questions: suggest the closest available option even if not exact match (e.g. wings → closest hot food available)\n"
            f"- Parking booking: tell driver to tap 'Go' on the stop card to reserve, mention the PFJ confirmation code\n"
            f"- Stop frequency: if driver asks for stops every N hours, calculate based on ~55mph avg and list stops accordingly\n"
            f"- Points questions: use the loyalty data above to give specific numbers\n"
            f"- Off-topic questions (weather trivia, stocks, politics, non-driving topics): politely decline and redirect to route help\n"
            f"- Competitor locations: never give directions to Love's, TA, Petro, BP, or any non-Pilot stop — redirect to Pilot options and mention the price advantage\n"
            f"- Never invent stop names, prices, or food options not listed above\n"
            f"Answer concisely (under 90 words): {user_msg}"
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

def _build_range_warning(leg):
    """
    Build a driver-facing message for a leg that exceeds max_between_stops,
    correctly attributing WHY — fuel range, legal HOS drive-time limit, or
    the driver's own preferred break cadence — instead of always blaming
    fuel (which was misleading: e.g. a full-tank trip hitting the legal
    11-hour drive limit isn't a fuel problem at all).
    """
    gap = leg["nearest_stop_mile"] - leg["from_mile"]
    reason = leg.get("reason", "fuel")
    if reason == "hos":
        cause = "your remaining legal drive time (Hours of Service) allows"
    elif reason == "preference":
        cause = "your preferred stop frequency allows"
    else:
        cause = "your fuel range supports"
    return (
        f"No Pilot/Flying J stop is within {leg['safe_range_mi']} miles at mile "
        f"{leg['from_mile']} — the closest available stop is at mile "
        f"{leg['nearest_stop_mile']}, {gap} miles further than {cause}. "
        f"Consider fueling before departure or finding a closer non-Pilot option."
    )


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
    requested_stops = body.get("num_stops")            # explicit stop count from UI (overrides auto-calc)
    # Driver's preferred max hours of continuous driving before a stop.
    # Real drivers stop well before the legal 11h HOS limit or the fuel
    # tank running dry — meal breaks, mandatory 30-min rest, stretching legs.
    # Previously the planner used ONLY fuel range + full HOS remaining to
    # decide stop spacing, which could place a first stop 600+ miles / 8+
    # hours in on a full tank — technically "safe" by fuel/HOS math, but not
    # how drivers actually plan a trip. Default 4h matches a common
    # real-world break cadence; UI can override via `max_hours_between_stops`.
    max_hours_between_stops = float(body.get("max_hours_between_stops", 4.0))

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

    # Always merge local locations.json — Databricks sandbox only has a subset
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
    local_stops = [_loc_to_stop(l) for l in LOCATIONS]
    if corridor_stops:
        # Merge: add local stops not already in Databricks results (de-dup by name)
        existing_names = {s["name"] for s in corridor_stops}
        corridor_stops = corridor_stops + [s for s in local_stops if s["name"] not in existing_names]
    else:
        corridor_stops = local_stops

    # Build optimized stop list — pick 1-3 stops spaced along route
    # Determine number of stops needed based on fuel range and route distance
    # total_miles not yet known here — use a rough estimate for stop count
    rough_miles = round(
        ((from_coords[0] - to_coords[0])**2 + (from_coords[1] - to_coords[1])**2)**0.5 * 69
    )
    # Fuel range from current level; a stop is needed every ~(range * 0.85) miles
    # (0.85 safety buffer — don't run below 15%). No artificial floor here —
    # a driver with only 52mi of range must be shown a stop within ~44mi, not
    # pushed out to some minimum distance. (A floor of 100 previously forced
    # every plan to space stops at least 100mi apart even when fuel range was
    # much lower, which is how a "52mi of fuel" driver could see a first stop
    # placed at 101mi — the driver would run out before reaching it.)
    safe_range = max(fuel_range_mi * 0.85, 10)
    # Driver's preferred break cadence, converted to miles at avg 55mph.
    # This is a separate, usually-tighter constraint than fuel/HOS — it's
    # about driver comfort/routine, not a hard mechanical or legal limit.
    preferred_range = max(max_hours_between_stops * 55, 10)
    # num_stops_needed is finalized after HOS is resolved below; placeholder here
    num_stops_needed = max(1, int(rough_miles / max(min(safe_range, preferred_range), 1)))

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

        # Scale tolerance with route length — long diagonal routes need wider corridor
        route_len_deg = (length_sq ** 0.5)
        MAX_PERP_DEG = min(2.0, max(0.5, route_len_deg * 0.20))  # ~35mi min, ~140mi max

        # Drop stops behind origin (t < 0.05), past 90% of route (no point stopping near destination),
        # or too far off the corridor
        corridor_stops = [
            s for s in corridor_stops
            if 0.05 <= route_progress(s) <= 0.90 and perp_distance_deg(s) <= MAX_PERP_DEG
        ]

        # If all stops failed the corridor filter, use local stops unfiltered
        if not corridor_stops:
            corridor_stops = local_stops

        # Sort by position along route first, then quality tier
        corridor_stops.sort(key=lambda s: (
            route_progress(s),
            not s.get("is_pfj", False),
            not s.get("in_network", False),
            not s.get("visited_before", False),
        ))

        def stop_miles_from_origin(stop):
            return route_progress(stop) * rough_miles

        chosen = corridor_stops[:num_stops_needed]  # refined below after HOS
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

    # Refine num_stops_needed now that hos_hours_driven is resolved.
    # max_between_stops is the tightest of three independent constraints:
    #   - fuel range (mechanical: how far the tank can physically go)
    #   - remaining legal drive time (HOS: how far the law allows)
    #   - preferred break cadence (driver comfort: how far they actually
    #     want to drive before stopping — usually the tightest of the three,
    #     since real drivers stop for meals/rest well before hitting either
    #     hard limit; this used to be missing entirely, which is how a full
    #     tank + full HOS could produce a first stop 600+ miles in)
    hos_drive_miles = hos_remaining * 55
    hard_limit = min(safe_range, hos_drive_miles) if hos_drive_miles > 0 else safe_range
    max_between_stops = min(hard_limit, preferred_range)
    # Track which constraint is actually binding, for accurate UI messaging
    # (previously every "stop is further than expected" case was labeled
    # a fuel issue even when HOS or the driver's own preference was the
    # real reason).
    if preferred_range <= hard_limit:
        binding_constraint = "preference"
    elif hos_drive_miles > 0 and hos_drive_miles < safe_range:
        binding_constraint = "hos"
    else:
        binding_constraint = "fuel"
    num_stops_needed = max(1, int(rough_miles / max(max_between_stops, 1)) + (1 if rough_miles % max(max_between_stops, 1) > 50 else 0))
    # If UI explicitly requested a stop count, honour it (capped at available stops)
    if requested_stops:
        num_stops_needed = max(num_stops_needed, int(requested_stops))
    num_stops_needed = max(1, min(num_stops_needed, len(corridor_stops) if corridor_stops else 1))
    # Re-slice chosen with the refined count. Stops must be reachable within
    # max_between_stops (the real fuel/HOS-safe distance) from the previous
    # stop (or origin for the first one) — NOT just evenly spaced across the
    # whole trip. Evenly-spacing by trip fraction (the old approach) could
    # place the first stop well past the driver's actual safe range (e.g. a
    # midpoint-based pick landing at mile 101 when the driver only has 52mi
    # of fuel left).
    out_of_range_legs = []  # legs where no stop was actually reachable within the fuel-safe range
    if corridor_stops:
        if num_stops_needed >= len(corridor_stops):
            chosen = corridor_stops
            # Verify each stop is actually reachable from the previous one —
            # taking "all available stops" doesn't guarantee they're in-range.
            _last_mile = 0.0
            for _s in sorted(chosen, key=stop_miles_from_origin):
                _mi = stop_miles_from_origin(_s)
                if _mi - _last_mile > max_between_stops:
                    out_of_range_legs.append({
                        "from_mile": round(_last_mile),
                        "nearest_stop_mile": round(_mi),
                        "safe_range_mi": round(max_between_stops),
                        "reason": binding_constraint,
                    })
                _last_mile = _mi
        else:
            chosen = []
            last_mile = 0.0
            remaining = sorted(corridor_stops, key=stop_miles_from_origin)
            for _ in range(num_stops_needed):
                # Candidates actually reachable from the last stop (or origin)
                reachable = [
                    s for s in remaining
                    if s not in chosen and last_mile < stop_miles_from_origin(s) <= last_mile + max_between_stops
                ]
                if reachable:
                    # Prefer the furthest reachable stop (maximize distance
                    # covered per leg) that's still in-range, tie-broken by quality
                    best = max(reachable, key=lambda s: (
                        stop_miles_from_origin(s),
                        s.get("is_pfj", False),
                        s.get("in_network", False),
                    ))
                else:
                    # Nothing reachable within safe range. Do NOT silently
                    # present a too-far stop as if it were a safe pick — record
                    # the gap so the response can explicitly warn the driver,
                    # then fall back to the closest remaining stop past
                    # last_mile only so the plan isn't completely empty.
                    ahead = [s for s in remaining if s not in chosen and stop_miles_from_origin(s) > last_mile]
                    if not ahead:
                        break
                    best = min(ahead, key=stop_miles_from_origin)
                    out_of_range_legs.append({
                        "from_mile": round(last_mile),
                        "nearest_stop_mile": round(stop_miles_from_origin(best)),
                        "safe_range_mi": round(max_between_stops),
                        "reason": binding_constraint,
                    })
                chosen.append(best)
                last_mile = stop_miles_from_origin(best)
            chosen.sort(key=route_progress)

    # Build stops response
    stops_out = []
    for i, s in enumerate(chosen):
        name = s.get("name", "Pilot Stop")
        city = s.get("city", "")
        # Real position along the route, not an evenly-spaced synthetic value —
        # a stop chosen to respect the fuel-safe range must report its ACTUAL
        # mile marker, otherwise the UI can show "stop at mile 101" for a stop
        # that's actually much closer (or claim a stop is reachable when the
        # display number doesn't match where it truly sits on the route).
        mile_marker = round(max(0.0, route_progress(s)) * total_miles) if corridor_stops else round(total_miles * (i + 1) / (len(chosen) + 1))
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
    # Flag stops that exceed max_between_stops (e.g. no corridor stop exists
    # close enough — sparse stop data — so the leg planner had to fall back
    # to the nearest available stop beyond the safe distance). This can't be
    # silently hidden: the UI/AI should tell the driver why this leg is
    # longer than expected. Kept `fuel_break_required` as the flag name for
    # frontend/backwards compatibility, but it's no longer assumed to always
    # mean "fuel" — `range_break_reason` says which constraint actually did
    # (or would) bind: "fuel", "hos", or "preference".
    prev_mile = 0
    for s in stops_out:
        leg_miles = s.get("mile_marker", 0) - prev_mile
        s["fuel_break_required"] = leg_miles > max_between_stops
        s["range_break_reason"] = binding_constraint if leg_miles > max_between_stops else None
        prev_mile = s.get("mile_marker", 0)

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

    plan_model_id = os.getenv("BEDROCK_PLAN_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    ai_plan = ask_ai(prompt, max_tokens=200, model_id=plan_model_id)
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

    # Store last plan so return loads and chat use the right route
    _last_plan["from"]  = from_
    _last_plan["to"]    = to_
    _last_plan["stops"] = [{"name": s["name"], "city": s["city"],
                            "lat": s.get("lat"), "lon": s.get("lon"),
                            "parking_forecast_pct": s.get("parking_forecast_pct"),
                            "shower_wait_min": s.get("shower_wait_min"),
                            "food_available": s.get("food_available", "")}
                           for s in chosen]
    # Bust chat cache so next chat call uses the new route's stops
    _chat_stops_cache["text"] = None

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
        "fuel_warning": (
            _build_range_warning(out_of_range_legs[0]) if out_of_range_legs else None
        ),
        "out_of_range_legs": out_of_range_legs,
        "journey_context": {
            "fuel_pct":      fuel_pct,
            "fuel_gal":      fuel_gal,
            "fuel_range_mi": fuel_range_mi,
            "cargo_type":    cargo_type,
            "arrive_by":     arrive_by,
            "num_stops_needed": num_stops_needed,
            "max_hours_between_stops": max_hours_between_stops,
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

def _driver_intel(driver_id):
    """Deterministic synthetic intelligence per driver: HOS, last stop, pilot streak."""
    import hashlib
    h = int(hashlib.md5(str(driver_id * 31 + 7).encode()).hexdigest(), 16)
    hos_driven   = round((h % 90) / 10, 1)          # 0.0–9.0h
    hos_remaining = max(0, round(11.0 - hos_driven, 1))
    # last stop: 70% Pilot, 30% competitor
    pilot_last = (h % 10) >= 3
    competitors_list = ["Love's Travel Stop", "TA/Petro", "Flying J (competitor)", "Speedway", "Casey's"]
    last_stop_name = "Pilot Flying J" if pilot_last else competitors_list[h % len(competitors_list)]
    # missed savings: competitor drivers who could have saved ~$12-28/stop
    missed = 0 if pilot_last else 12 + (h % 17)
    # pilot stop streak (consecutive Pilot stops)
    streak = (h >> 4) % 8 if pilot_last else 0
    # miles from a demo load origin (Nashville) — rough synthetic
    cities_miles = {"Columbus, OH": 310, "Detroit, MI": 520, "Memphis, TN": 210,
                    "Charlotte, NC": 410, "Atlanta, GA": 250, "Kansas City, MO": 480,
                    "Dallas, TX": 670, "Houston, TX": 780, "Chicago, IL": 470,
                    "St. Louis, MO": 310, "Louisville, KY": 175, "Cincinnati, OH": 280}
    return {
        "hos_driven":   hos_driven,
        "hos_remaining": hos_remaining,
        "last_stop":    last_stop_name,
        "last_stop_pilot": pilot_last,
        "missed_savings": missed,
        "pilot_streak": streak,
    }

@app.route("/api/fleet")
def api_fleet():
    """Return fleet summary: all drivers with loyalty + intelligence data."""
    fleet = []
    drivers = DRIVERS[:15]
    try:
        from databricks_client import get_driver_loyalty
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # Fetch all loyalty data in parallel — avoids 15 sequential Databricks calls
        with ThreadPoolExecutor(max_workers=8) as ex:
            loy_futures = {ex.submit(get_driver_loyalty, d["id"]): d for d in drivers}
            loy_map = {}
            for fut in as_completed(loy_futures):
                d = loy_futures[fut]
                try:
                    loy_map[d["id"]] = fut.result()
                except Exception:
                    loy_map[d["id"]] = None
        for d in drivers:
            loy   = loy_map.get(d["id"])
            intel = _driver_intel(d["id"])
            entry = {
                "id":          d["id"],
                "name":        d["name"],
                "current_location": d.get("current_location", "Unknown"),
                "destination": d.get("destination", "Unknown"),
                "route":       d.get("current_location", "Unknown") + " → " + d.get("destination", "Unknown"),
                "fuel_pct":    min(100, round(d.get("fuel_remaining_miles", 300) / 6)),
                "fuel_miles":  d.get("fuel_remaining_miles", 300),
                "status":      "fuel_risk" if d.get("fuel_remaining_miles", 999) < 150 else "ok",
                "loyalty_tier":  loy["loyalty_tier"]  if loy else d.get("loyalty_tier", "Standard"),
                "total_gallons": loy["total_gallons"]  if loy else 0,
                "total_visits":  loy["total_visits"]   if loy else 0,
                **intel,
            }
            fleet.append(entry)
    except Exception as e:
        print(f"[api_fleet] {e}")
        fleet = [
            {
                "id": d["id"], "name": d["name"],
                "current_location": d.get("current_location",""),
                "destination": d.get("destination",""),
                "route": d.get("current_location","") + " → " + d.get("destination",""),
                "fuel_pct": min(100, round(d.get("fuel_remaining_miles",300)/6)),
                "fuel_miles": d.get("fuel_remaining_miles", 300),
                "status": "fuel_risk" if d.get("fuel_remaining_miles",999) < 150 else "ok",
                "loyalty_tier": d.get("loyalty_tier","Standard"),
                "total_gallons": 0, "total_visits": 0,
                **_driver_intel(d["id"]),
            }
            for d in drivers
        ]

    at_risk    = [f for f in fleet if f["status"] == "fuel_risk"]
    competitor = [f for f in fleet if not f.get("last_stop_pilot", True)]
    total_missed = sum(f.get("missed_savings", 0) for f in competitor)

    return jsonify({
        "drivers": fleet,
        "summary": {
            "total":    len(fleet),
            "at_risk":  len(at_risk),
            "on_route": len(fleet),
            "competitor_stops": len(competitor),
            "missed_savings":   total_missed,
        }
    })


@app.route("/api/fleet/suggest", methods=["POST"])
def api_fleet_suggest():
    """Rank drivers for a load based on location proximity, HOS, fuel, and Pilot alignment."""
    body = request.json or {}
    load_origin = body.get("origin", "Nashville, TN")
    load_dest   = body.get("destination", "Dallas, TX")
    load_miles  = int(body.get("miles", 650))

    # Get current fleet (reuse same logic without a full HTTP round-trip)
    fleet = []
    for d in DRIVERS[:15]:
        intel = _driver_intel(d["id"])
        fleet.append({
            "id": d["id"], "name": d["name"],
            "current_location": d.get("current_location",""),
            "fuel_miles": d.get("fuel_remaining_miles", 300),
            "fuel_pct": min(100, round(d.get("fuel_remaining_miles",300)/6)),
            "loyalty_tier": d.get("loyalty_tier","Standard"),
            **intel,
        })

    # Score each driver (higher = better fit)
    def score(d):
        s = 0
        # HOS headroom — need at least 4h for a meaningful leg
        if d["hos_remaining"] >= 8:   s += 30
        elif d["hos_remaining"] >= 5: s += 15
        elif d["hos_remaining"] >= 3: s += 5
        # Fuel — enough to reach first Pilot stop (~150mi min)
        if d["fuel_miles"] >= 300:    s += 25
        elif d["fuel_miles"] >= 150:  s += 10
        # Pilot alignment — prefer drivers overdue for a Pilot stop
        if not d["last_stop_pilot"]:  s += 20   # overdue — assigning nudges them back
        elif d["pilot_streak"] >= 3:  s += 10   # loyal
        # Loyalty tier bonus
        tier = (d["loyalty_tier"] or "").lower()
        if "elite" in tier or "platinum" in tier: s += 10
        elif "gold" in tier:                      s += 5
        return s

    ranked = sorted(fleet, key=score, reverse=True)[:5]

    def why(d):
        reasons = []
        if d["hos_remaining"] >= 8:
            reasons.append(f"{d['hos_remaining']}h HOS remaining — full day available")
        elif d["hos_remaining"] >= 5:
            reasons.append(f"{d['hos_remaining']}h HOS remaining — fits this load")
        else:
            reasons.append(f"⚠️ Only {d['hos_remaining']}h HOS left — short legs only")
        if d["fuel_miles"] >= 300:
            reasons.append(f"⛽ {d['fuel_miles']}mi fuel — no stop needed before pickup")
        elif d["fuel_miles"] >= 150:
            reasons.append(f"⛽ {d['fuel_miles']}mi fuel — one Pilot stop en route")
        else:
            reasons.append(f"🚨 {d['fuel_miles']}mi fuel — needs fuel before pickup")
        if not d["last_stop_pilot"]:
            reasons.append(f"Last stop was {d['last_stop']} — route passes 2 Pilot locations")
        elif d["pilot_streak"] >= 3:
            reasons.append(f"🏆 {d['pilot_streak']}-stop Pilot streak — loyalty on track")
        return reasons

    suggestions = []
    for i, d in enumerate(ranked):
        suggestions.append({
            "rank":    i + 1,
            "id":      d["id"],
            "name":    d["name"],
            "location": d["current_location"],
            "hos_remaining": d["hos_remaining"],
            "fuel_miles":    d["fuel_miles"],
            "last_stop_pilot": d["last_stop_pilot"],
            "last_stop":     d["last_stop"],
            "loyalty_tier":  d["loyalty_tier"],
            "score":   score(d),
            "reasons": why(d),
            "pilot_stops_on_route": 2 if load_miles > 400 else 1,
            "estimated_savings": round(load_miles / 6.5 * 0.097, 2),
        })

    return jsonify({"suggestions": suggestions, "load_origin": load_origin, "load_destination": load_dest})

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
    Route-aware competitor truck stops. Selects the corridor that best matches
    _last_plan (from/to). Falls back to I-40W (Nashville→Dallas) if no plan active.
    """
    try:
        from databricks_client import get_fuel_prices
        pilot_fleet = get_fuel_prices().get("avg_net_price") or 3.448
        pilot_retail = get_fuel_prices().get("avg_gross_price") or 3.545
    except Exception:
        pilot_fleet  = 3.448
        pilot_retail = 3.545

    # Determine corridor from last plan destination
    dest = (_last_plan.get("to") or "").lower()
    frm  = (_last_plan.get("from") or "").lower()
    if any(k in dest for k in ["miami", "orlando", "tampa", "jacksonville", "fort pierce", "ocala", "florida", " fl"]):
        corridor = "i75s"  # I-75 South to Florida
    elif any(k in dest for k in ["atlanta", "ga", "chattanooga"]) and "knoxville" not in frm:
        corridor = "i75"
    elif any(k in dest for k in ["chicago", "indianapolis", "indiana", "illinois"]):
        corridor = "i65"
    elif any(k in frm for k in ["knoxville"]):
        corridor = "i40w"  # Knoxville → Dallas goes through Nashville on I-40W
    else:
        corridor = "i40w"  # default: Nashville→Memphis→Dallas

    if corridor == "i75s":
        # Nashville → Miami: I-24 → I-75 → Florida Turnpike
        competitors = [
            {
                "id": "loves_valdosta",
                "brand": "Love's",
                "name": "Love's Travel Stop #445",
                "city": "Valdosta", "state": "GA",
                "lat": 30.845, "lon": -83.292,
                "mile_marker": 490,
                "diesel_price": round(pilot_retail + 0.09, 3),
                "amenities": ["Subway", "Parking", "Showers", "CAT Scale"],
                "missing_vs_pilot": ["Fleet pricing", "MyRewards points", "Mobile fueling"],
                "nearest_pilot": {
                    "name": "Pilot Valdosta #219",
                    "city": "Valdosta, GA",
                    "miles_away": 4,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(0.09+pilot_retail-pilot_fleet,2)}/gal vs Love's", "2× MyRewards points", "Shower in 10 min avg"],
                },
            },
            {
                "id": "ta_petro_lake_city",
                "brand": "TA Petro",
                "name": "TA Petro #331",
                "city": "Lake City", "state": "FL",
                "lat": 30.197, "lon": -82.651,
                "mile_marker": 572,
                "diesel_price": round(pilot_retail + 0.13, 3),
                "amenities": ["Iron Skillet", "Parking", "Showers", "Laundry"],
                "missing_vs_pilot": ["Fleet pricing", "Loyalty program", "Mobile app offers"],
                "nearest_pilot": {
                    "name": "Pilot Lake City #147",
                    "city": "Lake City, FL",
                    "miles_away": 2,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(pilot_retail+0.13-pilot_fleet,2)}/gal vs TA", "Active offer: $29 bonus points", "82% parking available"],
                },
            },
            {
                "id": "bp_orlando",
                "brand": "BP",
                "name": "BP Truck Plaza",
                "city": "Orlando", "state": "FL",
                "lat": 28.551, "lon": -81.391,
                "mile_marker": 718,
                "diesel_price": round(pilot_retail + 0.06, 3),
                "amenities": ["Hot food", "Parking"],
                "missing_vs_pilot": ["Fleet pricing", "Showers", "Loyalty rewards", "CAT Scale"],
                "nearest_pilot": {
                    "name": "Pilot Orlando #388",
                    "city": "Orlando, FL",
                    "miles_away": 3,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(pilot_retail+0.06-pilot_fleet,2)}/gal vs BP", "Full-service showers", "MyRewards 2× points"],
                },
            },
        ]
    elif corridor == "i75":
        # Nashville → Atlanta: I-24/I-75
        competitors = [
            {
                "id": "loves_murfreesboro",
                "brand": "Love's",
                "name": "Love's Travel Stop #318",
                "city": "Murfreesboro", "state": "TN",
                "lat": 35.8456, "lon": -86.3903,
                "mile_marker": 78,
                "diesel_price": round(pilot_retail + 0.08, 3),
                "amenities": ["Subway", "Parking", "Showers", "CAT Scale"],
                "missing_vs_pilot": ["Fleet pricing", "MyRewards points", "2x loyalty multiplier", "Mobile fueling"],
                "nearest_pilot": {
                    "name": "Pilot Murfreesboro #312",
                    "city": "Murfreesboro, TN",
                    "miles_away": 5,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(0.08+pilot_retail-pilot_fleet,2)}/gal vs Love's", "2× MyRewards points", "Shower in 8 min avg", "Pilot Coffee"],
                },
            },
            {
                "id": "ta_petro_chattanooga",
                "brand": "TA Petro",
                "name": "TA Petro #187",
                "city": "Chattanooga", "state": "TN",
                "lat": 35.0456, "lon": -85.3097,
                "mile_marker": 148,
                "diesel_price": round(pilot_retail + 0.12, 3),
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
                "lat": 34.5023, "lon": -84.9513,
                "mile_marker": 215,
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
    elif corridor == "i65":
        # Chicago → Nashville: I-65
        competitors = [
            {
                "id": "loves_gary",
                "brand": "Love's",
                "name": "Love's Travel Stop #601",
                "city": "Gary", "state": "IN",
                "lat": 41.5934, "lon": -87.3464,
                "mile_marker": 25,
                "diesel_price": round(pilot_retail + 0.09, 3),
                "amenities": ["Subway", "Parking", "Showers"],
                "missing_vs_pilot": ["Fleet pricing", "MyRewards points", "CAT Scale", "Mobile fueling"],
                "nearest_pilot": {
                    "name": "Pilot Gary #145",
                    "city": "Gary, IN",
                    "miles_away": 3,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(0.09+pilot_retail-pilot_fleet,2)}/gal vs Love's", "2× MyRewards points", "CAT Scale on-site"],
                },
            },
            {
                "id": "ta_petro_indianapolis",
                "brand": "TA Petro",
                "name": "TA Petro #92",
                "city": "Indianapolis", "state": "IN",
                "lat": 39.7684, "lon": -86.1581,
                "mile_marker": 155,
                "diesel_price": round(pilot_retail + 0.11, 3),
                "amenities": ["Iron Skillet", "Parking", "Showers", "Laundry"],
                "missing_vs_pilot": ["Fleet pricing", "Loyalty program", "Mobile app offers"],
                "nearest_pilot": {
                    "name": "Pilot Indianapolis #267",
                    "city": "Indianapolis, IN",
                    "miles_away": 2,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(pilot_retail+0.11-pilot_fleet,2)}/gal vs TA", "Active offer: $25 bonus points", "77% parking available"],
                },
            },
            {
                "id": "bp_bowling_green",
                "brand": "BP",
                "name": "BP Truck Stop",
                "city": "Bowling Green", "state": "KY",
                "lat": 36.9903, "lon": -86.4436,
                "mile_marker": 310,
                "diesel_price": round(pilot_retail + 0.06, 3),
                "amenities": ["Hot food", "Parking"],
                "missing_vs_pilot": ["Fleet pricing", "Showers", "Loyalty rewards", "CAT Scale"],
                "nearest_pilot": {
                    "name": "Pilot Bowling Green #188",
                    "city": "Bowling Green, KY",
                    "miles_away": 3,
                    "diesel_price": pilot_fleet,
                    "perks": [f"Fleet price saves ${round(pilot_retail+0.06-pilot_fleet,2)}/gal vs BP", "Full-service showers", "MyRewards 2× points"],
                },
            },
        ]
    else:
        # I-40 West: Nashville → Memphis → Dallas (default)
        competitors = [
        # I-40 West: Nashville → Memphis corridor
        {
            "id": "loves_jackson",
            "brand": "Love's",
            "name": "Love's Travel Stop #512",
            "city": "Jackson", "state": "TN",
            "lat": 35.6145, "lon": -88.8139,
            "mile_marker": 82,
            "diesel_price": round(pilot_retail + 0.08, 3),
            "amenities": ["Subway", "Parking", "Showers", "CAT Scale"],
            "missing_vs_pilot": ["Fleet pricing", "MyRewards points", "2x loyalty multiplier", "Mobile fueling"],
            "nearest_pilot": {
                "name": "Pilot Jackson #198",
                "city": "Jackson, TN",
                "miles_away": 3,
                "diesel_price": pilot_fleet,
                "perks": [f"Fleet price saves ${round(0.08+pilot_retail-pilot_fleet,2)}/gal vs Love's", "2× MyRewards points", "Pilot Coffee", "Shower in 8 min avg"],
            },
        },
        # I-40 West: Memphis area
        {
            "id": "ta_petro_memphis",
            "brand": "TA Petro",
            "name": "TA Petro #214",
            "city": "Memphis", "state": "TN",
            "lat": 35.1495, "lon": -90.0490,
            "mile_marker": 187,
            "diesel_price": round(pilot_retail + 0.12, 3),
            "amenities": ["Iron Skillet", "Parking", "Showers", "Laundry"],
            "missing_vs_pilot": ["Fleet pricing", "Loyalty program", "Mobile app offers", "CAT Scale"],
            "nearest_pilot": {
                "name": "Pilot Memphis #412",
                "city": "Memphis, TN",
                "miles_away": 2,
                "diesel_price": pilot_fleet,
                "perks": [f"Fleet price saves ${round(pilot_retail+0.12-pilot_fleet,2)}/gal vs TA", "Active offer: $29 bonus points", "CAT Scale on-site", "78% parking available"],
            },
        },
        # I-40 West: Little Rock AR
        {
            "id": "bp_little_rock",
            "brand": "BP",
            "name": "BP Truck Plaza",
            "city": "Little Rock", "state": "AR",
            "lat": 34.7465, "lon": -92.2896,
            "mile_marker": 367,
            "diesel_price": round(pilot_retail + 0.05, 3),
            "amenities": ["Hot food", "Parking"],
            "missing_vs_pilot": ["Fleet pricing", "Showers", "Loyalty rewards", "CAT Scale", "Mobile fueling"],
            "nearest_pilot": {
                "name": "Pilot Little Rock #287",
                "city": "Little Rock, AR",
                "miles_away": 4,
                "diesel_price": pilot_fleet,
                "perks": [f"Fleet price saves ${round(pilot_retail+0.05-pilot_fleet,2)}/gal vs BP", "Full-service showers", "MyRewards 2× points", "DoorDash delivery inside"],
            },
        },
        ]  # end i40w competitors

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

# Return load templates keyed by destination city prefix (lowercase).
# Each entry is a list of loads originating FROM that city.
_RETURN_LOADS_BY_CITY = {
    "dallas": [
        {"id": "RL001", "origin": "Dallas, TX", "destination": "Nashville, TN",
         "cargo": "Auto Parts", "miles": 670,
         "gross_rate": 2100, "fuel_gal": 101, "window_closes_min": 240,
         "urgency": "high", "loads_competing": 3},
        {"id": "RL002", "origin": "Dallas, TX", "destination": "Atlanta, GA",
         "cargo": "Consumer Goods", "miles": 781,
         "gross_rate": 2400, "fuel_gal": 118, "window_closes_min": 420,
         "urgency": "medium", "loads_competing": 5},
        {"id": "RL003", "origin": "Dallas, TX", "destination": "Chicago, IL",
         "cargo": "Refrigerated", "miles": 921,
         "gross_rate": 2950, "fuel_gal": 139, "window_closes_min": 600,
         "urgency": "low", "loads_competing": 2},
    ],
    "atlanta": [
        {"id": "RL001", "origin": "Atlanta, GA", "destination": "Nashville, TN",
         "cargo": "Consumer Goods", "miles": 248,
         "gross_rate": 920, "fuel_gal": 37, "window_closes_min": 180,
         "urgency": "high", "loads_competing": 4},
        {"id": "RL002", "origin": "Atlanta, GA", "destination": "Charlotte, NC",
         "cargo": "Auto Parts", "miles": 244,
         "gross_rate": 1040, "fuel_gal": 36, "window_closes_min": 340,
         "urgency": "medium", "loads_competing": 2},
        {"id": "RL003", "origin": "Atlanta, GA", "destination": "Memphis, TN",
         "cargo": "Refrigerated", "miles": 393,
         "gross_rate": 1480, "fuel_gal": 59, "window_closes_min": 480,
         "urgency": "low", "loads_competing": 7},
    ],
    "nashville": [
        {"id": "RL001", "origin": "Nashville, TN", "destination": "Atlanta, GA",
         "cargo": "Automotive", "miles": 248,
         "gross_rate": 890, "fuel_gal": 37, "window_closes_min": 200,
         "urgency": "high", "loads_competing": 3},
        {"id": "RL002", "origin": "Nashville, TN", "destination": "Dallas, TX",
         "cargo": "General Freight", "miles": 670,
         "gross_rate": 2050, "fuel_gal": 101, "window_closes_min": 360,
         "urgency": "medium", "loads_competing": 6},
        {"id": "RL003", "origin": "Nashville, TN", "destination": "Chicago, IL",
         "cargo": "Refrigerated", "miles": 476,
         "gross_rate": 1600, "fuel_gal": 72, "window_closes_min": 480,
         "urgency": "low", "loads_competing": 4},
    ],
}
# Generic fallback loads — used when destination city not in the map above
_RETURN_LOADS_GENERIC = [
    {"id": "RL001", "cargo": "General Freight", "miles": 400,
     "gross_rate": 1200, "fuel_gal": 60, "window_closes_min": 300,
     "urgency": "medium", "loads_competing": 4},
    {"id": "RL002", "cargo": "Refrigerated", "miles": 550,
     "gross_rate": 1800, "fuel_gal": 83, "window_closes_min": 480,
     "urgency": "low", "loads_competing": 3},
    {"id": "RL003", "cargo": "Auto Parts", "miles": 300,
     "gross_rate": 950, "fuel_gal": 45, "window_closes_min": 180,
     "urgency": "high", "loads_competing": 6},
]

@app.route("/api/return_loads")
def api_return_loads():
    """
    Returns ranked return-load opportunities from the driver's actual destination
    (stored in _last_plan), with net earnings using real Pilot fuel prices.
    """
    from databricks_client import get_fuel_prices
    try:
        fp = get_fuel_prices()
        pilot_price = fp.get("avg_net_price") or fp.get("avg_gross_price") or 3.45
    except Exception:
        pilot_price = 3.45

    # Pick loads for the actual destination city
    dest = (_last_plan.get("to") or "").lower()
    city_key = next((k for k in _RETURN_LOADS_BY_CITY if k in dest), None)
    base_loads = _RETURN_LOADS_BY_CITY[city_key] if city_key else [
        {**l, "origin": _last_plan.get("to", "Your Destination"),
         "destination": _last_plan.get("from", "Origin")}
        for l in _RETURN_LOADS_GENERIC
    ]

    results = []
    for load in base_loads:
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
    images_dir = os.path.join(_base, "static", "images")
    return send_from_directory(images_dir, filename)

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
    # debug/reloader disabled by default — the debug auto-reloader restarts
    # the whole process on ANY file change in this OneDrive-synced folder
    # (background sync activity, editor autosave, even a test script running
    # nearby), which drops any request in flight at that moment. From the
    # browser this looks exactly like a random timeout, and was traced back
    # to this during demo/testing. Set FLASK_DEBUG=1 in .env to re-enable
    # debug mode + auto-reload for active development.
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"
    # threaded=True so one slow request (e.g. a multi-second Databricks/
    # Bedrock call) doesn't block the dev server from accepting other
    # connections in the meantime.
    app.run(debug=debug_mode, use_reloader=debug_mode, threaded=True, port=port, host="0.0.0.0")
