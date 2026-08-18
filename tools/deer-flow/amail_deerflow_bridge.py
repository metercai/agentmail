#!/usr/bin/env python3
"""amail_deerflow_bridge.py — DeerFlow 入站接收端(bridge 转发目标)。

amail-bridge(拉取器,透明转发)→ 本服务:
  1. HMAC 验签(X-Webhook-Signature,webhook_secret)
  2. 共享入站预处理 process_inbound_mail(身份/persona/富化/存储,
     最后一步 ping/pong 拦截——pong 回环走全链末端)
  3. 未拦截 → 按收件地址路由 agent → dispatch_to_deerflow(LangGraph API)

接受路径: /hook 与 /webhooks/amail-inbound(bridge 全 URL 路由可指向
任意端点,本服务兼容两路径;pull/push 两模式均可用)。

与 amail_openclaw_bridge.py 同构,仅投递段不同:
  - OpenClaw: dispatch_to_hooks → POST /hooks/agent
  - DeerFlow: dispatch_to_deerflow → POST /api/runs/wait(LangGraph)

共享逻辑(富化/组装/ping-pong/http)统一在共享核心 agentmail_base。

用法:
  python3 amail_deerflow_bridge.py [--port 8798] [--system-id SID]
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))          # tools/deer-flow/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/

import amail_base as _base            # noqa: E402  (DeerFlow 适配层)


def verify_hmac(secret: str, body: bytes, signature: str, timestamp: str) -> bool:
    """对照 amail webhook.rs sign_payload：HMAC-SHA256(body, secret)，hex 比较。"""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class DeerFlowBridgeHandler(BaseHTTPRequestHandler):
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
        if self.path not in ("/hook", "/webhooks/amail-inbound"):
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

        # ── 2. 共享入站预处理(与 Hermes/OpenClaw 同一实现)──
        # 身份解析 → persona → 富化 → 存储,最后一步 ping/pong 拦截。
        email = payload.get("to", "")
        if isinstance(email, list):
            email = email[0] if email else ""
        agent_id = _base.agent_for_email(self.bridge["registry"], email)
        if not agent_id:
            self._send_json(200, {"status": "no_agent", "email": email})
            return
        try:
            _base.set_agent_context(agent_id, self.bridge["system_id"])
        except Exception as e:
            self._send_json(200, {"status": "no_local_config", "agent": agent_id, "detail": str(e)})
            return
        try:
            enriched = _base.process_inbound_mail(payload, dict(self.headers))
        except Exception as e:
            self._send_json(500, {"error": f"preprocess failed: {e}"})
            return
        if enriched is None:
            self._send_json(200, {"status": "intercepted"})
            return

        # ── 3. 投递 DeerFlow LangGraph API ──
        try:
            resp = _base.dispatch_to_deerflow(enriched, self.bridge)
        except Exception as e:
            self._send_json(500, {"error": f"dispatch failed: {e}"})
            return
        if resp.get("error"):
            self._send_json(502, {"status": "deerflow_rejected", "detail": resp})
        else:
            self._send_json(200, {"status": "accepted", "detail": resp})


def _resolve_webhook_secret(system_id: str, gw: dict) -> str:
    """解析 webhook_secret: 优先 agentmail.json 落盘值(注册时生成并落盘,
    与云端一致),回退 gateway config。为空时验签必 401。"""
    secret = ""
    try:
        import glob
        addr_dir = os.path.expanduser(f"~/.agentmail/systems/{system_id}")
        for aj in sorted(glob.glob(os.path.join(addr_dir, "*", "agentmail.json"))):
            try:
                data = json.load(open(aj))
            except Exception:
                continue
            s = data.get("webhook_secret", "")
            if s:
                secret = s
                break
    except Exception:
        pass
    if not secret:
        secret = (gw or {}).get("webhook_secret", "")
    return secret


def serve(port: int, system_id: str) -> None:
    """启动接收端(bridge 转发目标)。"""
    gw = _base.load_gateway_config(system_id) or {}
    registry = _base.load_agents_registry(system_id)
    bridge_cfg = {
        "system_id": system_id,
        "webhook_secret": _resolve_webhook_secret(system_id, gw),
        "registry": registry,
        # DeerFlow 投递配置(可被 agentmail_gateway.json 的 deerflow_* 字段覆盖)
        "deerflow_url": gw.get("deerflow_url", "http://127.0.0.1:8001"),
        "assistant_id": gw.get("assistant_id", "lead_agent"),
        "timeout": int(gw.get("deerflow_timeout", 120)),
    }
    if not bridge_cfg["webhook_secret"]:
        print("WARN: webhook_secret empty — inbound verification will 401", file=sys.stderr)
    if not registry:
        print("WARN: no agents registered in registry — inbound will be dropped", file=sys.stderr)

    class _H(DeerFlowBridgeHandler):
        pass

    _H.bridge = bridge_cfg
    srv = ThreadingHTTPServer(("127.0.0.1", port), _H)
    print(f"amail-deerflow-bridge listening on 127.0.0.1:{port} (system_id={system_id})")
    print(f"  deerflow_url={bridge_cfg['deerflow_url']} assistant_id={bridge_cfg['assistant_id']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="DeerFlow 入站接收端(bridge 转发目标)")
    ap.add_argument("--port", type=int, default=8798)
    ap.add_argument("--system-id", default=os.environ.get("AMAIL_SYSTEM_ID", ""))
    args = ap.parse_args()
    system_id = args.system_id or _base.detect_system_id()
    if not system_id:
        print("need --system-id (or AMAIL_SYSTEM_ID / pointer)", file=sys.stderr)
        return 1
    serve(args.port, system_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
