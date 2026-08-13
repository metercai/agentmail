#!/usr/bin/env python3
"""amail-poll.py — OpenClaw 入站 pull 轮询。

amail-gateway 侧 webhook_url 空 → 邮件入 pending_deliveries 队列。
本脚本由 OpenClaw automations 命令负载定时触发：
  1. POST /api/v1/admin/pending（bridge key）→ batches（按 payload hash 分组）
  2. 每 batch：按收件地址查 agent → dispatch_to_hooks（共享投递链）
     （idempotencyKey 防重投）
  3. 全部受理后 POST /api/v1/admin/pending/ack
  4. 空队列输出 NO_REPLY（automations 静默令牌）

共享逻辑（富化/组装/投递/ping-pong/http）统一在 amail_base。

用法（由 automations 调用）:
  python3 amail-poll.py [--system-id SID] [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "hermes"))

import amail_base as _base            # noqa: E402


def poll_once(system_id: str, gateway_url: str, bridge_key: str, domain: str,
              hooks_token: str, registry: dict, limit: int,
              hooks_url: str = "http://127.0.0.1:18789/hooks/agent") -> int:
    """拉取并投递一轮。返回处理邮件数。"""
    resp = _base.http_post(f"{gateway_url}/api/v1/admin/pending",
                           {"limit": limit, "filter": [domain]}, api_key=bridge_key)
    batches = resp.get("batches") or []
    if not batches:
        print("NO_REPLY")
        return 0

    ack_ids: list = []
    for batch in batches:
        body = batch.get("body") or {}
        deliveries = batch.get("deliveries") or []
        if not deliveries:
            continue
        # ── ping-pong 拦截（E2E 验证，同 Hermes 补丁语义）──
        # Unified ping/pong interception (shared implementation —
        # identical conditions on Hermes preprocess and OpenClaw poll).
        pp = _base.handle_ping_pong(body, _base.send_pong)
        if pp == "ping":
            for d in deliveries:
                ack_ids.append(d.get("id"))
            print(f"  ping-pong: {_base.ping_id(body.get('subject',''))} intercepted ({len(deliveries)} delivery)")
            continue
        if pp == "pong":
            for d in deliveries:
                ack_ids.append(d.get("id"))
            print(f"  pong returned: {body.get('subject','').split(':', 1)[1].strip()}")
            continue

        # 该批所有收件人 → 每个 agent 各投一次（按 delivery 逐条，保证 agentId 正确）
        for d in deliveries:
            email = d.get("email", "")
            agent_id = _base.agent_for_email(registry, email)
            if not agent_id:
                print(f"  ⚠ no agent for {email} — skipping", file=sys.stderr)
                ack_ids.append(d.get("id"))
                continue
            try:
                hook_resp = _base.dispatch_to_hooks(
                    hooks_url, hooks_token, agent_id, dict(body),
                    idempotency_key=f"amail:{d.get('id')}",
                    system_id=system_id,
                )
            except RuntimeError as e:
                print(f"  ⚠ {email}: {e} — skipping", file=sys.stderr)
                ack_ids.append(d.get("id"))
                continue
            if hook_resp.get("status") in (200, 201, 202):
                ack_ids.append(d.get("id"))
                print(f"  ✓ {email} -> agent:{agent_id} (run {hook_resp.get('runId', '')})")
            else:
                print(f"  ✗ {email} -> hook rejected: {hook_resp.get('error', hook_resp.get('status'))}",
                      file=sys.stderr)
                # 不 ack —— 下轮重投；幂等 key 保证不重复处理

    # ack 已受理的 delivery
    if ack_ids:
        for i in range(0, len(ack_ids), 500):
            chunk = ack_ids[i:i + 500]
            ack = _base.http_post(f"{gateway_url}/api/v1/admin/pending/ack",
                                  {"ids": chunk}, api_key=bridge_key)
            print(f"  ack {len(chunk)}: {ack.get('acked', ack.get('status'))}")
    return len(batches)


def main() -> int:
    ap = argparse.ArgumentParser(description="amail pull 轮询")
    ap.add_argument("--system-id", default=os.environ.get("AMAIL_SYSTEM_ID", ""))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--hooks-url", default="http://127.0.0.1:18789/hooks/agent")
    args = ap.parse_args()

    system_id = args.system_id or _base.detect_system_id()
    gw = _base.load_gateway_config(system_id)
    if not gw:
        print("NO_REPLY")
        return 1
    mode = _base.load_mode(system_id)
    if mode.get("mode") != "pull":
        # push 模式不该跑轮询 —— 静默
        print("NO_REPLY")
        return 0

    # bridge-scope key（poll 配置里找，找不到则用 admin_key 兜底——服务端接受 system scope）
    poll_cfg_path = _base.system_dir(system_id) / "poll.json"
    bridge_key = ""
    if poll_cfg_path.is_file():
        try:
            bridge_key = json.loads(poll_cfg_path.read_text()).get("bridge_key", "")
        except Exception:
            pass
    bridge_key = bridge_key or gw.get("admin_key", "")

    hooks = _base.load_openclaw_hooks()
    if not hooks:
        print("NO_REPLY")
        return 1

    registry = _base.load_agents_registry(system_id)
    try:
        poll_once(system_id, gw["gateway_url"], bridge_key, gw.get("domain", ""),
                  hooks["token"], registry, args.limit, args.hooks_url)
    except Exception as e:
        print(f"poll error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
