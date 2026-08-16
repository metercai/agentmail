#!/usr/bin/env python3
"""send_welcome.py — 通用欢迎邮件验证工具(各 agent 系统通用)。

与 ping_test.py 同一设计:SMTP 入站发送欢迎邮件,验证投递+回复。
自动识别 gateway 版本并选择入站方式:
  advanced (/health version 含 "advanced-"):auth.local 认证发送
    (base64(admin_key)=encoded_manager@auth.local)——三层校验后绕过
    SPF/白名单(认证即信任)。
  base:普通 MAIL FROM:<manager> 发送——依赖 manager 地址自动加白
    (register_address 自动写白名单,无需认证)。

用法:
  python3 send_welcome.py [--system-id SID] [--agent-home DIR]
                          [--agent ADDR] [--to ADDR] [--manager ADDR]
  --agent-home: agent 系统 home(Hermes=~/.hermes,OpenClaw=~/.openclaw);
               指针文件 {agent-home}/.agentmail 提供 system_id/email
  --agent:      agent 标识(定位 mail 目录,默认从指针 email)
  --to:         直接指定收件地址(优先于 --agent/指针)
  --manager:    发件人(manager)地址,默认 config.manager_address
  --timeout:    等待回复秒数(默认 120)
  --no-wait:    发送后不等待回复,直接退出
退出码: 0=成功, 1=失败
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import sys
import time
import urllib.request
import uuid
from pathlib import Path

AGENTMAIL_HOME = Path.home() / ".agentmail"
SYSTEMS_DIR = AGENTMAIL_HOME / "systems"


def _clean_agent_dir_name(addr: str) -> str:
    """agent 地址 → 目录名(与 tools/agentmail_base._clean_agent_dir_name 一致)。"""
    return re.sub(r"[^\w.\-]", "_", addr)


def _smtp_cmd(s: socket.socket, c: str) -> str:
    """发送 SMTP 命令并完整读取多行响应。

    响应可能粘包(如 '250-server...\\r\\n250 8BITMIME' 一条 recv)。
    按行拆分,末行 'NNN '(第 4 字符非 '-')即响应完成。
    """
    s.sendall(f"{c}\r\n".encode())
    all_lines: list = []
    while True:
        chunk = s.recv(4096).decode(errors="replace")
        if not chunk:
            break
        all_lines.extend(chunk.splitlines())
        last = all_lines[-1] if all_lines else ""
        if len(last) < 4 or last[3] != "-":
            break
    return " | ".join(l.strip() for l in all_lines)


def _detect_edition(gateway_url: str) -> str:
    """GET /health → version → 'advanced' | 'base'。失败默认 base。"""
    try:
        with urllib.request.urlopen(f"{gateway_url.rstrip('/')}/health", timeout=10) as r:
            data = json.loads(r.read())
        ver = data.get("version", "")
        return "advanced" if "advanced-" in ver else "base"
    except Exception:
        return "base"


def _smtp_send(gateway_url: str, admin_key: str, agent_email: str,
               manager: str, edition: str, subject: str, body: str) -> str:
    """SMTP 发送。edition=advanced 用 auth.local 认证;base 用普通发件人。"""
    host = gateway_url.replace("https://", "").replace("http://", "").split("/")[0]
    port = 25

    if edition == "advanced":
        key_bytes = bytes.fromhex(admin_key)
        b64_key = base64.b64encode(key_bytes).decode().rstrip("=")
        encoded_manager = manager.replace("@", "=")
        mail_from = f"{b64_key}={encoded_manager}@auth.local"
    else:
        # base:普通发件人(manager 已由 register_address 自动加白)
        mail_from = manager

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(15)
    try:
        s.connect((host, port))
        banner = s.recv(4096).decode(errors="replace").strip()
        if not banner.startswith("220"):
            return f"SMTP banner failed: {banner}"
        _smtp_cmd(s, "EHLO amail-welcome")
        resp = _smtp_cmd(s, f"MAIL FROM:<{mail_from}>")
        if not resp.startswith("250"):
            return f"MAIL FROM failed: {resp}"
        resp = _smtp_cmd(s, f"RCPT TO:<{agent_email}>")
        if not resp.startswith("250"):
            return f"RCPT TO failed: {resp}"
        resp = _smtp_cmd(s, "DATA")
        if not resp.startswith("354"):
            return f"DATA failed: {resp}"
        s.sendall(body.replace("\n", "\r\n").encode())
        if not body.endswith("\n"):
            s.sendall(b"\r\n")
        s.sendall(b".\r\n")
        return _smtp_cmd(s, "")
    finally:
        try:
            s.sendall(b"QUIT\r\n")
        except Exception:
            pass
        s.close()


def _poll_reply(gateway_url: str, admin_key: str, agent_email: str,
                timeout_secs: int) -> tuple:
    """轮询 stats API 直到 sent 增加(agent 回复)。返回 (ok, sent, recv)。"""
    url = f"{gateway_url.rstrip('/')}/api/v1/stats/agent/me?email={agent_email}"

    def _fetch():
        try:
            req = urllib.request.Request(url, headers={"X-Api-Key": admin_key})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except Exception:
            return {}

    before = _fetch()
    before_sent = before.get("sent", 0)
    before_recv = before.get("received", 0)
    print(f"  Stats baseline: sent={before_sent}, received={before_recv}")

    start = time.time()
    last_sent, last_recv = before_sent, before_recv
    while time.time() - start < timeout_secs:
        time.sleep(5)
        now = _fetch()
        now_sent = now.get("sent", last_sent)
        now_recv = now.get("received", last_recv)
        last_sent, last_recv = now_sent, now_recv
        if now_sent > before_sent:
            print(f"  ✓ Agent replied (sent={now_sent}, received={now_recv})")
            return True, now_sent, now_recv
    print(f"  ⚠ Timeout — email sent but no reply within {timeout_secs}s "
          f"(last: sent={last_sent}, received={last_recv})")
    return False, last_sent, last_recv


def main() -> int:
    ap = argparse.ArgumentParser(description="欢迎邮件验证工具(共享,自动识别 gateway 版本)")
    ap.add_argument("--system-id", default="")
    ap.add_argument("--agent-home", default="",
                    help="agent 系统 home(Hermes=~/.hermes, OpenClaw=~/.openclaw)")
    ap.add_argument("--agent", default="", help="agent 标识(定位 mail 目录/地址)")
    ap.add_argument("--to", default="", help="直接指定收件地址(优先)")
    ap.add_argument("--manager", default="", help="发件人(manager)地址,默认 config.manager_address")
    ap.add_argument("--timeout", type=int, default=120, help="等待回复秒数")
    ap.add_argument("--no-wait", action="store_true", help="发送后不等待回复")
    args = ap.parse_args()

    agent_home = Path(args.agent_home or os.environ.get("AGENT_HOME", str(Path.home() / ".hermes")))

    # ── 解析系统身份:--to > --agent > 指针 > env ──
    sid = args.system_id
    email = args.agent
    pointer = agent_home / ".agentmail"
    if pointer.is_file():
        try:
            pd = json.loads(pointer.read_text())
            sid = sid or pd.get("system_id", "")
            email = email or pd.get("email", "")
        except Exception:
            pass
    sid = sid or os.environ.get("SYSTEM_ID", "") or os.environ.get("AMAIL_SYSTEM_ID", "")

    if not sid:
        print("✗ system_id 未解析(需 --system-id 或 {agent-home}/.agentmail 指针)")
        return 1

    # ── 读 gateway 配置 ──
    config_path = SYSTEMS_DIR / sid / "agentmail_gateway.json"
    if not config_path.exists():
        print(f"✗ agentmail_gateway.json not found: {config_path}")
        return 1
    cfg = json.loads(config_path.read_text())
    gw_url = cfg.get("gateway_url", "")
    ak = cfg.get("admin_key", "")
    manager = args.manager or os.environ.get("AMAIL_MANAGER_ADDRESS") \
        or os.environ.get("MANAGER") or cfg.get("manager_address", "")

    # 收件地址:--to > --agent > 指针 email > config 派生
    recipient = args.to or email
    if not recipient:
        recipient = f"{cfg.get('system_name', 'agent')}@{cfg.get('domain', '')}"
    if not manager:
        print("✗ 无 manager 地址(需 --manager 或 config.manager_address)")
        return 1
    if not all([gw_url, ak]):
        print("✗ Missing gateway_url/admin_key")
        return 1

    # ── 识别 gateway 版本 → 选择 SMTP 入站方式 ──
    edition = _detect_edition(gw_url)
    print(f"  Gateway:     {gw_url}")
    print(f"  Edition:     {edition}({'auth.local 认证' if edition == 'advanced' else '白名单直发'})")
    print(f"  To:          {recipient}")
    print(f"  Manager:     {manager}")

    msg_id = f"<welcome-{int(time.time())}-{uuid.uuid4().hex[:4]}@amail>"
    body = f"""From: {manager}
To: {recipient}
Message-ID: {msg_id}
Subject: Welcome! Your amail integration is live

Hello! This is your first email delivered through your new amail system.

Please reply with the current server time to confirm the mail loop is working.

--
This confirms: ✓ SMTP inbound  ✓ Webhook delivery  ✓ Agent processing  ✓ Outbound reply
"""

    resp = _smtp_send(gw_url, ak, recipient, manager, edition, "Welcome!", body)
    # base 版回落:auth.local 前缀会被当普通发件人拒(550),回落 manager 直发
    if not resp.startswith("250") and edition == "advanced":
        print(f"  ⚠ auth.local 发送失败({resp[:50]}),回落 base 白名单直发")
        resp = _smtp_send(gw_url, ak, recipient, manager, "base", "Welcome!", body)
    if not resp.startswith("250"):
        print(f"✗ SMTP send failed: {resp}")
        return 1
    print("  ✓ Welcome email sent via SMTP")

    if args.no_wait:
        return 0

    ok, sent, recv = _poll_reply(gw_url, ak, recipient, args.timeout)
    if ok:
        print(f"  ✓ Bidirectional send/receive verified (sent={sent}, received={recv})")
        return 0
    print(f"  ✗ No reply within {args.timeout}s (sent={sent}, received={recv})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
