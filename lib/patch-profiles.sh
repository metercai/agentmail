# Step 8: Patch Hermes — profile hooks
# ═══════════════════════════════════════════════════════════════
step_begin "$T_PROFILES"

PROFILES_PY="$HERMES_DIR/hermes_cli/profiles.py"

if [ ! -f "$PROFILES_PY" ]; then
    # Try alternate path
    PROFILES_PY="$HERMES_DIR/cli/profiles.py"
fi
if [ ! -f "$PROFILES_PY" ]; then
    step_warn "$T_PROFILES_MISS"
    info "  $T_WEBHOOK_HINT"
else
    if grep -q "trigger_profile_hooks" "$PROFILES_PY" 2>/dev/null; then
        step_ok "$T_PROFILES_OK"
    else
        echo -n "  $T_PROFILES_APPLY "
        PATCH_OUT=$(python3 "$SCRIPT_DIR/patches/apply_profiles_patch.py" "$PROFILES_PY" 2>&1) && echo "$T_OK" || { echo "$T_FAILED"; echo "$PATCH_OUT" | head -5 | sed 's/^/  | /'; }
        if grep -q "trigger_profile_hooks" "$PROFILES_PY" 2>/dev/null; then
            step_ok "$T_PROFILES_DONE"
        else
            step_warn "$T_PROFILES_FAIL"
        fi
    fi

    # Register existing profiles that don't have amail.json yet
    step_ok "$T_PROFILES_REG_DISP"
    REG_OUTPUT=$(python3 "$SCRIPT_DIR/lib/register_profiles.py" 2>/dev/null)
    REG_COUNT=0
    while IFS= read -r line; do
        case "$line" in
            registered:*) REG_COUNT="${line#registered:}" ;;
            failed:*)     info "  ⚠ ${line#failed:}" ;;
            no_config)    info "  No gateway config — skip" ;;
        esac
    done <<< "$REG_OUTPUT"
    if [ "${REG_COUNT:-0}" -gt 0 ]; then
        _msg="${T_PROFILES_REG_DONE/{count}/$REG_COUNT}"
        step_ok "$_msg"
    else
        step_ok "$T_PROFILES_REG_SKIP_MSG"
    fi
fi

# ═══════════════════════════════════════════════════════════════
