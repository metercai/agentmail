#!/usr/bin/env python3
"""activate.py — OpenClaw 独立激活（步骤 4）。

使用产品激活码激活新系统，落盘 ~/.agentmail/{system_id}/amail_gateway.json。
独立激活保证 system_id 与 Hermes 不同 → 目录天然隔离。

用法:
  python3 activate.py --gateway https://amail.token.tm --code <产品激活码> --system-name <3-8字符>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

SYSNAME_RE = re.compile(r"^[a-z][a-z0-9_-]{2,7}$")


def validate_sysname(name: str) -> str:
    name = name.strip().lower()
    if not SYSNAME_RE.match(name):
        raise SystemExit("system-name must be lowercase letter + 2-7 more chars (a-z, 0-9, -, _)")
    return name


def activate(gateway_url: str, code: str, system_name: str) -> dict:
    """POST /api/v1/activate-system → {system_id, raw_key, domain, system_name}."""
    body = json.dumps({"code": code, "system_name": system_name}).encode()
    req = urllib.request.Request(
        f"{gateway_url.rstrip('/')}/api/v1/activate-system",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            pass
        hints = {
            410: "activation code already claimed — use a fresh code",
            409: f"identifier '{system_name}' already taken — choose another",
            429: f"rate limited — retry after {detail or 'some'}s",
        }
        raise SystemExit(f"activate failed (HTTP {e.code}): {hints.get(e.code, detail)}")
    if not resp.get("system_id") or not resp.get("raw_key"):
        raise SystemExit(f"activate response missing system_id/raw_key: {resp}")
    return resp


def save_gateway_config(gateway_url: str, resp: dict) -> Path:
    cfg = {
        "gateway_url": gateway_url.rstrip("/"),
        "admin_key": resp["raw_key"],
        "domain": resp.get("domain", ""),
        "system_id": resp["system_id"],
        "system_name": resp.get("system_name", ""),
    }
    sid = resp["system_id"]
    p = Path.home() / ".agentmail" / sid / "agentmail_gateway.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    # 环境提示（同 shell 后续步骤用）
    os.environ["AMAIL_SYSTEM_ID"] = sid
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenClaw 独立激活")
    ap.add_argument("--gateway", required=True, help="amail-gateway base URL")
    ap.add_argument("--code", required=True, help="产品激活码")
    ap.add_argument("--system-name", default=os.environ.get("AMAIL_SYSTEM_NAME", ""),
                    help="3-8 字符系统标识（与 Hermes 不同；默认取 AMAIL_SYSTEM_NAME）")
    args = ap.parse_args()
    if not args.system_name:
        ap.error("--system-name is required (or set AMAIL_SYSTEM_NAME in .env)")

    system_name = validate_sysname(args.system_name)
    resp = activate(args.gateway, args.code, system_name)
    p = save_gateway_config(args.gateway, resp)
    print(f"activated: system_id={resp['system_id']} system_name={resp.get('system_name')} "
          f"domain={resp.get('domain')} config={p}")
    print(f"export AMAIL_SYSTEM_ID={resp['system_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
