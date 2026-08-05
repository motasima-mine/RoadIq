"""List all available Bedrock models in your AWS account."""
import os
import ssl
import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["AWS_CA_BUNDLE"] = ""

client = boto3.client(
    "bedrock",
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    verify=False,
)

print("Available foundation models (Claude + Nova):\n")
resp = client.list_foundation_models()
for model in resp["modelSummaries"]:
    mid = model["modelId"]
    if any(x in mid.lower() for x in ["claude", "nova", "titan"]):
        status = model.get("modelLifecycle", {}).get("status", "?")
        print(f"  {mid:55s}  [{status}]")
