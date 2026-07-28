#!/usr/bin/env python3
"""Gateway API client — shared by setup_system.py and deploy_bridge.py."""
import json, urllib.request, urllib.error
from typing import Dict, Optional


def whoami(gw: str, ak: str) -> dict:
    """GET /api/v1/whoami — return API key metadata."""
    req = urllib.request.Request(f"{gw}/api/v1/whoami",
        headers={"X-Api-Key": ak})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def create_api_key(gw: str, ak: str, system_id: str, email: str,
                   scopes: list, category: str) -> dict:
    """POST /api/v1/admin/api-keys. Returns {raw_key, error, detail, status}."""
    data = json.dumps({
        "system_id": system_id, "email_address": email,
        "scopes": scopes, "category": category,
    }).encode()
    req = urllib.request.Request(f"{gw}/api/v1/admin/api-keys", data=data,
        headers={"X-Api-Key": ak, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            return {"raw_key": "", "error": body.get("error", ""),
                    "detail": body.get("detail", ""), "status": e.code}
        except Exception:
            return {"raw_key": "", "error": f"HTTP {e.code}", "status": e.code}
    except Exception as e:
        return {"raw_key": "", "error": str(e)}
