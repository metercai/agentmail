# Step 10: online send/receive test
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TEST"

TEST_TS=$(date +%s)
TEST_EMAIL="amail-test-${TEST_TS}@test-${TEST_TS}.local"
TEST_AGENT_KEY=""
TEST_KEY_ID=""
TEST_DOMAIN_ID=""
TEST_WL_ID=""

echo -n "  $T_TEST_CREATE "
CREATE_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/api-keys" \
    -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
    -d '{"system_id":"'"$SYSTEM_ID"'","email_address":"'"$TEST_EMAIL"'","scopes":["agent","send"],"category":"agent"}' 2>/dev/null)
TEST_AGENT_KEY=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('raw_key',''))" 2>/dev/null)
TEST_KEY_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$TEST_AGENT_KEY" ]; then
    echo "$T_OK (${TEST_AGENT_KEY:0:8}...)"
else
    echo "$T_FAILED"
    step_warn "$T_TEST_FAIL_KEY"
fi

if [ -n "$TEST_AGENT_KEY" ]; then
    # Register test domain
    echo -n "  $T_TEST_REG "
    DOMAIN_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" \
        -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
        -d '{"id":"test-'${TEST_TS}'","domain":"test-'${TEST_TS}'.local"}' 2>/dev/null)
    TEST_DOMAIN_ID=$(echo "$DOMAIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
    [ -n "$TEST_DOMAIN_ID" ] && echo "$T_OK" || echo "$T_FAILED (non-fatal)"

    # Whitelist for outbound send
    WHITELIST_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/whitelists" \
        -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
        -d '{"system_id":"'${SYSTEM_ID}'","domain_addr":"test-'${TEST_TS}'.local","direction":"all","value":"*@example.com"}' 2>/dev/null)
    TEST_WL_ID=$(echo "$WHITELIST_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

    # Send a test email via API
    echo -n "  $T_TEST_SEND "
    SEND_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/send" \
        -H "X-Api-Key: $TEST_AGENT_KEY" -H "Content-Type: application/json" \
        -d '{"to":"test@example.com","subject":"Amail Integration Test","markdown":"This is an automated integration test from amail integrate.sh."}' 2>/dev/null)
    SEND_MSG_ID=$(echo "$SEND_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('email_id','') or json.load(sys.stdin).get('message_id',''))" 2>/dev/null)

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
    [ -n "$TEST_DOMAIN_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/system-domains/$TEST_DOMAIN_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
    [ -n "$TEST_WL_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/whitelists/$TEST_WL_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
    echo "$T_OK"
fi

# ═══════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              $T_DONE                         ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}$T_SUMMARY${NC}"
echo "  ├─ gateway_url:   $GATEWAY_URL"
echo "  ├─ system_id:   $SYSTEM_ID"
if $USE_PRODUCT_CODE; then
    echo "  ├─ $T_AUTH_LABEL:   $T_AUTH_LABEL_PC ${PRODUCT_CODE:0:8}... → admin_key ${ADMIN_KEY:0:8}..."
else
    echo "  ├─ admin_key:   ${ADMIN_KEY:0:8}... (scope: ${SCOPE:-?})"
fi
echo "  ├─ domain:      ${AMAIL_DOMAIN:-$T_UNSET}"
echo "  ├─ snapshots:   $SAVE_SNAPSHOTS"
echo "  ├─ manager:     ${MANAGER_ADDRESS:-<not set>}"
echo "  ├─ webhook:     ${WEBHOOK_HOST:-<auto-detect>}"
echo "  ├─ bridge:      $( [ -n "$WEBHOOK_HOST" ] && echo "configured ($WEBHOOK_HOST)" || echo "not needed" )"
echo "  └─ config:      $CONFIG_FILE"
echo ""
echo -e "  ${BOLD}$T_PATCH${NC}"
if [ -f "$WEBHOOK_PY" ] && grep -q "PREPROCESS_REGISTRY" "$WEBHOOK_PY" 2>/dev/null; then
    echo "  ├─ webhook.py:   $T_PATCHED (preprocessor registry)"
else
    echo "  ├─ webhook.py:   $T_NOT_PATCHED"
fi
if [ -f "$PROFILES_PY" ] && grep -q "trigger_profile_hooks" "$PROFILES_PY" 2>/dev/null; then
    echo "  └─ profiles.py:  $T_PATCHED (profile hooks)"
else
    echo "  └─ profiles.py:  $T_NOT_PATCHED"
fi
echo ""
echo -e "  ${BOLD}$T_NEXT${NC}"
echo "  ├─ $T_NEXT_1"
echo "  ├─ $T_NEXT_2"
echo "  └─ $T_NEXT_3: integrations/hermes/INTEGRATION-REFERENCE.md"
echo ""
