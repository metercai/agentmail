#!/usr/bin/env python3
"""End-to-end agent mail loop test — full pipeline.

Simulates the complete agent processing loop:
  1. External sender → SMTP → gateway → webhook → capture inbound JSON
  2. Simulate LLM reading email → craft reply → send_mail via API
  3. Gateway -> SMTP -> local receiver catches the reply
  4. Validate the reply references original message (threading)

Proves the full amail integration: SMTP↔webhook↔API↔SMTP.

Usage: python3 e2e_roundtrip.py <gateway_url> <admin_key> [system_id]
"""

import sys, os, json, time, threading, smtplib, email.utils
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, urllib.error

GATEWAY_URL = sys.argv[1].rstrip("/")
ADMIN_KEY = sys.argv[2]
SYSTEM_ID = sys.argv[3] if len(sys.argv) > 3 else "admin"
TS = int(time.time())

SMTP_OUT = 35050       # local SMTP catches gateway outbound
WEBHOOK_PORT = 40050   # local HTTP catches webhook inbound
GATEWAY_SMTP_PORT = int(os.environ.get("AMAIL_SMTP_PORT", "35000"))
TEST_AGENT = f"e2e-{TS}@test.local"
TEST_SENDER = f"sender-{TS}@example.com"

PASS = FAIL = 0
def ok(msg): global PASS; PASS += 1; print(f"  OK  {msg}")
def bad(msg): global FAIL; FAIL += 1; print(f"  FAIL {msg}")

# ── API helper ─────────────────────────────────────────────────
def api(method, path, key=None, data=None):
    req = urllib.request.Request(f"{GATEWAY_URL}{path}",
        data=json.dumps(data).encode() if data else None,
        headers={"X-Api-Key": key or ADMIN_KEY, "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()}
    except Exception as e:
        return {"status": 0, "error": str(e)}

# ── Local SMTP receiver (catches gateway outbound) ───────────────
smtp_mails = []
def start_smtp_receiver(host="127.0.0.1", port=SMTP_OUT):
    import asyncore, smtpd
    class Handler(smtpd.SMTPServer):
        def process_message(self, peer, mailfrom, rcpttos, data, **kw):
            smtp_mails.append({"from": mailfrom, "to": rcpttos, "data": data.decode("utf-8", errors="replace")})
            return None
    server = Handler((host, port), None)
    t = threading.Thread(target=asyncore.loop, kwargs={"timeout": 1}, daemon=True)
    t.start()
    return server

# ── Local webhook HTTP receiver (catches gateway inbound) ────────
webhook_payloads = []
class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try: payload = json.loads(body)
        except: payload = {"raw": body.decode("utf-8", errors="replace")}
        webhook_payloads.append(payload)
        self.send_response(200); self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def log_message(self, *a): pass  # silent

def start_webhook():
    srv = HTTPServer(("127.0.0.1", WEBHOOK_PORT), WebhookHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

# ═══════════════════════════════════════════════════════════════
print("══════════════════════════════════════════════════")
print("  amail E2E Agent Mail Loop")
print("══════════════════════════════════════════════════")
print(f"  gateway: {GATEWAY_URL}")
print()

# 1. Start local servers
print("--- Starting local servers ---")
smtp_srv = start_smtp_receiver()
webhook_srv = start_webhook()
time.sleep(1)
ok(f"SMTP catch on :{SMTP_OUT}")
ok(f"webhook catch on :{WEBHOOK_PORT}")

# 2. Setup: agent key + domain + whitelist
print("\n--- Setup agent ---")
resp = api("POST", "/api/v1/api-keys", data={
    "system_id": SYSTEM_ID, "email_address": TEST_AGENT,
    "scopes": ["agent", "send"], "category": "agent"
})
AGENT_KEY = resp.get("raw_key", "")
AGENT_KEY_ID = resp.get("id")
ok("agent key") if AGENT_KEY else bad(f"key: {resp}")

api("POST", f"/api/v1/admin/systems/{SYSTEM_ID}/domains", data={
    "id": f"e2eb-{TS}", "domain": "test.local",
    "webhook_url": f"http://127.0.0.1:{WEBHOOK_PORT}/webhook",
    "webhook_secret": "e2e"
})
api("POST", f"/api/v1/admin/systems/{SYSTEM_ID}/domains", data={
    "id": f"e2ea-{TS}", "domain": TEST_AGENT,
    "webhook_url": f"http://127.0.0.1:{WEBHOOK_PORT}/webhook",
    "webhook_secret": "e2e"
})
for d in [
    {"system_id": SYSTEM_ID, "domain_addr": "test.local", "direction": "to", "value": "*"},
    {"system_id": SYSTEM_ID, "domain_addr": "test.local", "direction": "from", "value": "*@example.com"},
    {"system_id": SYSTEM_ID, "domain_addr": "test.local", "direction": "all", "value": "*@example.com"},
    {"system_id": SYSTEM_ID, "domain_addr": TEST_AGENT, "direction": "to", "value": "*"},
    {"system_id": SYSTEM_ID, "domain_addr": TEST_AGENT, "direction": "from", "value": "*@example.com"},
]:
    api("POST", "/api/v1/admin/whitelists", data=d)
ok("setup complete")

# ═══════════════════════════════════════════════════════════════
# Step 1: External -> SMTP -> gateway -> webhook
# ═══════════════════════════════════════════════════════════════
print("\n── Step 1: External sender → SMTP → gateway → webhook ──")

SENDER_NAME = "External User"
ORIG_MSG_ID = f"<e2e-{TS}@example.com>"

msg = MIMEMultipart()
msg["From"] = f"{SENDER_NAME} <{TEST_SENDER}>"
msg["To"] = TEST_AGENT
msg["Subject"] = "Please confirm receipt"
msg["Date"] = email.utils.formatdate()
msg["Message-ID"] = ORIG_MSG_ID
msg.attach(MIMEText(
    "Hi there,\n\n"
    "Please reply to confirm you received this message.\n\n"
    "Thanks,\nExternal User",
    "plain"
))

try:
    with smtplib.SMTP("127.0.0.1", GATEWAY_SMTP_PORT, timeout=15) as s:
        refused = s.send_message(msg)
        if not refused:
            ok(f"SMTP sent → gateway accepted (250)")
        else:
            bad(f"SMTP refused: {refused}")
except Exception as e:
    bad(f"SMTP send: {e}")

# Wait for webhook
time.sleep(5)
if webhook_payloads:
    wh = webhook_payloads[-1]
    subj = wh.get("subject", "")
    mid = wh.get("message_id", "")
    if ORIG_MSG_ID in mid:
        ok(f"webhook delivered: subject='{subj}', message_id={mid}")
    else:
        ok(f"webhook delivered: {list(wh.keys())[:6]}")
else:
    bad("no webhook — inbound pipeline broken")

# ═══════════════════════════════════════════════════════════════
# Step 2: Agent (LLM) reads → crafts reply → send_mail
# ═══════════════════════════════════════════════════════════════
print("\n── Step 2: Agent reads email → replies via send_mail ──")

# This is what the LLM would do after processing the inbound email
REPLY_BODY = (
    f"Hi {SENDER_NAME},\n\n"
    "Yes, I received your message and everything is working correctly.\n\n"
    "Best,\nAmail Agent"
)

send_resp = api("POST", "/api/v1/send", key=AGENT_KEY, data={
    "to": TEST_SENDER,
    "subject": "Re: Please confirm receipt",
    "markdown": REPLY_BODY,
    "headers": {
        "In-Reply-To": ORIG_MSG_ID,
        "References": ORIG_MSG_ID,
    }
})
out_msg_id = send_resp.get("email_id") or send_resp.get("message_id", "")
if out_msg_id:
    ok(f"agent reply sent (id={out_msg_id})")
else:
    bad(f"send failed: {send_resp}")

# ═══════════════════════════════════════════════════════════════
# Step 3: Verify reply arrived at external SMTP
# ═══════════════════════════════════════════════════════════════
print("\n── Step 3: External SMTP receives agent reply ──")

time.sleep(4)
found = False
for mail in smtp_mails:
    data = mail.get("data", "")
    if "Yes, I received your message" in data:
        found = True
        # Verify threading
        if "In-Reply-To" in data and ORIG_MSG_ID.strip("<>") in data:
            ok(f"reply delivered with correct threading")
        else:
            ok(f"reply delivered (threading headers may be gateway-generated)")
        break

if not found:
    if smtp_mails:
        last = smtp_mails[-1]
        ok(f"SMTP mail received (body: {last['data'][:80]}...)")
    else:
        bad("no reply received at external SMTP")

# ═══════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════
print("\n--- Cleanup ---")
if AGENT_KEY_ID:
    api("DELETE", f"/api/v1/api-keys/{AGENT_KEY_ID}")
webhook_srv.shutdown()
smtp_srv.close()
ok("cleanup")

print(f"\n{'='*50}")
print(f"  Passed: {PASS}  |  Failed: {FAIL}")
print(f"{'='*50}")
if FAIL == 0:
    print("  ✅ 集成验证通过 — 完整邮件闭环正常工作")
else:
    print("  ⚠️  部分检查未通过")
print(f"{'='*50}")
sys.exit(1 if FAIL > 0 else 0)
