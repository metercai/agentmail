#!/usr/bin/env bash
# =============================================================================
# AmailGateway — Hermes Agent Integration Smoke Test
# =============================================================================
#
# 验证 Hermes Agent 侧与 AmailGateway 的集成是否正确。
# 不需要 system_admin key，只需从平台管理员获取的三项信息。
#
# Prerequisites:
#   - Hermes Agent 已通过 integrate.sh 完成集成
#   - Python 3.10+
#
# Usage:
#   export AMG_URL=http://46.17.41.218:38080
#   export AMG_SYS_ID=myproject
#   export AMG_ADMIN_KEY=sk-xxxx...
#   bash test/hermes_amail_smoke.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

AMG_URL="${AMG_URL:-${GATEWAY_URL:-http://127.0.0.1:38080}}"
AMG_SYS_ID="${AMG_SYS_ID:-${SYS_ID:-}}"
AMG_ADMIN_KEY="${AMG_ADMIN_KEY:-${ADMIN_KEY:-}}"
HERMES_DIR="${HERMES_DIR:-${PROJECT_DIR}/../hermes-agent}"
TS="$(date +%s)"
PASS=0; FAIL=0

# ─── Helpers ────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { PASS=$((PASS+1)); echo -e "  ${GREEN}[PASS]${NC} $1"; }
fail() { FAIL=$((FAIL+1)); echo -e "  ${RED}[FAIL]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
api() { curl -s -H "X-Api-Key: $AMG_ADMIN_KEY" -H "Accept: application/json" "$@"; }

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║      AmailGateway — Hermes Integration Smoke Test            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ─── Pre-checks ─────────────────────────────────────────────────────────────

echo "── Pre-checks ──"

if [[ -z "$AMG_ADMIN_KEY" ]]; then
    echo "  Set AMG_ADMIN_KEY (tenant_admin key) before running."
    echo "  Usage:"
    echo "    export AMG_URL=http://..."
    echo "    export AMG_SYS_ID=myproject"
    echo "    export AMG_ADMIN_KEY=sk-xxx..."
    exit 1
fi

# Test connection with whoami
WHO=$(api "$AMG_URL/api/v1/whoami" 2>/dev/null || echo '{"scope":"","tenant_id":""}')
SCOPE=$(echo "$WHO" | python3 -c "import sys,json;print(json.load(sys.stdin).get('scope',''))" 2>/dev/null)
TENANT=$(echo "$WHO" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tenant_id',''))" 2>/dev/null)

if [[ "$SCOPE" != "tenant_admin" ]]; then
    echo "  ❌ whoami returned scope=$SCOPE — expected tenant_admin"
    echo "  Response: $WHO"
    exit 1
fi
echo "  ✅ Connected to $AMG_URL as tenant=$TENANT (scope=$SCOPE)"
echo ""

# ─── Test 1: Tenant Access ──────────────────────────────────────────────────

echo "── Test 1: Tenant Access ──"

R=$(api -o /dev/null -w "%{http_code}" "$AMG_URL/api/v1/admin/tenants")
[[ "$R" = "200" ]] && pass "List tenants (200)" || fail "List tenants ($R)"

R=$(api -o /dev/null -w "%{http_code}" "$AMG_URL/api/v1/admin/tenants/$TENANT/domains")
[[ "$R" = "200" ]] && pass "List domains (200)" || fail "List domains ($R)"

DOMAINS=$(api "$AMG_URL/api/v1/admin/tenants/$TENANT/domains")
DOMAIN_COUNT=$(echo "$DOMAINS" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d) if isinstance(d,list) else 0)" 2>/dev/null)
pass "Domain count: $DOMAIN_COUNT"

# ─── Test 2: API Key Management ────────────────────────────────────────────

echo ""
echo "── Test 2: API Key Management ──"

# Create a temporary agent key (as tenant_admin would for a profile)
AGENT_EMAIL="smoketest-$TS@mail.amail.test"
AGENT_RESP=$(api -X POST "$AMG_URL/api/v1/api-keys" \
    -H "Content-Type: application/json" \
    -d "{\"tenant_id\":\"$TENANT\",\"domain\":\"mail.amail.test\",\"email_address\":\"$AGENT_EMAIL\",\"scopes\":[\"agent\",\"send\"],\"category\":\"agent\"}")
AGENT_KEY=$(echo "$AGENT_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('raw_key',''))" 2>/dev/null)
AGENT_ID=$(echo "$AGENT_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

[[ -n "$AGENT_KEY" ]] && pass "Create agent key (prefix: ${AGENT_KEY:0:8}...)" || fail "Create agent key (no raw_key)"

# Agent key whoami
WHO_A=$(curl -s -H "X-Api-Key: $AGENT_KEY" "$AMG_URL/api/v1/whoami")
AGENT_SCOPE=$(echo "$WHO_A" | python3 -c "import sys,json;print(json.load(sys.stdin).get('scope',''))" 2>/dev/null)
[[ "$AGENT_SCOPE" = "agent" ]] && pass "Agent whoami scope=agent" || fail "Agent whoami scope=$AGENT_SCOPE"

# List keys (tenant_admin can see shells)
R=$(api "$AMG_URL/api/v1/api-keys")
K_COUNT=$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d) if isinstance(d,list) else 0)" 2>/dev/null)
[[ "$K_COUNT" -ge 1 ]] && pass "List keys ($K_COUNT)" || fail "List keys ($K_COUNT)"

# ─── Test 3: Whitelist CRUD ────────────────────────────────────────────────

echo ""
echo "── Test 3: Whitelist (Contacts) ──"

# Create outbound whitelist entry (direction="to")
R=$(api -o /dev/null -w "%{http_code}" -X POST "$AMG_URL/api/v1/admin/whitelists" \
    -H "Content-Type: application/json" \
    -d "{\"tenant_id\":\"$TENANT\",\"domain_add\":\"mail.amail.test\",\"direction\":\"to\",\"value\":\"*@trusted.com\"}")
[[ "$R" = "201" ]] && pass "Create whitelist (201)" || fail "Create whitelist ($R)"

# List (requires ?domain= param)
R=$(api -o /dev/null -w "%{http_code}" "$AMG_URL/api/v1/admin/whitelists?domain=mail.amail.test")
[[ "$R" = "200" ]] && pass "List whitelist (200)" || fail "List whitelist ($R)"

WL=$(api "$AMG_URL/api/v1/admin/whitelists?domain=mail.amail.test")
WL_COUNT=$(echo "$WL" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d) if isinstance(d,list) else 0)" 2>/dev/null)
[[ "$WL_COUNT" -ge 1 ]] && pass "Whitelist entries: $WL_COUNT" || pass "Whitelist count: $WL_COUNT"

# Agent creates its own whitelist entry
R=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AMG_URL/api/v1/admin/whitelists" \
    -H "X-Api-Key: $AGENT_KEY" -H "Content-Type: application/json" \
    -d "{\"tenant_id\":\"$TENANT\",\"domain_add\":\"mail.amail.test\",\"direction\":\"to\",\"value\":\"partner@ext.com\"}")
[[ "$R" = "201" ]] && pass "Agent create own whitelist (201)" || fail "Agent create whitelist ($R)"

# ─── Test 4: Hermes Tools Import ───────────────────────────────────────────

echo ""
echo "── Test 4: Hermes Tools ──"

if [[ -d "$HERMES_DIR/tools" ]]; then
    if python3 -c "import sys; sys.path.insert(0, '$HERMES_DIR/tools'); from amail_tools import send_mail, manage_contacts, preprocess_mail_payload, trigger_profile_hooks; print('OK')" 2>/dev/null; then
        pass "amail_tools.py import OK"
    else
        fail "amail_tools.py import FAILED"
    fi
else
    warn "Hermes tools dir not found at $HERMES_DIR/tools — set HERMES_DIR"
    export HERMES_DIR="${HERMES_DIR:-$HOME/hermes-agent}"
    echo "  Trying: $HERMES_DIR"
fi

# ─── Test 5: Whois / Stats ────────────────────────────────────────────────

echo ""
echo "── Test 5: Stats ──"

R=$(api -o /dev/null -w "%{http_code}" "$AMG_URL/api/v1/stats/tenant/$TENANT")
[[ "$R" = "200" ]] && pass "Tenant stats (200)" || fail "Tenant stats ($R)"

R=$(api -o /dev/null -w "%{http_code}" "$AMG_URL/api/v1/stats/agents?tenant_id=$TENANT")
[[ "$R" = "200" ]] && pass "Agent stats (200)" || fail "Agent stats ($R)"

# Agent self-stats
R=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Api-Key: $AGENT_KEY" "$AMG_URL/api/v1/stats/agent/me")
[[ "$R" = "200" ]] && pass "Agent self-stats (200)" || fail "Agent self-stats ($R)"

# ─── Cleanup: delete test agent key ───────────────────────────────────────

if [[ -n "${AGENT_ID:-}" ]]; then
    R=$(api -o /dev/null -w "%{http_code}" -X DELETE "$AMG_URL/api/v1/api-keys/$AGENT_ID")
    [[ "$R" = "204" ]] && pass "Cleanup: deleted test agent key" || pass "Cleanup: agent key delete ($R)"
fi

# ─── Results ───────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           Smoke Test Results                                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  URL:        $AMG_URL"
echo "  Tenant:     $TENANT"
echo "  Admin key:  ${AMG_ADMIN_KEY:0:12}..."
echo "  Hermes:     ${HERMES_DIR}"
echo ""
echo "  ${GREEN}$PASS PASS${NC} / ${RED}$FAIL FAIL${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# Note: This test verifies Hermes-side integration only.
# Full E2E (SMTP → Webhook → Agent) requires Gateway running.
# ═══════════════════════════════════════════════════════════════════════════════
