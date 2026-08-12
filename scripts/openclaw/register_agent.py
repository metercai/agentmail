#!/usr/bin/env python3
"""register_agent.py — OpenClaw agent 注册到 amail（步骤 6）。

注册链（register_email → 已存在更新 webhook → manager 白名单 → activate_address）
走公共核心 agentmail_base.register_agent_email（Hermes/OpenClaw 共用）：
  1. 计算 email（main → agent@{domain}，其余 {agentId}@{domain}；共享域加 .{system_name}）
  2. 注册链（公共，幂等）→ api_key
  3. 落盘 agents/<agentId>/config.json + agents.json 注册表

用法:
  python3 register_agent.py --agent main --manager admin@x.com
  python3 register_agent.py --all --manager admin@x.com    # 注册全部 OpenClaw agents
  python3 register_agent.py --agent work --manager admin@x.com --system-id SID
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "openclaw"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "hermes"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import amail_base as _base            # noqa: E402
import agentmail_tools as _tools      # noqa: E402


def email_for_agent(agent_id: str, domain: str, system_name: str) -> str:
    """地址派生（公共核心 email_for_agent；OpenClaw 默认名 main → agent，
    其余保持原名；非法字符清洗含 '.' → '_'）。"""
    return _base.email_for_agent(agent_id, domain, system_name,
                                 default_aliases=("main",))


def discover_openclaw_agents() -> list:
    """列出 OpenClaw agents（openclaw agents list --json）；失败回退 [main]。"""
    try:
        out = subprocess.run(["openclaw", "agents", "list", "--json"],
                             capture_output=True, timeout=15, text=True)
        if out.returncode == 0 and out.stdout.strip():
            data = json.loads(out.stdout)
            agents = data if isinstance(data, list) else data.get("agents", [])
            ids = [a.get("id") or a.get("agentId") for a in agents]
            if ids:
                return ids
    except Exception:
        pass
    return ["main"]


def register_one(client, system_id: str, agent_id: str, email: str,
                 webhook_url: str, webhook_secret: str, manager_address: str,
                 domain: str, system_name: str, gateway_url: str) -> dict:
    """注册单个 agent：核心链走公共 register_agent_email，平台部分只做本地落盘组装。"""
    reg = _base.register_agent_email(
        client, system_id, email, webhook_url, webhook_secret,
        manager_address, mx_domain=domain,
    )
    api_key = reg.get("api_key", "")

    cfg = {
        "email": email,
        "gateway_url": gateway_url,
        "domain": domain,
        "system_id": system_id,
        "system_name": system_name,
        "manager_address": manager_address,
        "api_key": api_key,
        "mx_domain": domain,
    }
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser(description="注册 OpenClaw agent 到 amail")
    ap.add_argument("--agent", default="")
    ap.add_argument("--all", action="store_true", help="注册全部 OpenClaw agents")
    ap.add_argument("--manager", default="", help="manager_address（审批联系人）；缺省读 AMAIL_MANAGER 环境变量")
    ap.add_argument("--system-id", default=os.environ.get("AMAIL_SYSTEM_ID", ""))
    args = ap.parse_args()

    if not args.agent and not args.all:
        raise SystemExit("need --agent <id> or --all")
    if args.agent and args.all:
        raise SystemExit("--agent and --all are mutually exclusive")

    system_id = args.system_id or _base.detect_system_id()
    gw = _base.load_gateway_config(system_id)
    if not gw:
        raise SystemExit(f"gateway config not found (agentmail_gateway.json / amail_gateway.json) for {system_id} — run activate.py first")
    manager = args.manager or os.environ.get("AMAIL_MANAGER", "")
    if not manager:
        raise SystemExit("need --manager <addr> or AMAIL_MANAGER env (审批联系人)")
    mode = _base.load_mode(system_id)
    print(f"system_id={system_id} mode={mode.get('mode')} domain={gw.get('domain')}")

    # admin client（register_email/activate_address 全在 _GatewayClient）
    client = _tools._GatewayClient(gw["gateway_url"], gw.get("admin_key", ""))

    agents = [args.agent] if args.agent else discover_openclaw_agents()
    if not agents:
        agents = ["main"]

    webhook_url = mode.get("bridge_url", "") if mode.get("mode") == "push" else ""
    registry = _base.load_agents_registry(system_id)
    created = 0

    for agent_id in agents:
        email = email_for_agent(agent_id, gw["domain"], gw.get("system_name", ""))
        webhook_secret = secrets.token_hex(32)
        cfg = register_one(
            client, system_id, agent_id, email,
            webhook_url, webhook_secret, manager,
            gw["domain"], gw.get("system_name", ""), gw["gateway_url"],
        )
        if cfg["api_key"]:
            _base.save_agent_config(agent_id, cfg, system_id)
            registry[email] = agent_id
            created += 1
            print(f"  ✓ {agent_id} → {email} (api_key ok)")
        else:
            print(f"  ⚠ {agent_id} → {email} registered but no api_key (activation pending)")

    _base.save_agents_registry(system_id, registry)
    print(f"registered: {created}/{len(agents)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
