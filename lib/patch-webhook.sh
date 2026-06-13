# Step 7: Patch Hermes — webhook preprocessor
# ═══════════════════════════════════════════════════════════════
step_begin "$T_WEBHOOK"

WEBHOOK_PY="$HERMES_DIR/gateway/platforms/webhook.py"

if [ ! -f "$WEBHOOK_PY" ]; then
    step_warn "$T_WEBHOOK_MISS"
    info "  $T_WEBHOOK_HINT"
else
    if grep -q "PREPROCESS_REGISTRY" "$WEBHOOK_PY" 2>/dev/null; then
        step_ok "$T_WEBHOOK_OK"
    else
        echo -n "  $T_WEBHOOK_APPLY "
        python3 "$SCRIPT_DIR/patches/apply_webhook_patch.py" "$WEBHOOK_PY" 2>/dev/null && echo "$T_OK" || echo "$T_FAILED"
        if grep -q "PREPROCESS_REGISTRY" "$WEBHOOK_PY" 2>/dev/null; then
            step_ok "$T_WEBHOOK_DONE"
        else
            step_warn "$T_WEBHOOK_FAIL"
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════
