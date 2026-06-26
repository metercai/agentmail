#!/usr/bin/env bash
# configure_hermes.sh — Step 6: Configure Hermes for amail integration
# Called by integrate.sh (PATCH_STEP_PARENT=1 suppresses inner step_begins)
#
# Sub-steps:
#   1. Patch webhook.py — PREPROCESS_REGISTRY + ping-pong intercept
#   2. Patch profiles.py — trigger_profile_hooks
#   3. Register existing profiles as amail addresses
#   4. Ensure Hermes gateway is running with webhook support

SCRIPT_DIR="$(cd "$(dirname "$(dirname "$0")")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"

# ── 0. Stop any running gateways BEFORE patching ─────────────────
echo "  Stopping any running Hermes gateways..."
pkill -f "hermes.*gateway.*run.*accept-hooks" 2>/dev/null || true
sleep 2

# ── 1. Patch webhook ────────────────────────────────────────────
source "$LIB_DIR/patch-webhook.sh"

# ── 2. Patch profiles ───────────────────────────────────────────
source "$LIB_DIR/patch-profiles.sh"

# ── 3. Register existing profiles ───────────────────────────────
REG_OUTPUT=$(python3 "$SCRIPT_DIR/lib/register_profiles.py")
REG_COUNT=0
while IFS= read -r line; do
    case "$line" in
        registered:*) REG_COUNT="${line#registered:}" ;;
        failed:*)     echo "  ⚠ ${line#failed:}" ;;
        no_config)    echo "  No gateway config — skip" ;;
    esac
done <<< "$REG_OUTPUT"
if [ "${REG_COUNT:-0}" -gt 0 ]; then
    info "Registered amail addresses for ${REG_COUNT} profile(s)"
else
    info "All profiles already registered"
fi

# ── 4. Ensure gateway running ──────────────────────────────────
source "$LIB_DIR/hermes_gateway.sh"
