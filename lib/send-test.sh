# Step 10: online send/receive test
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TEST"

TEST_TS=$(date +%s)
TEST_WL_ID=""

cleanup_test() {
    [ -n "$TEST_WL_ID" ] && curl -s -X DELETE "$GATEWAY_URL/api/v1/admin/whitelists/$TEST_WL_ID" -H "X-Api-Key: $ADMIN_KEY" > /dev/null 2>&1
}
trap cleanup_test EXIT

# Get admin email and system ID from whoami (more reliable than config)
ADMIN_INFO=$(curl -s "$GATEWAY_URL/api/v1/whoami" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null)
ADMIN_EMAIL=$(echo "$ADMIN_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('email',''))" 2>/dev/null)
SYSTEM_ID=$(echo "$ADMIN_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null)

if [ -z "$ADMIN_EMAIL" ]; then
    echo -n "  $T_TEST_CREATE "
    echo "$T_FAILED (cannot determine admin email)"
    step_warn "$T_TEST_FAIL_KEY"
else
    # Create a temporary whitelist entry for the test
    echo -n "  Creating test whitelist... "
    WL_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/whitelists" \
        -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
        -d '{"system_id":"'"$SYSTEM_ID"'","domain_addr":"'"$ADMIN_EMAIL"'","direction":"all","value":"*@example.com"}' 2>/dev/null)
    TEST_WL_ID=$(echo "$WL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
    [ -n "$TEST_WL_ID" ] && echo "$T_OK" || echo "$T_FAILED (non-fatal)"

    # Send a test email using the admin key directly
    echo -n "  $T_TEST_SEND "
    SEND_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/send" \
        -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
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
