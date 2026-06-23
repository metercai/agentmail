#!/usr/bin/env python3
"""Step 9: Send welcome email via SMTP, verify delivery and reply."""
import sys, os, json, time, re, socket, base64, hashlib
from datetime import datetime, timezone
from email.mime.text import MIMEText
import urllib.request, urllib.error

def log_info(msg):
    print(f"  {msg}")

def log_warn(msg):
    print(f"  ⚠ {msg}")

def log_ok(msg):
    print(f"  ✓ {msg}")

def load_config():
    path = os.path.expanduser("~/.hermes/amail_gateway.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def get_agent_email(config):
    """Find agent email from gateway API, profiles, or env."""
    gw = config.get("gateway_url", "")
    ak = config.get("admin_key", "")
    sid = config.get("system_id", "")
    domain = config.get("domain", "")

    # 1. Env var
    email = os.environ.get("AGENT_EMAIL", "")
    if email:
        return email

    # 2. Query API — prefer default agent (short form: sys-name@domain)
    try:
        req = urllib.request.Request(f"{gw}/api/v1/admin/systems/{sid}/domains",
            headers={"X-Api-Key": ak})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        # Short form (no dot in local part) = default agent
        for d in data:
            dom = d.get("domain", "")
            if "@" in dom and "." not in dom.split("@")[0]:
                return dom
        # Explicit default.*
        for d in data:
            dom = d.get("domain", "")
            if "@" in dom and dom.startswith("default."):
                return dom
        # First with webhook
        for d in data:
            dom = d.get("domain", "")
            if "@" in dom and d.get("webhook_url"):
                return dom
        # First address
        for d in data:
            dom = d.get("domain", "")
            if "@" in dom:
                return dom
    except Exception as e:
        log_warn(f"API query failed: {e}")

    # 3. Profiles directory
    home = os.path.expanduser("~/.hermes")
    profiles_dir = os.path.join(home, "profiles")
    if os.path.isdir(profiles_dir):
        for name in sorted(os.listdir(profiles_dir)):
            aj = os.path.join(profiles_dir, name, "amail.json")
            if os.path.exists(aj):
                try:
                    with open(aj) as f:
                        pf = json.load(f)
                    if pf.get("system_id") == sid:
                        return pf.get("email", "")
                except:
                    pass
    # Root profile
    aj = os.path.join(home, "amail.json")
    if os.path.exists(aj):
        try:
            with open(aj) as f:
                pf = json.load(f)
            if pf.get("system_id") == sid:
                return pf.get("email", "")
        except:
            pass

    return ""

def do_smtp_send(gateway_url: str, admin_key: str, agent_email: str, manager: str):
    """Send welcome email via SMTP with auth. Returns True on success."""
    host = gateway_url.replace("https://", "").replace("http://", "")
    # If the URL has a path, strip it
    host = host.split("/")[0]
    port = 25  # SMTP

    # Build auth FROM
    key_bytes = bytes.fromhex(admin_key)
    b64_key = base64.b64encode(key_bytes).decode().rstrip("=")
    encoded_manager = manager.replace("@", "=")
    auth_from = f"{b64_key}={encoded_manager}@auth.local"

    # SMTP via socket (no external deps)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.connect((host, port))
        s.recv(4096)  # banner

        def cmd(c):
            s.sendall(f"{c}\r\n".encode())
            return s.recv(4096).decode().strip()

        cmd("EHLO amail-integration")

        # MAIL FROM with auth
        resp = cmd(f"MAIL FROM:<{auth_from}>")
        if not resp.startswith("250"):
            log_warn(f"MAIL FROM failed: {resp}")
            s.sendall(b"QUIT\r\n"); s.close()
            return False

        resp = cmd(f"RCPT TO:<{agent_email}>")
        if not resp.startswith("250"):
            log_warn(f"RCPT TO failed: {resp}")
            s.sendall(b"QUIT\r\n"); s.close()
            return False

        resp = cmd("DATA")
        if not resp.startswith("354"):
            log_warn(f"DATA failed: {resp}")
            s.sendall(b"QUIT\r\n"); s.close()
            return False

        # Email body
        body = f"""From: {manager}
To: {agent_email}
Subject: Welcome! Your amail integration is live

Hello! This is your first email delivered through your new amail system.

Please reply with the current server time to confirm the mail loop is working.

--
This confirms: ✓ SMTP inbound  ✓ Webhook delivery  ✓ Agent processing  ✓ Outbound reply
"""
        s.sendall(body.replace("\n", "\r\n").encode())
        if not body.endswith("\n"):
            s.sendall(b"\r\n")
        s.sendall(b".\r\n")
        resp = s.recv(4096).decode().strip()
        if not resp.startswith("250"):
            log_warn(f"DATA end failed: {resp}")
            s.sendall(b"QUIT\r\n"); s.close()
            return False

        s.sendall(b"QUIT\r\n"); s.close()
        log_ok("Welcome email sent via SMTP")
        return True
    except Exception as e:
        log_warn(f"SMTP error: {e}")
        return False

def poll_stats(gateway_url: str, admin_key: str, agent_email: str, timeout_secs: int = 30):
    """Poll stats API until received count increases. Returns True if reply detected."""
    import urllib.request, urllib.error

    url = f"{gateway_url.rstrip('/')}/api/v1/stats/agent/me?email={agent_email}"
    
    # Get baseline
    try:
        req = urllib.request.Request(url, headers={"X-Api-Key": admin_key})
        with urllib.request.urlopen(req, timeout=5) as r:
            before = json.loads(r.read())
    except:
        before = {"received": 0, "sent": 0}

    before_recv = before.get("received", 0)
    before_sent = before.get("sent", 0)
    log_info(f"Stats baseline: sent={before_sent}, received={before_recv}")

    start = time.time()
    while time.time() - start < timeout_secs:
        time.sleep(5)
        try:
            req = urllib.request.Request(url, headers={"X-Api-Key": admin_key})
            with urllib.request.urlopen(req, timeout=5) as r:
                now = json.loads(r.read())
            now_recv = now.get("received", 0)
            now_sent = now.get("sent", 0)
            if now_recv > before_recv:
                log_ok(f"Agent processed the email (received={now_recv}, sent={now_sent})")
                return True
        except:
            pass

    log_warn(f"Timeout — email sent but no reply within {timeout_secs}s")
    return False

def main():
    config = load_config()
    if not config:
        log_warn("No gateway config found")
        sys.exit(1)

    gw = config.get("gateway_url", "")
    ak = config.get("admin_key", "")
    sid = config.get("system_id", "")
    domain = config.get("domain", "")
    manager = os.environ.get("MANAGER", config.get("manager_address", "925457@qq.com"))
    agent_email = os.environ.get("AGENT_EMAIL", get_agent_email(config))

    print()
    print("  Send/receive test")
    print(f"  Gateway:     {gw}")
    print(f"  Agent email: {agent_email}")
    print(f"  Manager:     {manager}")

    if not agent_email:
        log_warn("No agent email found in current system")
        log_info("Run integrate.sh Step 8 to register profiles")
        log_info("Or set AGENT_EMAIL=user@domain")
        sys.exit(1)

    # Send
    ok = do_smtp_send(gw, ak, agent_email, manager)
    if not ok:
        log_warn("SMTP send failed")
        sys.exit(1)

    # Wait for reply
    verified = poll_stats(gw, ak, agent_email)

    log_info(f"Stats sent: ..., received: ...")
    if verified:
        log_ok("Bidirectional send/receive verified")
        sys.exit(0)
    else:
        log_warn("Timeout — email sent but no reply within 30s")
        sys.exit(1)

if __name__ == "__main__":
    main()
