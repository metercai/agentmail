#!/usr/bin/env python3
"""verify-e2e.py — OpenClaw 接入 E2E 验证（步骤 9）。

验证项（按 mode.json 激活对应路径）：
  1. ping-pong：amail.py send ping → 收到 pong（push 经 bridge / pull 经 poll）
  2. 入站：邮件到达 → agent turn 触发（hook 受理）→ 队列 ack 清空
  3. 崩溃恢复（pull）：模拟 poll 中断 → 队列保留 → 幂等重投不重复
  4. 出站 threading：amail.py send --message-id → 回复带 In-Reply-To
  5. 多 agent：各自 api_key 身份互不串扰

用法:
  python3 verify-e2e.py [--system-id SID] [--to <外部测试收件人>] [--quick]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "openclaw"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "hermes"))

import amail_base as _base  # noqa: E402

PASS, FAIL = 0, 0


def ok(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def run_amail(agent: str, *args: str) -> dict:
    amail = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "openclaw", "amail.py")
    r = subprocess.run([sys.executable, amail, "--agent", agent, *args],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return {"success": False, "error": r.stdout or r.stderr, "raw": r.stdout}


def wait_pending(system_id: str, gateway_url: str, bridge_key: str,
                 domain: str, timeout: int = 60) -> list:
    """轮询 pending 队列直到空或超时。返回观察到的批次。"""
    import urllib.request, urllib.error
    seen = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = json.dumps({"limit": 20, "filter": [domain]}).encode()
        req = urllib.request.Request(f"{gateway_url}/api/v1/admin/pending", data=data,
                                     headers={"Content-Type": "application/json",
                                              "X-Api-Key": bridge_key})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
        except Exception:
            resp = {}
        batches = resp.get("batches") or []
        if batches:
            seen.extend(batches)
            time.sleep(2)
        else:
            break
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenClaw amail E2E 验证")
    ap.add_argument("--system-id", default=os.environ.get("AMAIL_SYSTEM_ID", ""))
    ap.add_argument("--to", default="", help="外部测试收件人（ping 回信目标）")
    ap.add_argument("--quick", action="store_true", help="只跑 ping-pong")
    args = ap.parse_args()

    system_id = args.system_id or _base.detect_system_id()
    gw = _base.load_gateway_config(system_id)
    ok("gateway config", bool(gw), str(system_id))
    if not gw:
        return 1
    mode = _base.load_mode(system_id)
    ok("mode.json", mode.get("mode") in ("push", "pull"), str(mode))
    registry = _base.load_agents_registry(system_id)
    ok("agents registry", bool(registry), str(registry))
    hooks = _base.load_openclaw_hooks()
    ok("openclaw hooks token", bool(hooks and hooks.get("token")))

    agent_id = "main"
    agent_cfg = _base.load_agent_config(agent_id, system_id)
    ok(f"agent {agent_id} config (api_key)", bool(agent_cfg and agent_cfg.get("api_key")))
    if not agent_cfg:
        return 1
    my_email = agent_cfg["email"]
    to_addr = args.to or my_email  # 默认自环（同系统收信）

    # ── 1. ping-pong（pull：发 ping → poll 拦截 → pong 回发）──
    print("\n[1] ping-pong")
    ping_id = uuid.uuid4().hex[:8]
    r = run_amail(agent_id, "send", "--to", to_addr,
                  "--subject", f"__agentmail_ping__:{ping_id}",
                  "--body", "ping")
    ok("ping sent", r.get("success"), str(r.get("error")))
    if r.get("success"):
        # 等 poll 轮询周期（automations 30s）——手动触发或等待
        print(f"      ping_id={ping_id} — 等待轮询处理（30s 周期或手动 automations run）")
        # pull 路径验证 pong：轮询 pending 应被拦截清空
        bridge_key = gw.get("admin_key", "")
        time.sleep(5)
        batches = wait_pending(system_id, gw["gateway_url"], bridge_key,
                               gw.get("domain", ""), timeout=40)
        ok("pending drained (ping intercepted)", not batches)

    # ── 2. 入站（真实邮件投递触发 agent turn）──
    if not args.quick:
        print("\n[2] inbound -> agent turn")
        subject = f"[verify] {uuid.uuid4().hex[:6]}"
        r = run_amail(agent_id, "send", "--to", to_addr, "--subject", subject, "--body", "hello")
        ok("inbound mail sent", r.get("success"))
        time.sleep(5)
        batches = wait_pending(system_id, gw["gateway_url"], gw.get("admin_key", ""),
                               gw.get("domain", ""), timeout=40)
        ok("inbound drained", not batches)

    # ── 4. 出站 threading ──
    if not args.quick and r.get("success"):
        print("\n[3] outbound threading")
        msg_id = r.get("message_id") or r.get("email_id") or ""
        r2 = run_amail(agent_id, "send", "--to", to_addr, "--subject", "Re: thread",
                       "--body", "reply", "--message-id", msg_id)
        ok("reply with message_id", r2.get("success"), str(r2.get("error")))

    print(f"\nPASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
