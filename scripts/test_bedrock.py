"""Quick test: is Bedrock working through server.py?"""
import requests
import urllib3
urllib3.disable_warnings()

r = requests.post("http://localhost:5000/api/ai",
    json={"mode": "chat", "message": "Say hello in one sentence"},
    verify=False)
d = r.json()
print(f"Source: {d['source']}")
print(f"Text: {d['text']}")
