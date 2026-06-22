# Step 10: online send/receive test
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TEST"

TEST_TS=$(date +%s)
TEST_KEY_ID=""
TEST_ADDR_ID=""
TEST_WL_ID=""

cleanup_test() {
    [ -n "$TEST_KEY_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/api-keys/$TEST_KEY_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
    [ -n "$TEST_ADDR_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/system-domains/$TEST_ADDR_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
    [ -n "$TEST_WL_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/whitelists/$TEST_WL_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
}
trap cleanup_test EXIT

# Get admin info
ADMIN_INFO=$(curl -s "$GATEWAY_URL/api/v1/whoami" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null)
ADMIN_EMAIL=$(echo "$ADMIN_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('email',''))" 2>/dev/null)
SYSTEM_ID=$(echo "$ADMIN_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null)
HAS_AGENT_SCOPE=$(echo "$ADMIN_INFO" | python3 -c "import sys,json; s=' '.join(json.load(sys.stdin).get('scopes',[])); print('true' if 'agent' in s else 'false')" 2>/dev/null)

if [ -z "$SYSTEM_ID" ]; then
    echo "  $T_FAILED (cannot determine system_id)"
    step_warn "$T_TEST_FAIL_KEY"
else
    # Get primary domain from config
    TEST_DOMAIN=$(cat "$HOME/.hermes/amail_gateway.json" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('domain',''))" 2>/dev/null)

    if [ "$HAS_AGENT_SCOPE" = "true" ] && [ -n "$ADMIN_EMAIL" ] && echo "$ADMIN_EMAIL" | grep -q '@'; then
        # ── Admin key has agent scope + email → can send directly ──
        TEST_AGENT_KEY="$ADMIN_KEY"
        SENDER="$ADMIN_EMAIL"
    else
        # ── Admin key cannot send directly → create an agent key ──
        # ── New activation: SystemAdmin (email="") cannot send directly ──
        # Must create an agent key under a domain address
        if [ -z "$TEST_DOMAIN" ]; then
            echo "  $T_FAILED (no domain configured, cannot create test agent key)"
            step_warn "$T_TEST_FAIL_KEY"
        else
            TEST_EMAIL="test-${TEST_TS}@${TEST_DOMAIN}"

            echo -n "  ${T_TEST_REG} "
            ADDR_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/addresses" \
                -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
                -d '{"id":"test-'${TEST_TS}'","email":"'${TEST_EMAIL}'"}' 2>/dev/null)
            TEST_ADDR_ID=$(echo "$ADDR_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('domain',{}).get('id',''))" 2>/dev/null || true)
            [ -n "$TEST_ADDR_ID" ] && echo "$T_OK" || echo "$T_FAILED (non-fatal)"

            echo -n "  ${T_TEST_API_KEY} "
            KEY_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/api-keys" \
                -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
                -d '{"system_id":"'$SYSTEM_ID'","email_address":"'$TEST_EMAIL'","scopes":["agent"],"category":"agent","name":"amail-integration-test"}' 2>/dev/null)
            TEST_AGENT_KEY=$(echo "$KEY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('raw_key',''))" 2>/dev/null || true)
            TEST_KEY_ID=$(echo "$KEY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
            if [ -n "$TEST_AGENT_KEY" ]; then
                echo "$T_OK (${TEST_AGENT_KEY:0:8}...)"
            else
                echo "$T_FAILED"
                step_warn "$T_TEST_FAIL_KEY"
                TEST_AGENT_KEY=""
            fi

            SENDER="$TEST_EMAIL"
        fi
    fi

    if [ -n "${TEST_AGENT_KEY:-}" ]; then
        # Whitelist for outbound send
        echo -n "  ${T_TEST_WHITELIST} "
        WL_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/whitelists" \
            -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
            -d '{"system_id":"'$SYSTEM_ID'","domain_addr":"'$SENDER'","direction":"all","value":"*@example.com"}' 2>/dev/null)
        TEST_WL_ID=$(echo "$WL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
        [ -n "$TEST_WL_ID" ] && echo "$T_OK" || echo "$T_FAILED (non-fatal)"

        # Send test email
        echo -n "  $T_TEST_SEND "
        SEND_RESP=$(curl -s --max-time 15 -X POST "$GATEWAY_URL/api/v1/send" \
            -H "X-Api-Key: $TEST_AGENT_KEY" -H "Content-Type: application/json" \
            -d '{"to":"test@example.com","subject":"Amail Integration Test","markdown":"This is an automated integration test from amail integrate.sh."}' 2>/dev/null)
        SEND_MSG_ID=$(echo "$SEND_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('email_id','') or json.load(sys.stdin).get('message_id',''))" 2>/dev/null || true)

        if [ -n "$SEND_MSG_ID" ]; then
            echo "$T_OK (id=$SEND_MSG_ID)"
            step_ok "$T_TEST_OK"
        else
            echo "$T_FAILED"
            info "  response: $(echo "$SEND_RESP" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin),indent=2))" 2>/dev/null || echo "$SEND_RESP")"
            step_warn "$T_TEST_FAIL_SEND"
        fi

        # Cleanup
        echo -n "  $T_TEST_CLEAN "
        [ -n "$TEST_KEY_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/api-keys/$TEST_KEY_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
        [ -n "$TEST_ADDR_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/system-domains/$TEST_ADDR_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
        [ -n "$TEST_WL_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/whitelists/$TEST_WL_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
        echo "$T_OK"
    fi
fi
