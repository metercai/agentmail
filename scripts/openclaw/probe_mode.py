#!/usr/bin/env python3
"""probe_mode.py — 探测 push/pull 模式（步骤 5）。

判定：amail-gateway（云端）能否直连 OpenClaw 主机 bridge 端口。
本机为内网/NAT 时必然 pull。结果写 ~/.agentmail/{sid}/mode.json。

用法:
  python3 probe_mode.py [--system-id SID] [--bridge-port 8799] [--ssh-target root@host]
  # --ssh-target 提供时从网关侧探测；否则尝试本机公网可达性判定
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "openclaw"))
import amail_base as _base  # noqa: E402


def local_public_ip() -> str:
    """本机公网出口 IP（无则空串 = 内网/无外网）。"""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "http://ip.3322.net"):
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=4) as r:
                ip = r.read().decode().strip()
                if ip:
                    return ip
        except Exception:
            continue
    return ""


def probe_from_gateway(ssh_target: str, host: str, port: int) -> bool:
    """从云端 gateway（SSH）探测 host:port 可达性。"""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
           ssh_target, f"nc -z -w3 {host} {port} && echo REACHABLE || echo UNREACHABLE"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=15, text=True)
        return "REACHABLE" in out.stdout
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="探测 push/pull 模式")
    ap.add_argument("--system-id", default=os.environ.get("AMAIL_SYSTEM_ID", ""))
    ap.add_argument("--bridge-port", type=int, default=8799)
    ap.add_argument("--ssh-target", default=os.environ.get("AMAIL_SSH_TARGET", ""),
                    help="云端 gateway SSH 目标（探测用；缺省读 AMAIL_SSH_TARGET 环境变量）")
    args = ap.parse_args()

    system_id = args.system_id or _base.detect_system_id()
    if not system_id:
        raise SystemExit("system_id not found — run activate.py first")

    public_ip = local_public_ip()
    reachable = False
    detail = f"local_public_ip={public_ip or '(none/inner-net)'}"
    if public_ip and args.ssh_target:
        reachable = probe_from_gateway(args.ssh_target, public_ip, args.bridge_port)
        detail += f" probe_from_gateway={reachable}"
    elif public_ip:
        detail += " (no ssh-target — assume pull; set AMAIL_SSH_TARGET to probe)"

    mode = "push" if reachable else "pull"
    mode_cfg = {
        "mode": mode,
        "bridge_url": f"http://127.0.0.1:{args.bridge_port}/hook" if mode == "push" else "",
        "bridge_port": args.bridge_port,
        "probe": detail,
        "checked_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    _base.save_mode(system_id, mode_cfg)
    print(f"mode={mode} ({detail}) -> ~/.agentmail/{system_id}/mode.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
