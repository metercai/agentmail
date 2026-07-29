#!/usr/bin/env bash
# integrate.sh — amail Hermes one-click integration script
# =============================================================================
# Usage: bash integrate.sh
#
# Steps:
#   [1] Gateway connectivity
#   [2] Domain selection (admin_key) / Activation + system_name (product code)
#   [3] Basic config (snapshots, manager address, webhook mode)
#   [4] Save config + deploy bridge
#   [5] Install Hermes tools
#   [6] Configure Hermes (patches + profiles + gateway)
#   [7] Diagnostics
#   [8] Send/receive test
# =============================================================================
TOTAL_STEPS=8

set -eo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
BOLD='\033[1m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export SCRIPT_DIR
SCRIPT_DIR="$SCRIPT_DIR/lib"

# ── Language selection ──────────────────────────────────────────
LANG_CHOICE="${AMAIL_LANG:-}"
if [ -z "$LANG_CHOICE" ]; then
    echo ""
    echo -e "${BOLD}${YELLOW}Select language / 选择语言:${NC}"
    echo "  [1] English"
    echo "  [2] 中文"
    echo -n "  Choice (1/2) [1]: "
    read -r LANG_ANS
    LANG_ANS="${LANG_ANS:-1}"
    [ "$LANG_ANS" = "2" ] && LANG_CHOICE="zh" || LANG_CHOICE="en"
fi

# ── Load language strings and helpers ───────────────────────────
source "$SCRIPT_DIR/i18n.sh"
source "$SCRIPT_DIR/helpers.sh"

TOOLS_PY="$SCRIPT_DIR/tools/hermes/agentmail_tools.py"
HERMES_DIR="${HERMES_DIR:-$HOME/.hermes/hermes-agent}"

# ═══════════════════════════════════════════════════════════════
# Step 0: Agent system detection
# ═══════════════════════════════════════════════════════════════
AGENT_SYSTEM="${AMAIL_AGENT_SYSTEM:-}"
AGENT_HOME=""
if [ -z "$AGENT_SYSTEM" ]; then
    echo ""
    echo -e "${BOLD}${YELLOW}Select agent system / 选择 Agent 系统:${NC}"
    AGENTS_JSON=$(python3 "$SCRIPT_DIR/scripts/detect_agents.py" 2>/dev/null || echo '[]')
    AGENT_COUNT=$(echo "$AGENTS_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    if [ "$AGENT_COUNT" = "0" ]; then
        echo -e "  ${YELLOW}No agent system detected. Hermes Agent and OpenClaw are supported.${NC}"
        echo -n "  Manually enter agent home dir [~/.hermes]: "
        read -r _MANUAL_HOME
        AGENT_HOME="${_MANUAL_HOME:-$HOME/.hermes}"
        AGENT_SYSTEM="hermes"
    else
        IDX=1
        echo "$AGENTS_JSON" | python3 -c "
import sys,json
for a in json.load(sys.stdin):
    profiles = [p['name'] for p in a.get('profiles',[])][:3]
    extra = f' +{len(a[\"profiles\"])-3} more' if len(a.get('profiles',[])) > 3 else ''
    plist = ', '.join(profiles) + extra
    print(f'  [{IDX}] {a[\"product\"]} v{a[\"version\"]} ({len(a[\"profiles\"])} profiles: {plist})')
" IDX="$IDX" 2>/dev/null
        echo -n "  Choice [1]: "; read -r AGENT_CHOICE
        AGENT_CHOICE="${AGENT_CHOICE:-1}"
        # Map choice to product name
        AGENT_SYSTEM=$(echo "$AGENTS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$AGENT_CHOICE-1]['product'].split()[0].lower() if $AGENT_CHOICE <= len(d) else 'hermes')" 2>/dev/null || echo "hermes")
    fi
fi
case "$AGENT_SYSTEM" in
    hermes|Hermes*) AGENT_HOME="${AGENT_HOME:-$HOME/.hermes}" ;;
    openclaw|OpenClaw*) AGENT_HOME="${AGENT_HOME:-$HOME/.openclaw}" ;;
    *) AGENT_HOME="$HOME/.hermes" ;;
esac
export AGENT_SYSTEM AGENT_HOME

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
TITLE="$T_TITLE" python3 "$SCRIPT_DIR/print_banner.py"

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Step 1: Configure agentmail gateway                                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
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

PRODUCT_CODE=""
USE_PRODUCT_CODE=false

# Helper: find agentmail_gateway.json under ~/.agentmail/{system_id}/
_find_gw_cfg() {
    echo "$HOME/.agentmail/$SYSTEM_ID/agentmail_gateway.json"
}

# Helper: find agentmail.json under ~/.agentmail/{system_id}/
_find_agent_cfg() {
    echo "$HOME/.agentmail/$SYSTEM_ID/agentmail.json"
}

# Reuse existing config (skip if product code is explicitly requested)
REUSED_KEY=false
_GW_CFG=$(_find_gw_cfg)
if [ -z "${AMAIL_PRODUCT_CODE:-}" ] && [ -n "$_GW_CFG" ]; then
    STORED_KEY=$(python3 -c "import json; print(json.load(open('$_GW_CFG')).get('admin_key',''))" 2>/dev/null || echo "")
    STORED_URL=$(python3 -c "import json; print(json.load(open('$_GW_CFG')).get('gateway_url',''))" 2>/dev/null || echo "")
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
        echo "  $T_SELECT_AUTH"
        echo "    [1] $T_AUTH_OPT1"
        echo "    [2] $T_AUTH_OPT2"
        echo -n "  $T_CHOOSE (1/2) [1]: "; read -r AUTH_MODE
        AUTH_MODE="${AUTH_MODE:-1}"
        if [ "$AUTH_MODE" = "2" ]; then
            USE_PRODUCT_CODE=true
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
                echo -n "  $T_USE_KEY (Y/n) [Y]: "; read -r USE_AUTO
                if [ "${USE_AUTO:-Y}" = "Y" ] || [ "${USE_AUTO:-y}" = "y" ]; then
                    ADMIN_KEY="$AUTO_KEY"
                fi
            fi
            if [ -z "$ADMIN_KEY" ]; then
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
    CATEGORY=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category','?'))" 2>/dev/null || echo "?")
    AGENT_ADMIN_EMAIL=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('email','') or json.load(sys.stdin).get('email_address',''))" 2>/dev/null || echo "")
    step_ok "$T_ADMIN_KEY_OK ($SYSTEM_ID)"
else
    [ -z "$ADMIN_KEY" ] && step_fail "admin_key cannot be empty"
    echo -n "  $T_VERIFY "
    WHOAMI=$(curl -s "$GATEWAY_URL/api/v1/whoami" -H "X-Api-Key: *** 2>/dev/null || echo '{}')
    SCOPE=$(echo "$WHOAMI" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('scope','') or ','.join(d.get('scopes',[])))" 2>/dev/null || echo "")
    CATEGORY=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category','?'))" 2>/dev/null || echo "?")
    SYSTEM_ID=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null || echo "")
    AGENT_ADMIN_EMAIL=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('email','') or json.load(sys.stdin).get('email_address',''))" 2>/dev/null || echo "")
    [ -z "$SYSTEM_ID" ] && step_fail "Failed to determine system_id from whoami"
    if echo "$SCOPE" | grep -qE "platform|system|agent_admin"; then
        echo -e "${GREEN}$T_OK${NC}"
        step_ok "$T_ADMIN_KEY_OK ($SYSTEM_ID)"
    else
        echo -e "${RED}$T_FAILED${NC}"
        step_fail "$T_SCOPE_FAIL"
    fi
fi

# ── Mode detection (after whoami) ──────────────────────────────
AGENT_ADMIN_MODE=false
SHARED_DOMAIN_MODE=false
if [ "$CATEGORY" = "agent_admin" ]; then
    AGENT_ADMIN_MODE=true
    if echo "$SYSTEM_ID" | grep -q "^shared-"; then
        SHARED_DOMAIN_MODE=true
    fi
fi

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Step 2: Domain selection / shared-domain activation                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
if ! $USE_PRODUCT_CODE; then
    # ── Mode-aware domain handling ──
    if $AGENT_ADMIN_MODE && $SHARED_DOMAIN_MODE; then
        # Shared domain + agent_admin: domain is fixed, skip Step 2
        AMAIL_DOMAIN="${AMAIL_DOMAIN:-}"
        [ -z "$AMAIL_DOMAIN" ] && AMAIL_DOMAIN=$(python3 -c "import json; print(json.load(open('$_GW_CFG')).get('domain',''))" 2>/dev/null || echo "")
        DOMAIN_OK_COUNT=1
        step_ok "shared domain = $AMAIL_DOMAIN (from config)"
    else
        source "$SCRIPT_DIR/select_domain.sh"
    fi    # mode-aware domain handling
else
    if echo "$PRODUCT_CODE" | grep -q "^shared-"; then
        step_begin "$T_ACTIVATE"
        # Shared domain: activate via Python (reliable)
        export GATEWAY_URL PRODUCT_CODE
        ACTIVATE_RESULT=$(python3 "$SCRIPT_DIR/activate_system.py")
        # Parse result markers
        SYSTEM_ID=$(echo "$ACTIVATE_RESULT" | grep '^::set-system-id::' | sed 's/.*::set-system-id::\(.*\)/\1/')
        ADMIN_KEY=$(echo "$ACTIVATE_RESULT" | grep '^::set-admin-key::' | sed 's/.*::set-admin-key::\(.*\)/\1/')
        AMAIL_DOMAIN=$(echo "$ACTIVATE_RESULT" | grep '^::set-domain::' | sed 's/.*::set-domain::\(.*\)/\1/')
        SYSTEM_NAME=$(echo "$ACTIVATE_RESULT" | grep '^::set-system-name::' | sed 's/.*::set-system-name::\(.*\)/\1/')
        # Save raw system admin key immediately after activation
        if [ -n "$SYSTEM_ID" ] && [ -n "$ADMIN_KEY" ]; then
            mkdir -p "$HOME/.agentmail/.system_raw_key"
            echo "$ADMIN_KEY" > "$HOME/.agentmail/.system_raw_key/${SYSTEM_ID}_admin.key"
        fi
        if [ -n "$SYSTEM_ID" ] && [ -n "$ADMIN_KEY" ]; then
            USE_PRODUCT_CODE=false
            step_ok "system activated (id: ${SYSTEM_ID:0:8}..., identifier: $SYSTEM_NAME)"
        else
            if echo "$ACTIVATE_RESULT" | grep -q 'code_claimed'; then
                step_fail "Activation code already claimed"
            fi
            step_fail "System activation failed"
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
fi

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Step 3: Basic configuration (snapshots, manager, webhook mode)            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
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
# agent_admin mode: prefill manager_address from whoami email_address
_MGR_DEFAULT=""
if $AGENT_ADMIN_MODE && [ -n "$AGENT_ADMIN_EMAIL" ]; then
    _MGR_DEFAULT="$AGENT_ADMIN_EMAIL"
elif [ "$(read_config "manager_address")" != "" ]; then
    _MGR_DEFAULT="$(read_config "manager_address")"
fi
MANAGER_ADDRESS=$(ask_param "$T_MANAGER_PROMPT" "AMAIL_MANAGER_ADDRESS" "manager_address" "$_MGR_DEFAULT")

WEBHOOK_MODE="${AMAIL_WEBHOOK_MODE:-bridge}"
WEBHOOK_HOST="${AMAIL_WEBHOOK_HOST:-}"

_gw_host="$(echo "$GATEWAY_URL" | sed 's|^https\?://||;s|:.*||;s|/.*||')"
if echo "$_gw_host" | grep -qE '^(127\.|0\.0\.0\.0|localhost|::1)$'; then
    info "$T_LOCAL_GATEWAY"
    WEBHOOK_HOST=""
    python3 -c "
import json, os
p = '$_GW_CFG' if os.path.exists('$_GW_CFG') else ''
cfg = json.load(open(p)) if p else {}
cfg['webhook_host'] = ''
json.dump(cfg, open(p, 'w'), indent=2)
"
elif [ -z "$AMAIL_WEBHOOK_HOST" ]; then
    echo "  $T_WEBHOOK_MODE"
    echo "  $T_CHOOSE_ENV"
    echo "    [1] $T_WEBHOOK_OPT3"
    echo "    [2] $T_WEBHOOK_OPT2"
    echo "    [3] $T_WEBHOOK_OPT1"
    echo -n "  $T_CHOOSE (1/2/3) [1]: "; read -r WH_MODE
    WH_MODE="${WH_MODE:-1}"
    if [ "$WH_MODE" = "1" ]; then
        WEBHOOK_MODE="bridge"
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
        WEBHOOK_MODE="direct"
        read -r -p "  Public addr [ip:port]: " WEBHOOK_HOST
        while ! echo "$WEBHOOK_HOST" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' || \
              echo "$WEBHOOK_HOST" | grep -qE '^10\.|^172\.1[6-9]\.|^172\.2[0-9]\.|^172\.3[0-1]\.|^192\.168\.|^127\.'; do
            info "  Must be public IP:port (not 127.x/10.x/172.16-31.x/192.168.x)"
            read -r -p "  Public addr [ip:port]: " WEBHOOK_HOST
        done
        step_ok "public address = $WEBHOOK_HOST"
    fi
else
    WEBHOOK_HOST="$AMAIL_WEBHOOK_HOST"
    if echo "$WEBHOOK_HOST" | grep -qE '^10\.|^172\.1[6-9]\.|^172\.2[0-9]\.|^172\.3[0-1]\.|^192\.168\.|^127\.|^::1$|^localhost'; then
        WEBHOOK_MODE="internal"
    else
        WEBHOOK_MODE="direct"
    fi
fi

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Step 4: Save config + deploy bridge                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
step_begin "$T_SAVE_CFG"

EXIT_CODE=0
SETUP_RESULT=$(
export INTEGRATE_GATEWAY_URL="$GATEWAY_URL"
export INTEGRATE_SYSTEM_ID="$SYSTEM_ID"
export INTEGRATE_AMAIL_DOMAIN="$AMAIL_DOMAIN"
export INTEGRATE_SAVE_SNAPSHOTS="$SAVE_SNAPSHOTS"
export INTEGRATE_MANAGER_ADDRESS="$MANAGER_ADDRESS"
export INTEGRATE_WEBHOOK_HOST="$WEBHOOK_HOST"
export INTEGRATE_SYSTEM_NAME="$SYSTEM_NAME"
export INTEGRATE_PRODUCT_CODE="$PRODUCT_CODE"
export INTEGRATE_ADMIN_KEY="$ADMIN_KEY"
export INTEGRATE_USE_PRODUCT_CODE="$USE_PRODUCT_CODE"
python3 "$SCRIPT_DIR/scripts/setup_system.py" 2>&1
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

export GATEWAY_URL ADMIN_KEY SYSTEM_ID AMAIL_DOMAIN WEBHOOK_MODE WEBHOOK_HOST USE_PRODUCT_CODE

# Recompute _GW_CFG now that SYSTEM_ID is definitely set
_GW_CFG=$(_find_gw_cfg)

python3 "$SCRIPT_DIR/deploy_bridge.py"

CONFIG_FILE="${_GW_CFG:-$HOME/.agentmail/agentmail_gateway.json}"
if [ -f "$CONFIG_FILE" ]; then
    step_ok "$T_CONFIG_OK $CONFIG_FILE"
else
    step_warn "$T_CONFIG_WARN $CONFIG_FILE"
fi

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Steps 5-8: tools, configure, diagnostics, test                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
source "$SCRIPT_DIR/hermes/install-tools.sh"

# Step 6: Configure Hermes (patches + profiles + gateway)
PATCH_STEP_PARENT=1
step_begin "$T_WEBHOOK"
source "$SCRIPT_DIR/hermes/configure.sh"
unset PATCH_STEP_PARENT

# Step 7: Full pipeline diagnostics + ping-pong test
step_begin "$T_DIAG"
set +e  # non-zero from partial failures must not abort
AMAIL_AGENT_JSON="${_GW_CFG%/agentmail_gateway.json}/agentmail.json"
AMAIL_AGENT=$(python3 -c "import json; print(json.load(open('$AMAIL_AGENT_JSON')).get('email',''))" 2>/dev/null || echo "")
[ -z "$AMAIL_AGENT" ] && AMAIL_AGENT=$(python3 -c "import json; print(json.load(open('$_GW_CFG')).get('domain',''))" 2>/dev/null || echo "")
if [ -n "$AMAIL_AGENT" ]; then
    AGENT_FLAG="--agent $AMAIL_AGENT"
else
    AGENT_FLAG=""
fi
python3 "$SCRIPT_DIR/check_status.py" $AGENT_FLAG
STEP9_EXIT=$?
set -e
if [ $STEP9_EXIT -eq 0 ]; then
    step_ok "$T_DIAG_ALL"
else
    step_warn "$T_DIAG_PARTIAL"
fi
python3 "$SCRIPT_DIR/check_status.py" --ping $AGENT_FLAG

# Step 8: Send welcome email
step_begin "$T_TEST"
python3 "$SCRIPT_DIR/send_welcome.py"
