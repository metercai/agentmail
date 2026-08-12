#!/usr/bin/env python3
"""amail_openclaw_bridge.py — OpenClaw 入站 push bridge。

amail-gateway 推送（webhook_url 非空时）→ 本服务：
  1. HMAC 验签（X-Webhook-Signature，webhook_secret）
  2. 按收件地址路由 agent → dispatch_to_hooks（共享投递链）
  3. ping-pong 拦截（__agentmail_ping__ → __agentmail_pong__）

仅 push 模式启用（mode.json）。pull 模式部署不启动本服务。
共享逻辑（富化/组装/投递/ping-pong/http）统一在 amail_base。

用法:
  python3 amail_openclaw_bridge.py [--port 8799] [--system-id SID]
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "hermes"))

import amail_base as _base            # noqa: E402


def verify_hmac(secret: str, body: bytes, signature: str, timestamp: str) -> bool:
    """对照 amail webhook.rs sign_payload：HMAC-SHA256(body, secret)，hex 比较。
    timestamp 参与与否以实现核对为准（当前按 body-only 校验）。"""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class BridgeHandler(BaseHTTPRequestHandler):
    bridge = None  # 由 serve() 注入

    def log_message(self, *a):  # 静默默认日志
        pass

    def _send_json(self, code: int, obj: dict):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/hook":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "invalid body"})
            return

        # ── 1. HMAC 验签 ──
        sig = self.headers.get("X-Webhook-Signature", "")
        ts = self.headers.get("X-Mailrelay-Timestamp", "")
        secret = self.bridge["webhook_secret"]
        if not verify_hmac(secret, body, sig, ts):
            self._send_json(401, {"error": "bad signature"})
            return

        # ── ping-pong 拦截（E2E 验证，同 Hermes 补丁语义）──
        subject = payload.get("subject", "")
        if _base.is_ping(subject):
            pid = _base.ping_id(subject)
            pong_ok = _base.send_pong(payload, pid)
            self._send_json(200, {"pong": pid, "status": "pong_sent" if pong_ok else "pong_failed"})
            return
        if _base.is_pong(subject):
            self._send_json(200, {"pong": subject.split(":", 1)[1].strip(), "status": "pong_returned"})
            return

        # ── 2. 路由 + 共享投递链 ──
        email = payload.get("to", "")
        if isinstance(email, list):
            email = email[0] if email else ""
        agent_id = _base.agent_for_email(self.bridge["registry"], email)
        if not agent_id:
            self._send_json(200, {"status": "no_agent", "email": email})
            return
        try:
            resp = _base.dispatch_to_hooks(
                self.bridge["hooks_url"], self.bridge["hooks_token"], agent_id,
                payload, idempotency_key=f"amail:{payload.get('mail_id', '')}",
                extra_system_prompt=self.bridge.get("extra_system_prompt", ""),
                headers=dict(self.headers),
                system_id=self.bridge["system_id"],
            )
        except RuntimeError as e:
            self._send_json(200, {"status": "no_local_config", "agent": agent_id, "detail": str(e)})
            return
        if resp.get("status") in (200, 201, 202):
            self._send_json(200, {"status": "accepted", "runId": resp.get("runId", "")})
        else:
            self._send_json(502, {"status": "hook_rejected", "detail": resp})


def serve(system_id: str, port: int, hooks_url: str) -> None:
    gw = _base.load_gateway_config(system_id)
    if not gw:
        raise SystemExit(f"gateway config not found (agentmail_gateway.json) for {system_id}")
    hooks = _base.load_openclaw_hooks()
    if not hooks:
        raise SystemExit("OpenClaw hooks not configured (token missing)")
    registry = _base.load_agents_registry(system_id)

    bridge = {
        "system_id": system_id,
        "webhook_secret": gw.get("webhook_secret", ""),
        "registry": registry,
        "hooks_url": hooks_url,
        "hooks_token": hooks["token"],
        "extra_system_prompt": "",  # board 角色文本注入点（P1 board 接入后填充）
    }
    BridgeHandler.bridge = bridge
    srv = ThreadingHTTPServer(("127.0.0.1", port), BridgeHandler)
    print(f"bridge listening on 127.0.0.1:{port} (system {system_id}, mode=push)")
    srv.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenClaw amail push bridge")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--system-id", default=os.environ.get("AMAIL_SYSTEM_ID", ""))
    ap.add_argument("--hooks-url", default="http://127.0.0.1:18789/hooks/agent")
    args = ap.parse_args()
    system_id = args.system_id or _base.detect_system_id()
    serve(system_id, args.port, args.hooks_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
