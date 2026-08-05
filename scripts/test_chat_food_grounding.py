"""Test that the chat tab can now answer food-related questions with real data."""
import requests
import urllib3
urllib3.disable_warnings()

BASE = "http://localhost:5002"

questions = [
    "What food options are available at my next stop?",
    "Is there a Subway on my route?",
    "Where can I get coffee along the way?",
]

for q in questions:
    print("=" * 70)
    print(f"Q: {q}")
    print("=" * 70)
    r = requests.post(f"{BASE}/api/ai", json={"mode": "chat", "message": q}, verify=False, timeout=60)
    d = r.json()
    print(f"Status: {r.status_code} | source: {d.get('source')}")
    print(f"A: {d.get('text')}\n")
