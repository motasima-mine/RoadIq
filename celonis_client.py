"""
Celonis MCP Client
-------------------
Talks to the Celonis Agent Tools (MCP) Server using the real MCP JSON-RPC
protocol (initialize -> notifications/initialized -> tools/call).

The server responds with Server-Sent Events (SSE) framing even though we
send a plain JSON-RPC POST — each response body looks like:
    event: message
    data: {"jsonrpc":"2.0","id":1,"result":{...}}

Auth: OAuth2 client credentials against CELONIS_TOKEN_URL, with the
required `scope=mcp-asset.tools:execute`.
"""

import os
import time
import json
import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MCP_SERVER_URL = (
    "https://ai-context-model-pilot-pov.us-2.celonis.cloud"
    "/studio-copilot/api/v1/mcp-servers/mcp"
    "/64c73b17-5383-4263-a6aa-58de560edf6d"
)

_token_cache = {"token": None, "expires_at": 0}
_initialized = False  # tracks whether we've completed the MCP handshake this process


def get_celonis_token() -> str:
    """Fetch (or reuse cached) OAuth2 access token for the Celonis MCP server."""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["token"]

    resp = requests.post(
        os.getenv("CELONIS_TOKEN_URL"),
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("CELONIS_CLIENT_ID"),
            "client_secret": os.getenv("CELONIS_CLIENT_SECRET"),
            "scope": os.getenv("CELONIS_SCOPE", "mcp-asset.tools:execute"),
        },
        timeout=10,
        verify=False,  # corporate proxy intercepts SSL — bypass verification
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]


def _parse_sse_json(body: str) -> dict:
    """
    The MCP server responds with SSE framing:
        event: message
        data: {...json...}
    Extract and parse the JSON from the 'data:' line.
    """
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    # Fall back to plain JSON if no SSE framing was used
    return json.loads(body)


def _mcp_request(method: str, params: dict, req_id: int, token: str, expect_response: bool = True):
    """Send one JSON-RPC request to the Celonis MCP server."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    if req_id is not None:
        payload["id"] = req_id

    resp = requests.post(
        MCP_SERVER_URL, json=payload, headers=headers, timeout=30, verify=False
    )
    resp.raise_for_status()

    if not expect_response or not resp.text.strip():
        return None
    return _parse_sse_json(resp.text)


def _ensure_initialized(token: str):
    """Run the MCP initialize handshake once per process."""
    global _initialized
    if _initialized:
        return
    _mcp_request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "roadiq", "version": "1.0.0"},
        },
        req_id=1,
        token=token,
    )
    _mcp_request(
        "notifications/initialized", {}, req_id=None, token=token, expect_response=False
    )
    _initialized = True


def _call_tool_raw(tool_name: str, arguments: dict) -> tuple[str | None, bool]:
    """
    Call an MCP tool and return (text_block, is_error) without assuming the
    result is JSON — action-flow tools return plain text, not a JSON list,
    so this is the shared primitive both _call_tool() (data-loading tools)
    and celonis_update_driver_preferences() (action-flow tool) build on.

    Returns (None, False) if the call failed outright (network/auth error) —
    that case is already logged by the caller catching the exception.
    """
    token = get_celonis_token()
    _ensure_initialized(token)

    result = _mcp_request(
        "tools/call",
        {"name": tool_name, "arguments": arguments},
        req_id=int(time.time() * 1000) % 100000,
        token=token,
    )

    tool_result = result.get("result", {})
    content = tool_result.get("content", [])
    if not content:
        return None, False

    text_block = next((b["text"] for b in content if b.get("type") == "text"), None)
    return text_block, bool(tool_result.get("isError"))


def _call_tool(tool_name: str, arguments: dict) -> list | None:
    """
    Call a data-loading MCP tool and return the parsed list of result
    records, or None on failure. If the tool itself reports an error
    (result.isError=true, e.g. invalid arguments), that error text is
    printed and None is returned rather than raising — callers should treat
    this the same as any other unavailability and fall back gracefully.
    """
    try:
        text_block, is_error = _call_tool_raw(tool_name, arguments)
        if text_block is None:
            return None
        if is_error:
            print(f"[celonis_client] Tool '{tool_name}' returned an error: {text_block}")
            return None
        return json.loads(text_block)
    except Exception as e:
        print(f"[celonis_client] MCP tool call '{tool_name}' failed: {e}")
        return None


def celonis_load_locations(route_points: list) -> list | None:
    """
    Fetch Pilot/Flying J locations near the given route via the Celonis
    load_data_location_info MCP tool.

    Args:
        route_points: list of (lat, lon) tuples — typically [origin, destination]

    Returns:
        list of location dicts (only OPEN locations), or None on any failure
        (caller should fall back to local/Databricks data).
    """
    route_str = ",".join(f"({lat},{lon})" for lat, lon in route_points)
    records = _call_tool(
        "load_data_location_info",
        {"route": route_str, "page": 0, "page_size": 50},
    )
    if not records:
        return None

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
            "has_lounge":      bool(loc.get("O_CUSTOM_LINEOFBUSINESS.HASDRIVERSLOUNGE", 0)),
            "has_idle_air":    bool(loc.get("O_CUSTOM_LINEOFBUSINESS.HASIDELAIR", 0)),
            "has_mobile_fuel": bool(loc.get("O_CUSTOM_LINEOFBUSINESS.HASDIESELMOBILEFUELING", 0)),
            "is_pfj":          bool(loc.get("O_CUSTOM_LINEOFBUSINESS.ISPFJOPERATED", 0)),
        })

    return locations if locations else None


def celonis_load_driver(firstname: str, lastname: str) -> list | None:
    """
    Fetch driver context via the Celonis load_data_driver_info MCP tool.

    Returns:
        list of driver record dicts, or None on failure.

    KNOWN CELONIS BUG (confirmed, filed against sandbox 2026-08-05):
    This tool's `firstname`/`lastname` arguments are NOT applied as a
    server-side filter — calling it with a name that cannot exist in any
    dataset (e.g. "Zzyzx Nonexistent99") returns the exact same 50 records
    every time. It is not even random sampling; identical input always
    produces identical, unfiltered output.

    There is currently NO alternative identifier available. The tool's own
    description text mentions "first and last name, or license number," but
    the actual server-side schema (a Pydantic model) only accepts
    {firstname, lastname, page, page_size} — passing license_number, or any
    PFJ internal ID like dim_loyalty_id / dim_loyalty_household_id, is
    rejected outright with:
        "Extra inputs are not permitted [type=extra_forbidden]"
    (This is despite the tool's advertised JSON schema claiming
    additionalProperties: true — the real validation is strict.)

    Reproduction: scripts/test_celonis_filter_bug.py
    Until Celonis fixes server-side filtering (or adds a real ID parameter),
    this tool cannot be used to look up a specific driver by identity.
    """
    records = _call_tool(
        "load_data_driver_info",
        {"firstname": firstname, "lastname": lastname, "page": 0, "page_size": 50},
    )
    return records or None


def get_driver_hos(firstname: str, lastname: str) -> dict | None:
    """
    Compute a Hours-of-Service (HOS) summary for a driver from Celonis
    driver records.

    FMCSA property-carrying drivers get an 11-hour daily drive limit within
    a 14-hour on-duty window. This pulls the driver's logged HOURSWORKED
    entries and computes hours driven "today" (most recent date on record)
    plus how many drive hours remain before they legally must stop.

    Returns:
        {
          "status": str,                 # driver employment status (Active/Suspended/etc.)
          "license_number": str,
          "hours_worked_today": float,   # most recent day's logged hours
          "hours_remaining": float,      # 11 - hours_worked_today, floored at 0
          "miles_remaining": int,        # hours_remaining * avg 55 mph
          "hos_status": str,             # "OK" | "APPROACHING_LIMIT" | "AT_LIMIT"
          "most_recent_date": str,
        }
        or None if no records available.
    """
    records = celonis_load_driver(firstname, lastname)
    if not records:
        return None

    # Records are per hours-of-service log entry; find the most recent date
    dated = [
        r for r in records
        if r.get("O_CUSTOM_DRIVERPAYHOURSOFSERVICESUMMARY.DATE")
        and r.get("O_CUSTOM_DRIVERPAYHOURSOFSERVICESUMMARY.HOURSWORKED") is not None
    ]
    if not dated:
        return None

    dated.sort(
        key=lambda r: r["O_CUSTOM_DRIVERPAYHOURSOFSERVICESUMMARY.DATE"],
        reverse=True,
    )
    latest = dated[0]

    hours_worked = float(latest["O_CUSTOM_DRIVERPAYHOURSOFSERVICESUMMARY.HOURSWORKED"])
    hours_remaining = max(0.0, 11.0 - hours_worked)
    miles_remaining = round(hours_remaining * 55)  # avg highway speed assumption

    if hours_remaining <= 0:
        hos_status = "AT_LIMIT"
    elif hours_remaining <= 2:
        hos_status = "APPROACHING_LIMIT"
    else:
        hos_status = "OK"

    return {
        "status": latest.get("O_CUSTOM_DRIVER.STATUS", "Unknown"),
        "license_number": latest.get("O_CUSTOM_DRIVER.LICENSENUMBER", ""),
        "hours_worked_today": round(hours_worked, 2),
        "hours_remaining": round(hours_remaining, 2),
        "miles_remaining": miles_remaining,
        "hos_status": hos_status,
        "most_recent_date": latest["O_CUSTOM_DRIVERPAYHOURSOFSERVICESUMMARY.DATE"],
    }


def celonis_update_driver_preferences(
    driver_id: str,
    food_preferences: str | None = None,
    shower_preferences: str | None = None,
) -> dict | None:
    """
    Persist a driver's food/shower preferences via the Celonis
    trigger_action_flow_Update_Driver_Preferences MCP tool.

    This is a WRITE operation (unlike every other function in this module,
    which are read-only data loads) — it stores context learned from
    conversation (e.g. the Chat tab) back into Celonis so future
    recommendations can use it.

    Args:
        driver_id: required. The tool description says "prompt the driver
            for it if not available" — in this app we pass the driver's
            dim_loyalty_id (PFJ's internal identifier) as a string.
        food_preferences: optional free-text, e.g. "Subway, no Burger King"
        shower_preferences: optional free-text, e.g. "quick shower, prefer clean stalls"

    Returns:
        {"execution_result": str} on success, or None on failure. At least
        one of food_preferences/shower_preferences should be provided —
        the tool schema allows both to be null but that would be a no-op.
    """
    arguments = {"Driver_ID": str(driver_id)}
    if food_preferences is not None:
        arguments["Food_Preferences"] = food_preferences
    if shower_preferences is not None:
        arguments["Shower_Preferences"] = shower_preferences

    try:
        text_block, is_error = _call_tool_raw(
            "trigger_action_flow_Update_Driver_Preferences", arguments
        )
        if text_block is None:
            return None
        if is_error:
            print(f"[celonis_client] Update_Driver_Preferences returned an error: {text_block}")
            return None
        try:
            return json.loads(text_block)
        except json.JSONDecodeError:
            # Action flows may return plain text rather than JSON — wrap it.
            return {"execution_result": text_block}
    except Exception as e:
        print(f"[celonis_client] Update_Driver_Preferences call failed: {e}")
        return None
