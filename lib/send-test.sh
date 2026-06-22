# Step 10: online send/receive test — bidirectional SMTP → agent → reply
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TEST"

CONFIG_FILE="$HOME/.hermes/amail_gateway.json"
if [ ! -f "$CONFIG_FILE" ]; then
    step_warn "$T_TEST_FAIL_KEY"
    exit 0
fi

# ── Load config ──
ADMIN_KEY=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('admin_key',''))" 2>/dev/null)
GATEWAY_URL=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('gateway_url',''))" 2>/dev/null)
AGENT_DOMAIN=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('domain',''))" 2>/dev/null)
SYSTEM_ID=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('system_id',''))" 2>/dev/null)
MANAGER=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('manager_address',''))" 2>/dev/null)

if [ -z "$ADMIN_KEY" ] || [ -z "$GATEWAY_URL" ] || [ -z "$AGENT_DOMAIN" ] || [ -z "$MANAGER" ]; then
    step_warn "Missing required config — check $CONFIG_FILE"
    exit 0
fi

# Find agent email address — try env var first, then query API, then profiles
AGENT_EMAIL="${AGENT_EMAIL:-}"
if [ -z "$AGENT_EMAIL" ]; then
    # Query the system for registered email addresses
    AGENT_EMAIL=$(curl -s "${GATEWAY_URL}/api/v1/admin/systems/${SYSTEM_ID}/domains" \
        -H "X-Api-Key: ${ADMIN_KEY}" 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Find the first address entry (contains @) that has webhook_url
for d in data:
    dom = d.get('domain', '')
    if '@' in dom and d.get('webhook_url'):
        print(dom)
        sys.exit(0)
# Fallback: first address entry
for d in data:
    dom = d.get('domain', '')
    if '@' in dom:
        print(dom)
        sys.exit(0)
print('')
" 2>/dev/null || echo "")
fi
if [ -z "$AGENT_EMAIL" ]; then
    for f in "$HOME/.hermes/profiles/"*/amail.json; do
        [ -f "$f" ] || continue
        AE=$(python3 -c "import json; print(json.load(open('$f')).get('email',''))" 2>/dev/null)
        if [ -n "$AE" ]; then AGENT_EMAIL="$AE"; break; fi
    done
fi
if [ -z "$AGENT_EMAIL" ]; then
    AGENT_EMAIL="${AGENT_EMAIL:-agent@${AGENT_DOMAIN}}"
fi

echo "  Gateway:     $GATEWAY_URL"
echo "  Agent email: $AGENT_EMAIL"
echo "  Manager:     $MANAGER"

# If no agent email found in current system, register a temporary one
REGISTERED_AGENT=""
if [ -z "$AGENT_EMAIL" ] || ! curl -s "${GATEWAY_URL}/api/v1/admin/systems/${SYSTEM_ID}/domains" \
    -H "X-Api-Key: ${ADMIN_KEY}" 2>/dev/null | python3 -c "
import sys, json; data = json.load(sys.stdin)
ok = any('@' in d.get('domain','') for d in data)
sys.exit(0 if ok else 1)
"; then
    # Register a test agent under this system
    TS=$(date +%s)
    AGENT_EMAIL="test-agent-${TS}@${AGENT_DOMAIN}"
    echo "  Registering temporary agent: $AGENT_EMAIL"
    ADDR_RESP=$(curl -s -X POST "${GATEWAY_URL}/api/v1/admin/systems/${SYSTEM_ID}/addresses" \
        -H "X-Api-Key: ${ADMIN_KEY}" -H "Content-Type: application/json" \
        -d "{\"id\":\"test-${TS}\",\"email\":\"${AGENT_EMAIL}\",\"manager_address\":\"${MANAGER}\"}" 2>/dev/null)
    # Create whitelist for manager
    curl -s -X POST "${GATEWAY_URL}/api/v1/admin/whitelists" \
        -H "X-Api-Key: ${ADMIN_KEY}" -H "Content-Type: application/json" \
        -d "{\"system_id\":\"${SYSTEM_ID}\",\"domain_addr\":\"${AGENT_EMAIL}\",\"direction\":\"all\",\"value\":\"${MANAGER}\"}" > /dev/null
    REGISTERED_AGENT="$AGENT_EMAIL"
fi

# ── Build auth SMTP FROM ──
b64_key=$(python3 -c "
import base64, sys
try:
    key = bytes.fromhex('$ADMIN_KEY')
    raw = base64.b64encode(key).decode()
    # Remove padding for embedding (will be re-added on decode)
    print(raw.rstrip('='))
except: sys.exit(1)
" 2>/dev/null || echo "")
if [ -z "$b64_key" ]; then
    step_warn "Failed to encode admin key"
    exit 0
fi
encoded_manager=$(echo "$MANAGER" | sed 's/@/=/g')
AUTH_FROM="${b64_key}=${encoded_manager}@auth.local"

# ── Baseline: amail.log + stats ──
BEFORE_LOG=$(wc -l < "$HOME/.hermes/amail.log" 2>/dev/null || echo 0)
BEFORE_SENT=$(curl -s "$GATEWAY_URL/api/v1/stats/agent/me?email=${AGENT_EMAIL}" \
    -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('sent',-1))" 2>/dev/null || echo -1)
BEFORE_RECV=$(curl -s "$GATEWAY_URL/api/v1/stats/agent/me?email=${AGENT_EMAIL}" \
    -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('received',-1))" 2>/dev/null || echo -1)

echo -n "  Sending welcome email via SMTP... "

# ── SMTP send with auth ──
SMTP_HOST=$(echo "$GATEWAY_URL" | sed 's|^https\?://||;s|:.*||')
SMTP_PORT=25

SEND_OUTPUT=$(python3 << PYEOF 2>&1
import socket, base64
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(15)
    s.connect(("$SMTP_HOST", $SMTP_PORT))
    def r(): return s.recv(4096).decode()
    r()  # banner
    s.sendall(b"EHLO amail-integration-test\\r\\n")
    r()
    s.sendall(b"MAIL FROM:<${AUTH_FROM}>\\r\\n")
    mail_resp = r()
    s.sendall(b"RCPT TO:<${AGENT_EMAIL}>\\r\\n")
    rcpt_resp = r()
    s.sendall(b"DATA\\r\\n")
    data_resp = r()
    body = "From: $MANAGER\\nTo: $AGENT_EMAIL\\nSubject: 🎉 Welcome! Your amail integration is live\\n\\nHello! This is your first email delivered through your new amail system.\\n\\nPlease reply with the current server time to confirm the mail loop is working.\\n\\n--\\nThis confirms: ✅ SMTP inbound ✅ Webhook delivery ✅ Agent processing ✅ Outbound reply\\n."
    s.sendall(body.encode() + b"\\r\\n.\\r\\n")
    data_end = r()
    s.sendall(b"QUIT\\r\\n")
    s.close()
    print(f"MAIL:{mail_resp.strip()}|RCPT:{rcpt_resp.strip()}|DATA:{data_end.strip()}")
except Exception as e:
    print(f"ERROR:{e}")
PYEOF
)

echo "$SEND_OUTPUT"

if echo "$SEND_OUTPUT" | grep -q 'DATA:250 OK\|DATA:250 2'; then
    echo "  $T_OK"
else
    echo "  $T_FAILED"
    info "  SMTP response: $SEND_OUTPUT"
    step_warn "SMTP send failed — check gateway connectivity and agent address"
    exit 0
fi

# ── Poll for delivery (5s × 6 = 30s max) ──
VERIFIED=false
for i in $(seq 1 6); do
    sleep 5
    NOW_LOG=$(wc -l < "$HOME/.hermes/amail.log" 2>/dev/null || echo 0)
    LOG_DELTA=$((NOW_LOG - BEFORE_LOG))

    NOW_SENT=$(curl -s "$GATEWAY_URL/api/v1/stats/agent/me?email=${AGENT_EMAIL}" \
        -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('sent',-1))" 2>/dev/null || echo -1)
    NOW_RECV=$(curl -s "$GATEWAY_URL/api/v1/stats/agent/me?email=${AGENT_EMAIL}" \
        -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('received',-1))" 2>/dev/null || echo -1)

    LOG_OK=false
    STATS_OK=false

    # amail.log should show inbound + outbound entries
    if [ "$LOG_DELTA" -ge 2 ] && tail -1 "$HOME/.hermes/amail.log" 2>/dev/null | grep -q '"Re:'; then
        LOG_OK=true
    fi
    # Stats should show +1 sent and +1 received
    [ "$NOW_SENT" -gt "$BEFORE_SENT" ] && [ "$NOW_RECV" -gt "$BEFORE_RECV" ] && STATS_OK=true

    if $LOG_OK && $STATS_OK; then
        VERIFIED=true
        break
    fi
done

if $VERIFIED; then
    step_ok "双向收发验证通过 — agent 已接收并回复了测试邮件"
else
    step_warn "超时 — 测试邮件已发送但未在 30 秒内收到 agent 回复"
    info "  amail.log delta: $(( $(wc -l < "$HOME/.hermes/amail.log" 2>/dev/null || echo 0) - BEFORE_LOG )) 行"
    info "  Stats sent: $NOW_SENT (before: $BEFORE_SENT), received: $NOW_RECV (before: $BEFORE_RECV)"
fi

# Cleanup temporary agent
if [ -n "$REGISTERED_AGENT" ]; then
    ADDR_ID=$(curl -s "${GATEWAY_URL}/api/v1/admin/systems/${SYSTEM_ID}/domains" \
        -H "X-Api-Key: ${ADMIN_KEY}" 2>/dev/null | python3 -c "
import sys, json; data = json.load(sys.stdin)
ids = [x['id'] for x in data if x.get('domain','') == '$REGISTERED_AGENT']
print(ids[0] if ids else '')
" 2>/dev/null)
    [ -n "$ADDR_ID" ] && curl -s -X DELETE "${GATEWAY_URL}/api/v1/admin/system-domains/${ADDR_ID}" -H "X-Api-Key: ${ADMIN_KEY}" > /dev/null
fi
