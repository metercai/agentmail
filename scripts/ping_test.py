#!/usr/bin/env python3
"""ping_test.py — 独立共享 Ping-Pong End-to-End 测试(各 agent 系统通用)。

从 check_status.py 的 _run_ping_test 与 verify-e2e.py 独立出来。与
send_welcome.py 同一机制:SMTP auth 入站(auth.local 认证 FROM)发送
__agentmail_ping__ 邮件,验证全链路后 pong 回发。

Ping/Pong 语义:ping 邮件走完全部中间链(富化/附件/存储)才在调用
agent 前最后一刻被吞;pong 只在全链路正常时回复 —— 测试通过 =
进入 agent 之前的所有处理正常。

两种投递模式(按 agentmail_gateway.json 的 mode 字段自动选择):
  pull : 验证 pending 队列 —— ping 出现 → poll 拉取拦截 → 队列清空
         (OpenClaw/DeerFlow 默认)
  push : 验证 agentmail.log 三阶段事件 —— ping_intercepted →
         pong_sent → pong_returned(Hermes webhook.py 补丁)

用法:
  python3 ping_test.py [--system-id SID] [--agent-home DIR] [--timeout 120]
  --agent-home:  agent 系统 home(Hermes=~/.hermes,OpenClaw=~/.openclaw)
                指针文件 {agent-home}/.agentmail 提供 system_id/email
  --agent:       可选的 agent 标识(定位 mail 目录,默认从指针 email)
  --timeout:     等待处理的秒数(默认 120)
  --no-snapshot: 跳过原始邮件快照检查
  --mode pull|push: 强制指定模式(默认 auto)
退出码: 0=通过, 1=失败
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
from datetime import datetime, timezone
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────
AGENTMAIL_HOME = Path.home() / ".agentmail"
SYSTEMS_DIR = AGENTMAIL_HOME / "systems"
MAIL_DIR = AGENTMAIL_HOME / "mail"

PING_PREFIX = "__agentmail_ping__:"


def _clean_agent_dir_name(addr: str) -> str:
    """agent 地址 → 目录名(与 tools/agentmail_base._clean_agent_dir_name 一致)。"""
    return re.sub(r"[^\w.\-]", "_", addr)


def _smtp_cmd(s: socket.socket, c: str) -> str:
    """发送 SMTP 命令并完整读取多行响应。

    响应可能是多条独立 recv 包,也可能一条包含全部行
    (如 '250-server...\\r\\n250 8BITMIME' 粘包)。按行拆分后逐行
    判定:行首 'NNN-' 表示还有后续行,'NNN ' 是末行。
    """
    s.sendall(f"{c}\r\n".encode())
    all_lines: list = []
    while True:
        chunk = s.recv(4096).decode(errors="replace")
        if not chunk:
            break
        all_lines.extend(chunk.splitlines())
        # 末行 'NNN ' 或 'NNN'(第 4 字符非 '-')即响应完成。
        # 粘包时整条含多行,只有拆行后的最后一行能决定是否结束。
        last = all_lines[-1] if all_lines else ""
        if len(last) < 4 or last[3] != "-":
            break
    return " | ".join(l.strip() for l in all_lines)


def _smtp_send_ping(gw_url: str, admin_key: str, email: str,
                    manager: str, ping_id: str, edition: str = "advanced") -> str:
    """SMTP auth 发送 ping(与 send_welcome.py 同机制)。返回 DATA end 响应。

    edition=advanced:auth.local 认证发送(base64(admin_key)=manager@auth.local)。
    edition=base:普通 MAIL FROM:<manager>(manager 已自动加白)。
    """
    host = gw_url.replace("https://", "").replace("http://", "").split("/")[0]
    if edition == "advanced":
        # auth.local 认证:网关要求 key 的 scope 含 system/platform
        # (advanced/strategy.rs resolve_sender)——agent scope 会被拒。
        # 因此这里必须用系统 admin_key,不能用 agent api_key。
        key_bytes = bytes.fromhex(admin_key)
        b64_key = base64.b64encode(key_bytes).decode().rstrip("=")
        encoded_manager = manager.replace("@", "=")
        auth_from = f"{b64_key}={encoded_manager}@auth.local"
    else:
        auth_from = manager

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(15)
    s.connect((host, 25))
    try:
        # Banner: read directly (no command sent)
        banner = s.recv(4096).decode(errors="replace").strip()
        if not banner.startswith("220"):
            return f"SMTP banner failed: {banner}"
        _smtp_cmd(s, "EHLO amail-ping-test")
        resp = _smtp_cmd(s, f"MAIL FROM:<{auth_from}>")
        if not resp.startswith("250"):
            return f"MAIL FROM failed: {resp}"
        resp = _smtp_cmd(s, f"RCPT TO:<{email}>")
        if not resp.startswith("250"):
            return f"RCPT TO failed: {resp}"
        resp = _smtp_cmd(s, "DATA")
        if not resp.startswith("354"):
            return f"DATA failed: {resp}"
        body = (f"From: {manager}\nTo: {email}\n"
                f"Subject: {PING_PREFIX}{ping_id}\n"
                f"Message-ID: <ping-{ping_id}@amail.token.tm>\n"
                f"\nPing test message\n")
        s.sendall(body.replace("\n", "\r\n").encode())
        s.sendall(b".\r\n")
        return _smtp_cmd(s, "")
    finally:
        try:
            s.sendall(b"QUIT\r\n")
        except Exception:
            pass
        s.close()


def _api_get(gw_url: str, admin_key: str, path: str) -> dict:
    req = urllib.request.Request(f"{gw_url}{path}",
                                 headers={"X-Api-Key": admin_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def _api_post(gw_url: str, admin_key: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{gw_url}{path}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-Api-Key": admin_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def _detect_edition(gateway_url: str) -> str:
    """GET /health → version → 'advanced' | 'base'。失败默认 advanced
    (auth.local 认证发送;若 base 版返回 550 可 --mode 不强求,由
    base 版白名单直发兜底)。"""
    try:
        with urllib.request.urlopen(f"{gateway_url.rstrip('/')}/health", timeout=10) as r:
            data = json.loads(r.read())
        ver = data.get("version", "")
        return "advanced" if "advanced-" in ver else "base"
    except Exception:
        return "advanced"


def main() -> int:
    ap = argparse.ArgumentParser(description="Ping-Pong End-to-End Test(共享)")
    ap.add_argument("--system-id", default="")
    ap.add_argument("--agent-home", default="",
                    help="agent 系统 home(Hermes=~/.hermes, OpenClaw=~/.openclaw)")
    ap.add_argument("--agent", default="", help="agent 标识(定位 mail 目录)")
    ap.add_argument("--manager", default="", help="发件人(manager)地址,默认 config.manager_address")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--mode", choices=["auto", "pull", "push"], default="auto")
    ap.add_argument("--no-snapshot", action="store_true")
    args = ap.parse_args()

    agent_home = Path(args.agent_home or os.environ.get("AGENT_HOME", str(Path.home() / ".hermes")))

    # ── 解析系统身份:指针 > 参数 > env ──
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
    sid = sid or os.environ.get("SYSTEM_ID", "")

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
    if not email:
        # 主 agent 地址派生:Hermes 默认 agent_id=default,OpenClaw 默认
        # agent_id=main,共享域统一归一为 agent.{system_name}@{domain}
        # (email_for_agent 规则)——不能直接用 system_name@domain(缺 agent.)
        email = f"agent.{cfg.get('system_name', 'agent')}@{cfg.get('domain', '')}"
    manager = args.manager or cfg.get("manager_address", "")
    mode = cfg.get("mode", "pull")  # pull|push(8/14 起 mode 合并进 gateway config)

    if not all([gw_url, ak, email, manager]):
        print("✗ Missing required config fields(gateway_url/admin_key/email/manager)")
        return 1

    mode = args.mode if args.mode != "auto" else mode
    mail_dir = MAIL_DIR / _clean_agent_dir_name(email)          # 快照目录(mail 数据)
    amail_log = AGENTMAIL_HOME / "logs" / f"agentmail.{_clean_agent_dir_name(email)}.log"

    # ── 识别 gateway 版本 → 选择 SMTP 入站方式 ──
    edition = _detect_edition(gw_url)
    ping_id = uuid.uuid4().hex[:12]

    # ── SMTP auth 发送(带 base 回落) ──
    print(f"  mode={mode} edition={edition} system_id={sid} email={email}")
    t_sent = time.time()
    resp = _smtp_send_ping(gw_url, ak, email, manager, ping_id, edition)
    # base 版回落:auth.local 前缀会被当普通发件人拒(550),回落 manager 直发
    if not resp.startswith("250") and edition == "advanced":
        print(f"  ⚠ auth.local 发送失败({resp[:50]}),回落 base 白名单直发")
        resp = _smtp_send_ping(gw_url, ak, email, manager, ping_id, "base")
    if not resp.startswith("250"):
        print(f"✗ SMTP ping send failed: {resp}")
        return 1
    print(f"  Ping sent: {PING_PREFIX}{ping_id}")
    dt_sent = datetime.fromtimestamp(t_sent, tz=timezone.utc)

    deadline = time.time() + args.timeout
    found_ping = found_pong = found_sent = False

    def _parse_ts(s: str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s[:26], fmt[:len(s[:26])])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
        return None

    def _fmt_secs(ts_str: str, t0: datetime) -> float:
        dt = _parse_ts(ts_str)
        return (dt - t0).total_seconds() if dt else 0.0

    pull_observed = 0   # pending 中出现 ping 的次数
    pull_acked = 0      # pending 清空(ping 被拉取拦截)的次数

    while time.time() < deadline:
        # ── push 模式:agentmail.log 三阶段事件 ──
        if amail_log.exists():
            for line in reversed(amail_log.read_text().splitlines()):
                if ping_id not in line:
                    continue
                try:
                    entry = json.loads(line)
                    d = entry.get("dir", "")
                    ts = entry.get("ts", "")
                    if d == "ping_intercepted" and not found_ping:
                        found_ping = True
                        print(f"  +{_fmt_secs(ts, dt_sent):5.1f}s    Webhook Receive (ping)         ✓")
                    if d == "pong_sent" and found_ping and not found_sent:
                        found_sent = True
                        print(f"  +{_fmt_secs(ts, dt_sent):5.1f}s    Pong Sent (send_mail)          ✓")
                    if d == "pong_returned" and found_ping and not found_pong:
                        found_pong = True
                        print(f"  +{_fmt_secs(ts, dt_sent):5.1f}s    Webhook Return (pong)          ✓")
                        print(f"  +{_fmt_secs(ts, dt_sent):5.1f}s    Total round-trip: {_fmt_secs(ts, dt_sent):.1f}s")
                except Exception:
                    pass
        # ── pull 模式:pending 队列出现 ping → 清空(被 poll 拉取拦截)──
        pend = _api_post(gw_url, ak, "/api/v1/admin/pending",
                         {"limit": 20, "filter": [cfg.get("domain", "")]})
        batches = pend.get("batches") or []
        ping_here = any(PING_PREFIX in (b.get("body") or {}).get("subject", "")
                        for b in batches)
        if ping_here and not pull_observed:
            pull_observed = 1
            print(f"  +{time.time() - t_sent:5.1f}s    Pending queue (ping received)    ✓")
        if pull_observed and not batches and not pull_acked:
            # 队列曾含 ping,现已清空 = poll 拉取并拦截
            pull_acked = 1
            print(f"  +{time.time() - t_sent:5.1f}s    Pending drained (poll intercepted) ✓")

        if mode == "push" and found_ping and found_pong:
            break
        if mode == "pull" and pull_observed and pull_acked:
            break
        time.sleep(3)

    # ── 结果判定 ──
    if mode == "pull":
        if pull_observed and pull_acked:
            print(f"  ✓ Ping intercepted via pull — pipeline OK (ping_id={ping_id})")
            result_ok = True
        elif pull_observed:
            print(f"  ✗ Ping reached pending but was not drained within {args.timeout}s")
            result_ok = False
        else:
            print(f"  ✗ Ping never reached pending within {args.timeout}s")
            result_ok = False
    else:  # push
        if found_ping and found_pong:
            print(f"  ✓ Full push pipeline verified (ping_id={ping_id})")
            result_ok = True
        elif found_ping:
            print(f"  ✓ Ping intercepted, but pong not returned within {args.timeout}s")
            result_ok = False
        else:
            print(f"  ✗ No ping or pong detected within {args.timeout}s")
            result_ok = False
    if not result_ok:
        return 1

    # ── 原始邮件快照检查 ──
    if not args.no_snapshot:
        snap_ok = 0
        snap_total = 0
        if mail_dir.exists():
            now_ts = time.time()
            for entry in mail_dir.rglob("*"):
                if entry.is_file():
                    snap_total += 1
                    if now_ts - entry.stat().st_mtime < 300:
                        snap_ok += 1
        if snap_ok > 0:
            print(f"  ✓ Snapshots: {snap_ok} new file(s) in mail/{_clean_agent_dir_name(email)}/ (total {snap_total})")
        else:
            print(f"  ⚠ Snapshots: {snap_total} total file(s), none from last 5min")

    return 0


if __name__ == "__main__":
    sys.exit(main())
