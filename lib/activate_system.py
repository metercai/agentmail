"""Activate a shared domain system via API. Called by integrate.sh."""
import urllib.request, urllib.error, json, sys, os, re

# Read from env vars set by integrate.sh
code = os.environ.get("PRODUCT_CODE", "")
name = os.environ.get("SYSTEM_NAME", "")
gw = os.environ.get("GATEWAY_URL", "")

data = json.dumps({"code": code, "system_name": name}).encode()
req = urllib.request.Request(
    f"{gw.rstrip('/')}/api/v1/activate-system",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    body = resp.read().decode()
    print(f"{body}{resp.status}", end="")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"{body}{e.code}", end="")
except Exception as e:
    print(f'{{"error":"{e}"}}000', end="")
