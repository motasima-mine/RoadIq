import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

_token_cache = {"token": None, "expires_at": 0}


def get_celonis_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["token"]

    resp = requests.post(
        os.getenv("CELONIS_TOKEN_URL"),
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("CELONIS_CLIENT_ID"),
            "client_secret": os.getenv("CELONIS_CLIENT_SECRET"),
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]


def celonis_load_locations(route_points: list) -> list | None:
    """
    Fetch open Pilot/Flying J locations from Celonis near the given route.
    route_points: list of (lat, lon) tuples — typically [origin, destination].
    Returns list of location dicts, or None on any failure (app falls back to local data).
    """
    try:
        token = get_celonis_token()

        # Bounding box from route with ±1.5 degree buffer (~100 mile corridor)
        lats = [p[0] for p in route_points]
        lons = [p[1] for p in route_points]
        min_lat, max_lat = min(lats) - 1.5, max(lats) + 1.5
        min_lon, max_lon = min(lons) - 1.5, max(lons) + 1.5

        base = os.getenv("CELONIS_TOKEN_URL", "").replace("/oauth2/token", "")
        endpoint = f"{base}/api/locations"

        resp = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "min_lat": min_lat,
                "max_lat": max_lat,
                "min_lon": min_lon,
                "max_lon": max_lon,
            },
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()

        # Support both a top-level list and {"data": [...]} envelope
        records = raw if isinstance(raw, list) else raw.get("data", [])

        locations = []
        for loc in records:
            status = loc.get("O_CUSTOM_LINEOFBUSINESS.LINEOFBUSINESSSTATUS", "")
            if status != "OPEN":
                continue
            locations.append({
                "lat":             loc.get("O_CUSTOM_LINEOFBUSINESS.ADDRESSLATITUDE"),
                "lng":             loc.get("O_CUSTOM_LINEOFBUSINESS.ADDRESSLONGITUDE"),
                "address":         loc.get("1e2c69ff-0487-47a5-91c1-15e83cc5d87c", ""),
                "city":            loc.get("O_CUSTOM_LINEOFBUSINESS.CITY", ""),
                "state":           loc.get("O_CUSTOM_LINEOFBUSINESS.STATE", ""),
                "brand":           loc.get("O_CUSTOM_LINEOFBUSINESS.STOREFRONTBRAND", ""),
                "diesel_brand":    loc.get("O_CUSTOM_LINEOFBUSINESS.DIESELBRAND", ""),
                "has_lounge":      loc.get("O_CUSTOM_LINEOFBUSINESS.HASDRIVERSLOUNGE", 0),
                "has_idle_air":    loc.get("O_CUSTOM_LINEOFBUSINESS.HASIDELAIR", 0),
                "has_mobile_fuel": loc.get("O_CUSTOM_LINEOFBUSINESS.HASDIESELMOBILEFUELING", 0),
                "is_pfj":          loc.get("O_CUSTOM_LINEOFBUSINESS.ISPFJOPERATED", 0),
            })

        return locations if locations else None

    except Exception as e:
        print(f"[celonis_client] Warning — could not load locations: {e}")
        return None
