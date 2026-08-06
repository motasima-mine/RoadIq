"""
RoadIQ Voice Server — Amazon Nova Sonic bidirectional speech-to-speech bridge.

WHY THIS IS A SEPARATE PROCESS FROM server.py:
server.py is a synchronous Flask app answering plain request/response HTTP
calls. Nova Sonic needs a persistent, bidirectional, async streaming
connection (Bedrock's InvokeModelWithBidirectionalStream API) — structurally
closer to a phone call than a REST call. Rather than bolt async machinery
onto Flask, this runs as its own asyncio process with a WebSocket front door
for the browser.

ARCHITECTURE:
    Browser (mic + speaker, raw PCM16 via WebSocket)
        <-> voice_server.py (this file, asyncio + websockets)
        <-> Amazon Nova Sonic (Bedrock InvokeModelWithBidirectionalStream)
                <-> RoadIQ tool functions (databricks_client.py / celonis_client.py)

Each browser WebSocket connection gets its own NovaSonicSession, which owns
one Bedrock bidirectional stream. Audio frames are relayed in both
directions with no buffering/transcoding beyond base64 (the browser side
handles resampling to 16kHz in / 24kHz out via the AudioWorklet in
static/voice.html).

AUTH NOTE: this SDK (aws_sdk_bedrock_runtime, the "smithy" experimental
streaming client) only supports classic IAM SigV4 credentials
(AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN) — it does
NOT support the AWS_BEARER_TOKEN_BEDROCK auth server.py's Converse-API calls
use. Both are set in .env; this file only reads the IAM triplet, server.py's
ask_ai() only reads the bearer token — they don't conflict.

MODEL: amazon.nova-2-sonic-v1:0 (ACTIVE; the plain amazon.nova-sonic-v1:0 is
LEGACY, end-of-life 2026-09-14 — confirmed via list_foundation_models()).

Run standalone:  python voice_server.py
Then open static/voice.html (served by server.py) in a browser and grant
mic permission. This process listens on ws://localhost:8765 by default.
"""
import os
import sys
import json
import base64
import uuid
import asyncio
import inspect
import datetime
import warnings

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import websockets
from websockets.server import serve as ws_serve

from aws_sdk_bedrock_runtime.client import (
    BedrockRuntimeClient,
    InvokeModelWithBidirectionalStreamOperationInput,
)
from aws_sdk_bedrock_runtime.models import (
    InvokeModelWithBidirectionalStreamInputChunk,
    BidirectionalInputPayloadPart,
)
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

sys.path.insert(0, os.path.dirname(__file__))
import databricks_client
import celonis_client

MODEL_ID = os.getenv("NOVA_SONIC_MODEL_ID", "amazon.nova-2-sonic-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
WS_HOST = os.getenv("VOICE_WS_HOST", "localhost")
WS_PORT = int(os.getenv("VOICE_WS_PORT", "8765"))

# Demo driver / route — same as server.py's DEMO_DRIVER / demo Nashville->Atlanta
# corridor, so voice answers line up with what the rest of the app already
# shows for this driver.
DEMO_DRIVER_ID = 7
DEMO_CORRIDOR = (33.0, 37.0, -87.0, -83.0)  # min_lat, max_lat, min_lon, max_lon

DEBUG = os.getenv("VOICE_DEBUG", "0") == "1"


def debug_print(msg):
    if DEBUG:
        fn = inspect.stack()[1].function
        print(f"{datetime.datetime.now():%H:%M:%S.%f}"[:-3] + f" [{fn}] {msg}")


# ── Tool implementations ────────────────────────────────────────────────────
# These wrap RoadIQ's existing Databricks/Celonis functions so Nova Sonic can
# call them mid-conversation and speak back real data. Same anti-hallucination
# pattern as /api/plan and /api/ai chat: the model only reasons over what a
# tool call actually returns, never invents stop names, prices, or food.

def _tool_get_route_stops(_args):
    """List real Pilot/Flying J stops on the driver's current route."""
    min_lat, max_lat, min_lon, max_lon = DEMO_CORRIDOR
    stops = databricks_client.get_stops_in_corridor(
        min_lat, max_lat, min_lon, max_lon, driver_id=DEMO_DRIVER_ID
    )
    if not stops:
        stops = databricks_client.get_stops_in_corridor(-90, 90, -180, 180, driver_id=DEMO_DRIVER_ID)
    if not stops:
        return {"stops": [], "note": "No stop data available right now."}

    out = []
    for s in stops[:6]:
        out.append({
            "lob_id": s.get("lob_id"),
            "name": s.get("name"),
            "city": s.get("city"),
            "state": s.get("state"),
            "has_lounge": bool(s.get("has_lounge")),
            "has_mobile_fuel": bool(s.get("has_mobile_fuel")),
        })
    return {"stops": out}


def _tool_get_food_at_stop(args):
    """Get real food/restaurant offerings at a specific stop (by lob_id) or the nearest stop if no id given."""
    lob_id = args.get("lob_id")
    if lob_id is None:
        # Fall back to the first corridor stop
        min_lat, max_lat, min_lon, max_lon = DEMO_CORRIDOR
        stops = databricks_client.get_stops_in_corridor(min_lat, max_lat, min_lon, max_lon)
        if not stops:
            return {"food": [], "note": "No stop data available right now."}
        lob_id = stops[0]["lob_id"]

    food_map = databricks_client.get_pfj360_food_offerings([lob_id]) or {}
    items = food_map.get(int(lob_id), [])
    if not items:
        return {"food": [], "note": "No food offering data found for that stop. Do not guess — tell the driver you don't have that data."}
    return {"food": items}


def _tool_get_parking_and_shower(args):
    """Get real parking availability % and shower wait time at a specific stop (by lob_id), or the first corridor stop if none given."""
    lob_id = args.get("lob_id")
    if lob_id is None:
        min_lat, max_lat, min_lon, max_lon = DEMO_CORRIDOR
        stops = databricks_client.get_stops_in_corridor(min_lat, max_lat, min_lon, max_lon)
        if not stops:
            return {"note": "No stop data available right now."}
        lob_id = stops[0]["lob_id"]

    lob_id = int(lob_id)
    parking = databricks_client.get_parking_availability([lob_id]) or {}
    shower = databricks_client.get_shower_wait([lob_id]) or {}
    result = {}
    if lob_id in parking:
        result["parking_pct_available"] = parking[lob_id]["parking_pct_available"]
    if lob_id in shower:
        result["shower_avg_wait_minutes"] = shower[lob_id]["avg_wait_minutes"]
    if not result:
        result["note"] = "No parking/shower data found for that stop."
    return result


def _tool_save_preference(args):
    """Save a food or shower preference the driver mentioned, so future recommendations use it."""
    food = args.get("food_preference")
    shower = args.get("shower_preference")
    if not food and not shower:
        return {"saved": False, "note": "No preference provided."}
    result = celonis_client.celonis_update_driver_preferences(
        str(DEMO_DRIVER_ID), food_preferences=food, shower_preferences=shower
    )
    return {"saved": result is not None, "food_preference": food, "shower_preference": shower}


TOOL_HANDLERS = {
    "getroutestops": _tool_get_route_stops,
    "getfoodatstop": _tool_get_food_at_stop,
    "getparkingandshower": _tool_get_parking_and_shower,
    "savepreference": _tool_save_preference,
}


# ── Nova Sonic event templates (per AWS bidirectional streaming API) ───────
START_SESSION_EVENT = '''{
    "event": {
        "sessionStart": {
            "inferenceConfiguration": { "maxTokens": 1024, "topP": 0.9, "temperature": 0.7 }
        }
    }
}'''

AUDIO_CONTENT_START_EVENT = '''{
    "event": {
        "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "type": "AUDIO",
            "interactive": true,
            "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 16000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64"
            }
        }
    }
}'''

AUDIO_EVENT_TEMPLATE = '''{
    "event": {
        "audioInput": { "promptName": "%s", "contentName": "%s", "content": "%s" }
    }
}'''

TEXT_CONTENT_START_EVENT = '''{
    "event": {
        "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "type": "TEXT",
            "role": "%s",
            "interactive": false,
            "textInputConfiguration": { "mediaType": "text/plain" }
        }
    }
}'''

TEXT_INPUT_EVENT = '''{
    "event": {
        "textInput": { "promptName": "%s", "contentName": "%s", "content": "%s" }
    }
}'''

TOOL_CONTENT_START_EVENT = '''{
    "event": {
        "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "interactive": false,
            "type": "TOOL",
            "role": "TOOL",
            "toolResultInputConfiguration": {
                "toolUseId": "%s",
                "type": "TEXT",
                "textInputConfiguration": { "mediaType": "text/plain" }
            }
        }
    }
}'''

CONTENT_END_EVENT = '''{
    "event": { "contentEnd": { "promptName": "%s", "contentName": "%s" } }
}'''

PROMPT_END_EVENT = '''{ "event": { "promptEnd": { "promptName": "%s" } } }'''

SESSION_END_EVENT = '''{ "event": { "sessionEnd": {} } }'''


SYSTEM_PROMPT = """You are RoadIQ's voice co-pilot for a Pilot Flying J truck driver who is
currently driving. Keep every response short and spoken-style (1-2 sentences) — the driver
cannot read a screen right now. Only talk about Pilot/Flying J stops, food, parking, showers,
fuel, and preferences using the tools provided. Never invent a location, price, or food option
that a tool did not return. If a tool has no data for something, say so plainly and suggest
what you can help with instead. If the driver mentions a food or shower preference, save it
using the savePreference tool without being asked."""


def _tool_schema(properties, required=None):
    return json.dumps({"type": "object", "properties": properties, "required": required or []})


class NovaSonicSession:
    """One browser WebSocket connection <-> one Nova Sonic bidirectional stream."""

    def __init__(self, ws):
        self.ws = ws
        self.client = None
        self.stream = None
        self.is_active = False
        self.prompt_name = str(uuid.uuid4())
        self.system_content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        self.pending_tool_name = None
        self.pending_tool_use_id = None
        self._recv_task = None

    def _init_client(self):
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{AWS_REGION}.amazonaws.com",
            region=AWS_REGION,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        self.client = BedrockRuntimeClient(config=config)

    async def start(self):
        self._init_client()
        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=MODEL_ID)
        )
        self.is_active = True

        prompt_start_event = self._build_prompt_start_event()
        init_events = [
            START_SESSION_EVENT,
            prompt_start_event,
            TEXT_CONTENT_START_EVENT % (self.prompt_name, self.system_content_name, "SYSTEM"),
            TEXT_INPUT_EVENT % (self.prompt_name, self.system_content_name, SYSTEM_PROMPT),
            CONTENT_END_EVENT % (self.prompt_name, self.system_content_name),
            AUDIO_CONTENT_START_EVENT % (self.prompt_name, self.audio_content_name),
        ]
        for ev in init_events:
            await self._send_raw(ev)
            await asyncio.sleep(0.05)

        self._recv_task = asyncio.create_task(self._process_responses())
        debug_print("Nova Sonic session started")

    def _build_prompt_start_event(self):
        tools = [
            {
                "toolSpec": {
                    "name": "getRouteStops",
                    "description": (
                        "Use this tool whenever the driver asks about Pilot or Flying J stops "
                        "coming up on their current route. It should be triggered for queries "
                        "such as:\n"
                        "- \"What stops are coming up?\"\n"
                        "- \"Where's the next Pilot?\"\n"
                        "- \"What are my options on this route?\"\n"
                        "- \"Is there a Flying J up ahead?\"\n"
                        "Returns real stop names, cities, and amenity flags (lounge, mobile fueling) "
                        "from the driver's actual corridor — never invent a stop not in the result."
                    ),
                    "inputSchema": {"json": _tool_schema({})},
                }
            },
            {
                "toolSpec": {
                    "name": "getFoodAtStop",
                    "description": (
                        "Use this tool whenever the driver asks about **food or restaurants** at a "
                        "stop. It should be triggered for queries such as:\n"
                        "- \"What food options are at my next stop?\"\n"
                        "- \"Is there a Subway on my route?\"\n"
                        "- \"Where can I get coffee?\"\n"
                        "- \"What can I eat up ahead?\"\n"
                        "Pass lob_id if the driver named a specific stop that getRouteStops already "
                        "returned; otherwise omit it and this checks the next stop. If the result has "
                        "no food listed, say so honestly — do not invent a restaurant."
                    ),
                    "inputSchema": {"json": _tool_schema({"lob_id": {"type": "integer", "description": "Stop location ID from getRouteStops, optional"}})},
                }
            },
            {
                "toolSpec": {
                    "name": "getParkingAndShower",
                    "description": (
                        "Use this tool whenever the driver asks about **parking availability or "
                        "shower wait times** at a stop. It should be triggered for queries such as:\n"
                        "- \"Is there parking at the next stop?\"\n"
                        "- \"How long is the shower wait?\"\n"
                        "- \"Can I find a spot to park overnight up ahead?\"\n"
                        "Pass lob_id if the driver named a specific stop, otherwise omit it to check "
                        "the next stop on the route."
                    ),
                    "inputSchema": {"json": _tool_schema({"lob_id": {"type": "integer", "description": "Stop location ID from getRouteStops, optional"}})},
                }
            },
            {
                "toolSpec": {
                    "name": "savePreference",
                    "description": (
                        "Use this tool whenever the driver states a **food or shower preference** "
                        "in conversation, even if they didn't explicitly ask you to remember it. It "
                        "should be triggered for statements such as:\n"
                        "- \"I always like to stop at Subway.\"\n"
                        "- \"I prefer a quick shower, I don't need anything fancy.\"\n"
                        "- \"Remember that I like Wendy's.\"\n"
                        "Do NOT trigger this for a plain question like \"Is there a Subway on my "
                        "route?\" — that is a lookup, not a stated preference. Call this silently; "
                        "do not ask the driver for permission first."
                    ),
                    "inputSchema": {"json": _tool_schema({
                        "food_preference": {"type": "string", "description": "Restaurant/food the driver prefers, optional"},
                        "shower_preference": {"type": "string", "description": "Shower frequency/cleanliness preference, optional"},
                    })},
                }
            },
        ]
        event = {
            "event": {
                "promptStart": {
                    "promptName": self.prompt_name,
                    "textOutputConfiguration": {"mediaType": "text/plain"},
                    "audioOutputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 24000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "voiceId": "matthew",
                        "encoding": "base64",
                        "audioType": "SPEECH",
                    },
                    "toolUseOutputConfiguration": {"mediaType": "application/json"},
                    "toolConfiguration": {"tools": tools},
                }
            }
        }
        return json.dumps(event)

    async def _send_raw(self, event_json):
        if not self.stream or not self.is_active:
            return
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode("utf-8"))
        )
        try:
            await self.stream.input_stream.send(chunk)
        except Exception as e:
            debug_print(f"send_raw error: {e}")

    async def send_audio_chunk(self, pcm16_bytes):
        """Forward one chunk of raw PCM16 (16kHz mono) audio from the browser mic to Nova Sonic."""
        blob = base64.b64encode(pcm16_bytes).decode("utf-8")
        event = AUDIO_EVENT_TEMPLATE % (self.prompt_name, self.audio_content_name, blob)
        await self._send_raw(event)

    async def _process_responses(self):
        """Read Nova Sonic's output stream and relay audio/text/tool events to the browser + tool handlers."""
        try:
            while self.is_active:
                output = await self.stream.await_output()
                result = await output[1].receive()
                if not (result.value and result.value.bytes_):
                    continue
                try:
                    data = json.loads(result.value.bytes_.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                event = data.get("event", {})

                if "audioOutput" in event:
                    audio_b64 = event["audioOutput"]["content"]
                    await self.ws.send(json.dumps({"type": "audio", "data": audio_b64}))

                elif "textOutput" in event:
                    text = event["textOutput"]["content"]
                    role = event["textOutput"].get("role", "")
                    if '"interrupted" : true' in text or '"interrupted":true' in text:
                        await self.ws.send(json.dumps({"type": "barge_in"}))
                    else:
                        await self.ws.send(json.dumps({"type": "transcript", "role": role, "text": text}))

                elif "toolUse" in event:
                    self.pending_tool_name = event["toolUse"]["toolName"]
                    self.pending_tool_use_id = event["toolUse"]["toolUseId"]
                    self._pending_tool_input = event["toolUse"].get("content", "{}")
                    debug_print(f"toolUse: {self.pending_tool_name}")

                elif event.get("contentEnd", {}).get("type") == "TOOL":
                    asyncio.create_task(self._run_tool_and_reply())

                elif "completionEnd" in event:
                    debug_print("completionEnd")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            debug_print(f"_process_responses error: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
        finally:
            self.is_active = False

    async def _run_tool_and_reply(self):
        tool_name = (self.pending_tool_name or "").lower()
        handler = TOOL_HANDLERS.get(tool_name)
        try:
            raw_args = self._pending_tool_input
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            args = {}

        if handler:
            try:
                result = handler(args)
            except Exception as e:
                result = {"error": str(e)}
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        content_name = str(uuid.uuid4())
        await self._send_raw(TOOL_CONTENT_START_EVENT % (self.prompt_name, content_name, self.pending_tool_use_id))
        tool_result_event = json.dumps({
            "event": {
                "toolResult": {
                    "promptName": self.prompt_name,
                    "contentName": content_name,
                    "content": json.dumps(result),
                }
            }
        })
        await self._send_raw(tool_result_event)
        await self._send_raw(CONTENT_END_EVENT % (self.prompt_name, content_name))
        # Surface tool activity to the browser UI (transparency, not required by the model)
        await self.ws.send(json.dumps({"type": "tool_call", "tool": tool_name, "args": args, "result": result}))

    async def close(self):
        if not self.is_active:
            return
        self.is_active = False
        if self._recv_task:
            self._recv_task.cancel()
        try:
            await self._send_raw(CONTENT_END_EVENT % (self.prompt_name, self.audio_content_name))
            await self._send_raw(PROMPT_END_EVENT % (self.prompt_name))
            await self._send_raw(SESSION_END_EVENT)
            if self.stream:
                await self.stream.input_stream.close()
        except Exception as e:
            debug_print(f"close error: {e}")


async def handle_connection(ws):
    debug_print(f"Browser connected: {ws.remote_address}")
    session = NovaSonicSession(ws)
    try:
        await session.start()
        await ws.send(json.dumps({"type": "ready"}))
        async for message in ws:
            if isinstance(message, bytes):
                await session.send_audio_chunk(message)
            else:
                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "audio":
                    await session.send_audio_chunk(base64.b64decode(msg["data"]))
                elif msg.get("type") == "stop":
                    break
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[voice_server] session error: {e}")
        if DEBUG:
            import traceback
            traceback.print_exc()
    finally:
        await session.close()
        debug_print("Session closed")


async def main():
    print(f"RoadIQ Voice Server — Nova Sonic bridge")
    print(f"Model: {MODEL_ID} | Region: {AWS_REGION}")
    print(f"Listening on ws://{WS_HOST}:{WS_PORT}")
    async with ws_serve(handle_connection, WS_HOST, WS_PORT, max_size=None):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nVoice server stopped.")
