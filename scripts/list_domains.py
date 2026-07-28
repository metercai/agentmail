#!/usr/bin/env python3
"""List domains for a system. Used by integrate.sh Step 3 domain selection."""
import sys, json, os
import urllib.request

gw = os.environ.get("GATEWAY_URL", "")
ak = os.environ.get("ADMIN_KEY", "")
sid = os.environ.get("SYSTEM_ID", "")

req = urllib.request.Request(f"{gw}/api/v1/admin/systems/{sid}/domains",
    headers={"X-Api-Key": ak})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
except:
    data = []

# Bare domains only (no @)
entries = [d for d in data if "@" not in d.get("domain", "")]
if entries:
    print("  Existing domains:")
    for i, d in enumerate(entries, 1):
        status = " (inactive)" if not d.get("is_active") else ""
        print(f"    [{i}] {d['domain']}{status}")
    print(f"    [{len(entries)+1}] Enter a new domain")
else:
    print("  No existing domains — enter a new one")
