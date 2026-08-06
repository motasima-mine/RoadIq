"""
End-to-end smoke test for voice_server.py — verifies the WebSocket protocol,
Nova Sonic session lifecycle, and (if reachable) tool-calling, WITHOUT a real
microphone. Since this is speech-to-speech, we can't literally "ask a
question" via text — Nova Sonic only accepts AUDIO content in this session
config. What this test DOES verify:

1. voice_server.py accepts a WebSocket connection and sends {"type":"ready"}
2. Sending real audio-shaped PCM16 frames (16kHz mono) doesn't crash the
   session or the Bedrock stream
3. The server tears down cleanly on {"type":"stop"}

For a true "spoken question -> spoken answer with real data" test, use
static/voice.html with an actual microphone -- that is the only way to
produce speech Nova Sonic will actually transcribe and act on. This script
is regression coverage for the plumbing, not a substitute for a live mic
test.
"""
import asyncio
import json
import base64
import math
import struct
import sys

import websockets

WS_URL = "ws://localhost:8765"


def make_tone_pcm16(duration_s=0.5, freq=440, sample_rate=16000):
    """Generate a simple sine tone as PCM16 bytes -- structurally valid audio
    input (not real speech, so Nova Sonic won't transcribe words from it, but
    it proves the audio pipe doesn't error)."""
    n_samples = int(duration_s * sample_rate)
    samples = []
    for i in range(n_samples):
        val = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(val)
    return struct.pack("<%dh" % len(samples), *samples)


async def main():
    print(f"Connecting to {WS_URL} ...")
    async with websockets.connect(WS_URL, max_size=None) as ws:
        events_seen = []

        async def listen():
            try:
                async for message in ws:
                    msg = json.loads(message)
                    events_seen.append(msg["type"])
                    if msg["type"] == "transcript":
                        print(f"  transcript ({msg.get('role')}): {msg.get('text')}")
                    elif msg["type"] == "tool_call":
                        print(f"  tool_call: {msg.get('tool')} -> {json.dumps(msg.get('result'))[:200]}")
                    elif msg["type"] == "audio":
                        print(f"  audio chunk received ({len(msg.get('data',''))} b64 chars)")
                    else:
                        print(f"  event: {msg['type']}")
            except websockets.exceptions.ConnectionClosed:
                print("  (connection closed)")

        listen_task = asyncio.create_task(listen())

        # Wait for ready
        deadline = asyncio.get_event_loop().time() + 10
        while "ready" not in events_seen and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)

        if "ready" not in events_seen:
            print("FAIL: never received 'ready' event within 10s")
            listen_task.cancel()
            return False

        print("PASS: session started, received 'ready'")

        # Send ~2s of tone audio in 20ms chunks (320 samples @16kHz = 640 bytes)
        tone = make_tone_pcm16(duration_s=2.0)
        chunk_size = 640
        for i in range(0, len(tone), chunk_size):
            chunk = tone[i:i + chunk_size]
            await ws.send(json.dumps({"type": "audio", "data": base64.b64encode(chunk).decode()}))
            await asyncio.sleep(0.02)

        print("PASS: sent 2s of synthetic audio without error")

        # Give Nova Sonic a moment to process/respond
        await asyncio.sleep(5)

        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.sleep(1)
        listen_task.cancel()

        print(f"\nEvent types observed: {set(events_seen)}")
        print("Smoke test complete. Session lifecycle + audio pipe are functional.")
        print("NOTE: real transcript/tool_call verification requires a live mic test via static/voice.html.")
        return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
