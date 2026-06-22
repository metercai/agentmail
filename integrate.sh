#!/usr/bin/env bash
# integrate.sh — amail Hermes one-click integration script
# =============================================================================
# Usage: bash integrate.sh
#
# Steps: [1] gateway connect  [2] auth method  [3] domain
#        [4] basic config    [5] save / activate  [5a] bridge + domain key
#        [6] install tools   [7] patch webhook   [8] patch profiles
#        [9] diagnostics     [10] send/receive test
# =============================================================================
TOTAL_STEPS=10

set -eo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
BOLD='\033[1m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export SCRIPT_DIR
LIB_DIR="$SCRIPT_DIR/lib"

# ── Language selection ──────────────────────────────────────────
LANG_CHOICE="${AMAIL_LANG:-}"
if [ -z "$LANG_CHOICE" ]; then
    echo ""
    echo -e "${BOLD}Select language / 选择语言:${NC}"
    echo "  [1] English (default)"
    echo "  [2] 中文"
    echo -n "  Choice [1/2]: "
    read -r LANG_ANS
    LANG_ANS="${LANG_ANS:-1}"
    [ "$LANG_ANS" = "2" ] && LANG_CHOICE="zh" || LANG_CHOICE="en"
fi

# ── Load language strings and helpers ───────────────────────────
source "$LIB_DIR/i18n.sh"
source "$LIB_DIR/helpers.sh"

TOOLS_PY="$SCRIPT_DIR/tools/amail_tools.py"
HERMES_DIR="${HERMES_DIR:-$HOME/.hermes/hermes-agent}"

# ── Load .env file ──────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
fi

if [ ! -f "$TOOLS_PY" ]; then
    echo -e "${RED}[ERROR] $T_ERR_NO_TOOLS: $TOOLS_PY${NC}"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         ${T_TITLE}                       ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"

# ═══════════════════════════════════════════════════════════════
# Step 1: gateway_url
# ═══════════════════════════════════════════════════════════════
step_begin "$T_GATEWAY"

DEFAULT_URL="http://127.0.0.1:38080"
if curl -s -o /dev/null -w '%{http_code}' "$DEFAULT_URL/health" 2>/dev/null | grep -q 200; then
    info "$T_DETECT $DEFAULT_URL"
fi
GATEWAY_URL=$(ask_param "gateway_url" "AMAIL_URL" "gateway_url" "$DEFAULT_URL")

# Normalize port — only append non-default ports
if ! echo "$GATEWAY_URL" | grep -qE ':[0-9]+(/|$|#|\?)'; then
    if echo "$GATEWAY_URL" | grep -qi '^https://'; then
        : # no-op — 443 is default for HTTPS
    else
        GATEWAY_URL="${GATEWAY_URL%/}:80"
    fi
fi

echo -n "  $T_CHECKING "
HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "$GATEWAY_URL/health" 2>/dev/null || echo "000")
[ "$HEALTH" != "200" ] && { echo -e "${RED}$T_FAILED (HTTP $HEALTH)${NC}"; step_fail "Cannot reach $GATEWAY_URL/health"; }
UPTIME=$(curl -s "$GATEWAY_URL/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('uptime_secs','?'))" 2>/dev/null || echo "?")
echo -e "${GREEN}$T_OK${NC}"
step_ok "$T_GATEWAY_OK ${UPTIME}s)"

# ═══════════════════════════════════════════════════════════════
# Step 2: auth
# ═══════════════════════════════════════════════════════════════
step_begin "$T_AUTH"

PRODUCT_CODE=""
USE_PRODUCT_CODE=false

# Reuse existing config (skip if product code is explicitly requested)
REUSED_KEY=false
if [ -z "${AMAIL_PRODUCT_CODE:-}" ] && [ -f "$HOME/.hermes/amail_gateway.json" ]; then
    STORED_KEY=$(python3 -c "import json; print(json.load(open('$HOME/.hermes/amail_gateway.json')).get('admin_key',''))" 2>/dev/null || echo "")
    STORED_URL=$(python3 -c "import json; print(json.load(open('$HOME/.hermes/amail_gateway.json')).get('gateway_url',''))" 2>/dev/null || echo "")
    if [ -n "$STORED_KEY" ] && [ "$STORED_URL" = "$GATEWAY_URL" ]; then
        echo -n "  $T_VERIFY "
        WHOAMI=$(curl -s "$GATEWAY_URL/api/v1/whoami" -H "X-Api-Key: $STORED_KEY" 2>/dev/null || echo '{}')
        SCOPE=$(echo "$WHOAMI" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('scope','') or ','.join(d.get('scopes',[])))" 2>/dev/null || echo "")
        if echo "$SCOPE" | grep -qE "platform|system"; then
            echo -e "${GREEN}$T_OK${NC}"
            ADMIN_KEY="$STORED_KEY"
            REUSED_KEY=true
            step_ok "$T_DETECT_KEY — reusable (scope: $SCOPE)"
        else
            echo -e "${YELLOW}stale${NC} (invalid scope: $SCOPE)"
        fi
    fi
fi

if ! $REUSED_KEY; then
    ADMIN_KEY="${AMAIL_ADMIN_KEY:-}"
    PRODUCT_CODE="${AMAIL_PRODUCT_CODE:-}"
    if [ -n "$ADMIN_KEY" ] && [ -z "$PRODUCT_CODE" ]; then
        info "$T_AUTH_READ"
    elif [ -n "$PRODUCT_CODE" ] && [ -z "$ADMIN_KEY" ]; then
        USE_PRODUCT_CODE=true
        echo "  $T_AUTH_READ_PC"
    else
        echo ""
        info "$T_SELECT_AUTH"
        info "  [1] $T_AUTH_OPT1"
        info "  [2] $T_AUTH_OPT2"
        echo -n "  $T_CHOOSE [1/2] (default 1): "; read -r AUTH_MODE
        AUTH_MODE="${AUTH_MODE:-1}"
        if [ "$AUTH_MODE" = "2" ]; then
            USE_PRODUCT_CODE=true
            echo "  $T_PC_HELP"
            read -r -p "  $T_PC_PROMPT" PRODUCT_CODE
            [ -z "$PRODUCT_CODE" ] && step_fail "$T_PC_EMPTY"
            info "$T_PC_USING: ${PRODUCT_CODE:0:8}..."
            info "$T_PC_AUTO"
        else
            AUTO_KEY=""; AUTO_PATH=""
            for dir in "." "/tmp/amail-gateway"; do
                [ -d "$dir" ] || continue
                found=$(find "$dir" -maxdepth 1 -name "*.admin_key" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2)
                [ -n "$found" ] && [ -f "$found" ] && AUTO_KEY=$(head -1 "$found") && AUTO_PATH="$found" && break
            done
            if [ -n "$AUTO_KEY" ]; then
                info "$T_DETECT_KEY: $AUTO_PATH (${AUTO_KEY:0:8}...)"
                echo -n "  $T_USE_KEY [Y/n]: "; read -r USE_AUTO
                if [ "${USE_AUTO:-Y}" = "Y" ] || [ "${USE_AUTO:-y}" = "y" ]; then
                    ADMIN_KEY="$AUTO_KEY"
                fi
            fi
            if [ -z "$ADMIN_KEY" ]; then
                echo "  $T_KEY_HINT"
                ADMIN_KEY=$(ask_param "$T_KEY_PROMPT" "AMAIL_ADMIN_KEY" "admin_key" "")
            fi
        fi
    fi
fi

if $USE_PRODUCT_CODE; then
    step_ok "$T_PC_USING (prefix: ${PRODUCT_CODE:0:8}...)"
elif $REUSED_KEY; then
    SYSTEM_ID=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null || echo "")
    [ -z "$SYSTEM_ID" ] && step_fail "Failed to determine system_id from whoami"
    step_ok "$T_ADMIN_KEY_OK (prefix: ${ADMIN_KEY:0:8}..., system_id: $SYSTEM_ID)"
else
    [ -z "$ADMIN_KEY" ] && step_fail "admin_key cannot be empty"
    echo -n "  $T_VERIFY "
    WHOAMI=$(curl -s "$GATEWAY_URL/api/v1/whoami" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo '{}')
    SCOPE=$(echo "$WHOAMI" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('scope','') or ','.join(d.get('scopes',[])))" 2>/dev/null || echo "")
    CATEGORY=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category','?'))" 2>/dev/null || echo "?")
    SYSTEM_ID=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null || echo "")
    [ -z "$SYSTEM_ID" ] && step_fail "Failed to determine system_id from whoami"
    if echo "$SCOPE" | grep -qE "platform|system"; then
        echo -e "${GREEN}$T_OK${NC}"
        step_ok "$T_ADMIN_KEY_OK (prefix: ${ADMIN_KEY:0:8}..., scope: $SCOPE, category: $CATEGORY, system_id: $SYSTEM_ID)"
    else
        echo -e "${RED}$T_FAILED${NC}"
        step_fail "$T_SCOPE_FAIL"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# Step 3: domain
# ═══════════════════════════════════════════════════════════════
if ! $USE_PRODUCT_CODE; then
    step_begin "$T_DOMAIN"
    AMAIL_DOMAIN="${AMAIL_DOMAIN:-}"
    info "$T_DOMAIN_QUERY"
    DOMAINS_JSON=$(curl -s "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo "[]")
    SELECTED_DOMAINS=""
    DOMAIN_OK_COUNT=0

    while true; do
        # Refresh domain list
        DOMAINS_JSON=$(curl -s "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo "[]")
        BARE_DOMAINS=$(echo "$DOMAINS_JSON" | python3 -c "
import sys,json
entries = [d for d in json.load(sys.stdin) if '@' not in d.get('domain','')]
for d in entries:
    print(d['domain'])
" 2>/dev/null)
        DOMAIN_COUNT=$(echo "$BARE_DOMAINS" | sed '/^$/d' | wc -l)

        echo -e "  ${BOLD}$T_DOMAIN_EXISTING:${NC}"
        echo "$DOMAINS_JSON" | python3 -c "
import sys,json
entries = [d for d in json.load(sys.stdin) if '@' not in d.get('domain','')]
for i,d in enumerate(entries,1):
    status = ' (inactive)' if not d.get('is_active') else ''
    print(f'    [{i}] {d.get(\"domain\",\"?\")}{status}')
domain_count = len(entries)
print(f'    [{domain_count+1}] Enter a new domain')
" 2>/dev/null
        echo ""
        echo -n "  $T_DOMAIN_SELECT"; read -r DOMAIN_CHOICE
        DOMAIN_CHOICE="${DOMAIN_CHOICE:-1}"

        # Check if adding new domain
        if [ "$DOMAIN_CHOICE" = "$((DOMAIN_COUNT+1))" ]; then
            read -r -p "  New domain (e.g. 'admin.local'): " NEW_DOMAIN
            if [ -n "$NEW_DOMAIN" ]; then
                # Check if domain already exists globally
                if domain_exists_globally "$NEW_DOMAIN"; then
                    echo -e "  ${YELLOW}Domain '$NEW_DOMAIN' already exists — choose a different one${NC}"
                else
                    SELECTED_DOMAINS="$NEW_DOMAIN"
                    break
                fi
            fi
            continue
        fi

        # Single domain selection
        if echo "$DOMAIN_CHOICE" | grep -qE '^[0-9]+$' && [ "$DOMAIN_CHOICE" -ge 1 ] && [ "$DOMAIN_CHOICE" -le "$DOMAIN_COUNT" ]; then
            SELECTED_DOMAINS=$(echo "$BARE_DOMAINS" | sed -n "${DOMAIN_CHOICE}p")
        fi

        if [ -n "$SELECTED_DOMAINS" ]; then
            break
        fi
        info "No valid domains selected, please try again."
    done

    # Create/confirm all selected domains
    for DOM in $SELECTED_DOMAINS; do
        echo -n "  Ensuring domain '$DOM'... "
        DOMAIN_RESP=$(curl -s -w "\n%{http_code}" -X POST \
            "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" \
            -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
            -d "{\"id\":\"dom-$(echo "$DOM" | tr -c 'a-zA-Z0-9' '-')-$(date +%s)\",\"domain\":\"$DOM\"}" 2>/dev/null || echo "{\"error\":\"curl_failed\"}\n000")
        DOMAIN_HTTP=$(echo "$DOMAIN_RESP" | tail -1)
        if [ "$DOMAIN_HTTP" = "201" ] || [ "$DOMAIN_HTTP" = "200" ]; then
            echo -e "${GREEN}$T_OK${NC}"
            DOMAIN_OK_COUNT=$((DOMAIN_OK_COUNT + 1))
        elif echo "$DOMAIN_RESP" | grep -qi "already exists\|UNIQUE.*domain"; then
            echo -e "${YELLOW}already exists${NC}"
            DOMAIN_OK_COUNT=$((DOMAIN_OK_COUNT + 1))
        else
            echo -e "${YELLOW}failed (will continue)${NC}"
        fi
    done

    # Use first domain as primary for downstream steps
    AMAIL_DOMAIN=$(echo "$SELECTED_DOMAINS" | awk '{print $1}')
    if [ -n "$AMAIL_DOMAIN" ]; then
        step_ok "domains: $SELECTED_DOMAINS ($DOMAIN_OK_COUNT OK)"
    fi
else
    step_begin "$T_DOMAIN"
    while true; do
        if [ -z "$AMAIL_DOMAIN" ]; then
            read -r -p "  $T_DOMAIN_HINT" AMAIL_DOMAIN
        fi
        if [ -z "$AMAIL_DOMAIN" ]; then
            step_fail "$T_DOMAIN_EMPTY"
        fi
        # Check if domain already exists globally
        if domain_exists_globally "$AMAIL_DOMAIN"; then
            echo -e "  ${YELLOW}Domain '$AMAIL_DOMAIN' already exists — choose a different one${NC}"
            AMAIL_DOMAIN=""
        else
            break
        fi
    done
    step_ok "domain = $AMAIL_DOMAIN"
    SYSTEM_ID=""
fi

# ═══════════════════════════════════════════════════════════════
# Step 4: basic configuration
# ═══════════════════════════════════════════════════════════════
step_begin "$T_SNAP_CONFIG"

# Read current config value for display
_SAVE_DEFAULT="yes"
if [ -n "${AMAIL_SAVE_SNAPSHOTS:-}" ]; then
    case "$AMAIL_SAVE_SNAPSHOTS" in
        true|True|TRUE|1|yes|Yes|YES) _SAVE_DEFAULT="yes" ;;
        *) _SAVE_DEFAULT="no" ;;
    esac
elif [ "$(read_config "save_raw_snapshots")" = "false" ]; then
    _SAVE_DEFAULT="no"
fi
echo -n "  $T_SNAP_PROMPT (yes/no) [$_SAVE_DEFAULT]: "
read -r _SAVE_INPUT
_SAVE_INPUT="${_SAVE_INPUT:-$_SAVE_DEFAULT}"
case "$_SAVE_INPUT" in
    y|Y|yes|Yes|YES) SAVE_SNAPSHOTS="true" ;;
    *) SAVE_SNAPSHOTS="false" ;;
esac
unset _SAVE_CURRENT _SAVE_DEFAULT _SAVE_INPUT
MANAGER_ADDRESS=$(ask_param "$T_MANAGER_PROMPT" "AMAIL_MANAGER_ADDRESS" "manager_address" "")

WEBHOOK_MODE="${AMAIL_WEBHOOK_MODE:-bridge}"
WEBHOOK_HOST="${AMAIL_WEBHOOK_HOST:-}"

_gw_host="$(echo "$GATEWAY_URL" | sed 's|^https\?://||;s|:.*||;s|/.*||')"
if echo "$_gw_host" | grep -qE '^(127\.|0\.0\.0\.0|localhost|::1)$'; then
    info "Gateway is local — no bridge needed"
    WEBHOOK_HOST=""
    python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg['webhook_host'] = ''
json.dump(cfg, open(p, 'w'), indent=2)
"
elif [ -z "$AMAIL_WEBHOOK_HOST" ]; then
    echo "  How does your Hermes Agent receive emails from the gateway?"
    echo "    Choose based on your Agent's network environment:"
    echo "    [1] Agent has a public IP — gateway can directly push webhooks to it"
    echo "    [2] An amail-bridge is already deployed in your LAN / on this machine"
    echo "    [3] No bridge yet — auto-deploy one on this machine (recommended)"
    echo -n "  Choose [1/2/3] (default 3): "; read -r WH_MODE
    WH_MODE="${WH_MODE:-3}"
    if [ "$WH_MODE" = "1" ]; then
        WEBHOOK_MODE="direct"
        read -r -p "  Public addr [ip:port]: " WEBHOOK_HOST
        while ! echo "$WEBHOOK_HOST" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' || \
              echo "$WEBHOOK_HOST" | grep -qE '^10\.|^172\.1[6-9]\.|^172\.2[0-9]\.|^172\.3[0-1]\.|^192\.168\.|^127\.'; do
            info "  Must be public IP:port (not 127.x/10.x/172.16-31.x/192.168.x)"
            read -r -p "  Public addr [ip:port]: " WEBHOOK_HOST
        done
        step_ok "public address = $WEBHOOK_HOST"
    elif [ "$WH_MODE" = "2" ]; then
        WEBHOOK_MODE="internal"
        read -r -p "  Internal bridge addr [ip:port]: " WEBHOOK_HOST
        while ! echo "$WEBHOOK_HOST" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' || \
              ! echo "$WEBHOOK_HOST" | grep -qE '^10\.|^172\.1[6-9]\.|^172\.2[0-9]\.|^172\.3[0-1]\.|^192\.168\.'; do
            info "  Must be internal IP:port (10.x/172.16-31.x/192.168.x)"
            read -r -p "  Internal bridge addr [ip:port]: " WEBHOOK_HOST
        done
        step_ok "internal bridge address = $WEBHOOK_HOST"
    else
        WEBHOOK_MODE="bridge"
    fi
else
    WEBHOOK_HOST="$AMAIL_WEBHOOK_HOST"
    if echo "$WEBHOOK_HOST" | grep -qE '^10\.|^172\.1[6-9]\.|^172\.2[0-9]\.|^172\.3[0-1]\.|^192\.168\.|^127\.|^::1$|^localhost'; then
        WEBHOOK_MODE="internal"
    else
        WEBHOOK_MODE="direct"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# Step 5: write config
# ═══════════════════════════════════════════════════════════════
step_begin "$T_SAVE"

EXIT_CODE=0
SETUP_RESULT=$(
export INTEGRATE_GATEWAY_URL="$GATEWAY_URL"
export INTEGRATE_SYSTEM_ID="$SYSTEM_ID"
export INTEGRATE_AMAIL_DOMAIN="$AMAIL_DOMAIN"
export INTEGRATE_SAVE_SNAPSHOTS="$SAVE_SNAPSHOTS"
export INTEGRATE_MANAGER_ADDRESS="$MANAGER_ADDRESS"
export INTEGRATE_WEBHOOK_HOST="$WEBHOOK_HOST"
export INTEGRATE_PRODUCT_CODE="$PRODUCT_CODE"
export INTEGRATE_ADMIN_KEY="$ADMIN_KEY"
export INTEGRATE_USE_PRODUCT_CODE="$USE_PRODUCT_CODE"
python3 << 'PYEOF'
import sys, json, os
sys.path.insert(0, os.environ["SCRIPT_DIR"] + "/tools")
from amail_tools import setup
kwargs = dict(
    gateway_url=os.environ.get("INTEGRATE_GATEWAY_URL", ""),
    system_id=os.environ.get("INTEGRATE_SYSTEM_ID", ""),
    domain=os.environ.get("INTEGRATE_AMAIL_DOMAIN", "") or "",
    save_raw_snapshots=os.environ.get("INTEGRATE_SAVE_SNAPSHOTS", "false") == "true",
    manager_address=os.environ.get("INTEGRATE_MANAGER_ADDRESS", "") or "",
    webhook_host=os.environ.get("INTEGRATE_WEBHOOK_HOST", "") or "",
)
if os.environ.get("INTEGRATE_USE_PRODUCT_CODE", "") == "true":
    kwargs["product_code"] = os.environ.get("INTEGRATE_PRODUCT_CODE", "")
else:
    kwargs["admin_key"] = os.environ.get("INTEGRATE_ADMIN_KEY", "")
result = setup(**kwargs)
display_result = {k: v for k, v in result.items() if k not in ("success", "path")}
print(json.dumps(display_result, indent=2, ensure_ascii=False))
if not result.get("success"): sys.exit(1)
PYEOF
) || EXIT_CODE=$?
_ERR_MSG=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error','') or d.get('detail',''))" 2>/dev/null || echo "")
[ $EXIT_CODE -ne 0 ] && step_fail "Activation failed: ${_ERR_MSG:-Unknown error}"

if $USE_PRODUCT_CODE; then
    NEW_ADMIN_KEY=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('admin_key','') or d.get('raw_key',''))" 2>/dev/null || echo "")
    NEW_SYSTEM_ID=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null || echo "")
    NEW_DOMAIN=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('domain',''))" 2>/dev/null || echo "")
    if [ -n "$NEW_ADMIN_KEY" ]; then
        ADMIN_KEY="$NEW_ADMIN_KEY"
        SYSTEM_ID="$NEW_SYSTEM_ID"
        AMAIL_DOMAIN="$NEW_DOMAIN"
        echo -e "  ${BOLD}$T_ACTIVATED${NC}"
        echo "  ├─ system_id:  ${SYSTEM_ID:-?}"
        echo "  ├─ domain:     ${AMAIL_DOMAIN:-?}"
        echo "  └─ admin_key:  ${ADMIN_KEY:0:8}..."
    else
        step_warn "$T_ACT_FAIL"
    fi
fi

CONFIG_FILE="$HOME/.hermes/amail_gateway.json"
if [ -f "$CONFIG_FILE" ]; then
    step_ok "$T_CONFIG_OK $CONFIG_FILE"
else
    step_warn "$T_CONFIG_WARN $CONFIG_FILE"
fi

# ═══════════════════════════════════════════════════════════════
# Step 5a: bridge deployment + domain key
# ═══════════════════════════════════════════════════════════════
source "$LIB_DIR/deploy-bridge.sh"

# ═══════════════════════════════════════════════════════════════
# Steps 6-10
# ═══════════════════════════════════════════════════════════════
source "$LIB_DIR/install-tools.sh"
source "$LIB_DIR/patch-webhook.sh"
source "$LIB_DIR/patch-profiles.sh"
source "$LIB_DIR/diagnostics.sh"
source "$LIB_DIR/send-test.sh"
