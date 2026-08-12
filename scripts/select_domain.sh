#!/usr/bin/env bash
# select_domain.sh — Interactive domain selection for amail gateway
# Called by integrate.sh Step 2.
# Exports: AMAIL_DOMAIN, DOMAIN_OK_COUNT, SYSTEM_NAME

set -e

SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$SCRIPT_DIR/scripts/helpers.sh"

step_begin "$T_DOMAIN"
_GW_CFG=$(_find_gw_cfg)
export GATEWAY_URL ADMIN_KEY SYSTEM_ID

# Read domain from stored config if env var not set
if [ -z "$AMAIL_DOMAIN" ] && [ -n "$_GW_CFG" ]; then
    AMAIL_DOMAIN=$(python3 -c "import json; print(json.load(open('$_GW_CFG')).get('domain',''))" 2>/dev/null || echo "")
fi

if [ -n "$AMAIL_DOMAIN" ]; then
    SELECTED_DOMAINS="$AMAIL_DOMAIN"
    DOMAIN_OK_COUNT=1
    if [ -z "${SYSTEM_NAME:-}" ]; then
        SYSTEM_NAME=$(python3 -c "import json; print(json.load(open('$_GW_CFG')).get('system_name',''))" 2>/dev/null || echo "")
    fi
    step_ok "domain = $AMAIL_DOMAIN (identifier: ${SYSTEM_NAME:-?})"
    return 0
fi

info "$T_DOMAIN_QUERY"
DOMAINS_JSON=$(curl -s --connect-timeout 10 --max-time 15 \
    "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" \
    -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo "[]")
SELECTED_DOMAINS=""
DOMAIN_OK_COUNT=0

while true; do
    DOMAINS_JSON=$(curl -s --connect-timeout 10 --max-time 15 \
        "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" \
        -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo "[]")
    BARE_DOMAINS=$(python3 -c "
import sys,json
entries = [d['domain'] for d in json.load(sys.stdin) if '@' not in d.get('domain','')]
for d in entries:
    print(d)
" <<< "$DOMAINS_JSON" 2>/dev/null)
    DOMAIN_COUNT=$(echo "$BARE_DOMAINS" | sed '/^$/d' | wc -l)

    echo -e "  ${BOLD}$T_DOMAIN_EXISTING:${NC}"
    echo "$DOMAINS_JSON" | python3 -c "
import sys,json
entries = [d for d in json.load(sys.stdin) if '@' not in d.get('domain','')]
for i,d in enumerate(entries,1):
    status = ' (inactive)' if not d.get('is_active') else ''
    print(f'    [{i}] {d.get(\"domain\",\"?\")}{status}')
print(f'    [{len(entries)+1}] Enter a new domain')
" 2>/dev/null
    echo ""
    echo -n "  $T_DOMAIN_SELECT"; read -r DOMAIN_CHOICE
    DOMAIN_CHOICE="${DOMAIN_CHOICE:-1}"

    # agent_admin users cannot create new domains
    if $AGENT_ADMIN_MODE && [ "$DOMAIN_CHOICE" = "$((DOMAIN_COUNT+1))" ]; then
        echo -e "  ${YELLOW}agent_admin key cannot create domains — select an existing one${NC}"
        continue
    fi

    # Check if adding new domain
    if [ "$DOMAIN_CHOICE" = "$((DOMAIN_COUNT+1))" ]; then
        read -r -p "  New domain (e.g. 'admin.local'): " NEW_DOMAIN
        if [ -n "$NEW_DOMAIN" ]; then
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
    if echo "$DOMAIN_CHOICE" | grep -qE '^[0-9]+$' && \
       [ "$DOMAIN_CHOICE" -ge 1 ] && [ "$DOMAIN_CHOICE" -le "$DOMAIN_COUNT" ]; then
        SELECTED_DOMAINS=$(echo "$BARE_DOMAINS" | sed -n "${DOMAIN_CHOICE}p")
    fi
    [ -n "$SELECTED_DOMAINS" ] && break
    info "No valid domains selected, please try again."
done

# Create/confirm all selected domains
for DOM in $SELECTED_DOMAINS; do
    echo -n "  Ensuring domain '$DOM'... "
    DOMAIN_RESP=$(curl -s -w "\n%{http_code}" -X POST \
        "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" \
        -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
        -d "{\"id\":\"dom-$(echo "$DOM" | tr -c 'a-zA-Z0-9' '-')-$(date +%s)\",\"domain\":\"$DOM\"}" \
        2>/dev/null || echo '{"error":"curl_failed"}\n000')
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

AMAIL_DOMAIN=$(echo "$SELECTED_DOMAINS" | awk '{print $1}')
[ -n "$AMAIL_DOMAIN" ] && step_ok "domains: $SELECTED_DOMAINS ($DOMAIN_OK_COUNT OK)"
