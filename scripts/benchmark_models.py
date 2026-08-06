"""
One-off benchmark: compare candidate Bedrock models on a realistic RoadIQ
chat prompt, measuring latency and token usage side by side.

Not a permanent part of the app -- run manually when re-evaluating the
BEDROCK_MODEL_ID choice. Uses the real driver_chat.txt prompt shape with
demo data so the comparison reflects actual RoadIQ token volume.
"""
import os
import time
import boto3
import botocore.config
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

PROMPT = """You are RoadIQ, an AI co-pilot inside the Pilot Flying J driver app. You help truck drivers make stop decisions while on the road.

DRIVER CONTEXT:
- Name: James
- Route: Nashville, TN -> Atlanta, GA
- Fuel remaining: 140 miles worth
- Loyalty tier: Elite
- Vehicle health: good

AVAILABLE PILOT STOPS ON THIS ROUTE:
- Pilot Knoxville #198 (Knoxville, TN) - Parking: 78% available; Shower wait: 8 min; Food: Subway, Pilot Coffee, DoorDash; Diesel: $3.42/gal
- Pilot Chattanooga #212 (Chattanooga, TN) - Parking: 45% available; Shower wait: 15 min; Food: Hand Roped Pizza, GrubHub; Diesel: $3.45/gal
- Flying J Calhoun #87 (Calhoun, GA) - Parking: 92% available; Shower wait: 3 min; Food: Cold Brew Coffee, Fresh Salads; Diesel: $3.40/gal

DRIVER'S MESSAGE:
"Is there a Subway on my route, and where should I stop for fuel?"

YOUR TASK:
Respond to the driver's question or request. Be specific - recommend an actual Pilot stop from the list above when relevant.

RULES:
- Keep responses under 120 words
- Address the driver by first name
- Be conversational - short sentences, no jargon
- Only reference stops and data provided above - never invent locations, prices, or availability numbers
- If the driver asks about something not covered by the data (weather, traffic, ETA), say you don't have that info and suggest what you CAN help with
- Always tie recommendations back to a concrete Pilot stop with its real stats
- If fuel is below 150 miles remaining, proactively flag urgency
- Mention loyalty perks when relevant to the driver's tier
"""

CANDIDATES = [
    "amazon.nova-lite-v1:0",       # current
    "amazon.nova-micro-v1:0",      # cheapest/fastest text-only
    "us.amazon.nova-2-lite-v1:0",  # newer nova-lite, needs inference profile
    "amazon.nova-pro-v1:0",        # stronger nova
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",   # fast+cheap claude, inference profile
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # "better" claude, inference profile
]


def bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        verify=False,
        config=botocore.config.Config(retries={"max_attempts": 2, "mode": "standard"}),
    )


def run_one(client, model_id):
    start = time.perf_counter()
    try:
        r = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": PROMPT}]}],
            inferenceConfig={"maxTokens": 200, "temperature": 0.7},
        )
        elapsed = time.perf_counter() - start
        text = r["output"]["message"]["content"][0]["text"]
        usage = r.get("usage", {})
        return {
            "ok": True,
            "elapsed_s": round(elapsed, 2),
            "input_tokens": usage.get("inputTokens"),
            "output_tokens": usage.get("outputTokens"),
            "text": text,
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {"ok": False, "elapsed_s": round(elapsed, 2), "error": str(e)[:200]}


def main():
    client = bedrock_client()
    print(f"{'MODEL':45s} | {'OK':4s} | {'TIME(s)':8s} | {'IN_TOK':7s} | {'OUT_TOK':7s}")
    print("-" * 90)
    results = []
    for model_id in CANDIDATES:
        r = run_one(client, model_id)
        results.append((model_id, r))
        if r["ok"]:
            print(f"{model_id:45s} | {'Y':4s} | {r['elapsed_s']:<8} | {r['input_tokens']:<7} | {r['output_tokens']:<7}")
        else:
            print(f"{model_id:45s} | {'N':4s} | {r['elapsed_s']:<8} | ERROR: {r['error']}")

    print("\n--- Sample outputs ---")
    for model_id, r in results:
        if r["ok"]:
            print(f"\n[{model_id}]\n{r['text']}")


if __name__ == "__main__":
    main()
