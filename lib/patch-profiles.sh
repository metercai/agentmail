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
    echo -n "  Registering amail addresses for existing profiles... "
    REG_OUTPUT=$(python3 << PYEOF
import sys, os
sys.path.insert(0, "$SCRIPT_DIR/tools")
from amail_tools import _auto_register_email, _load_gateway_config
config = _load_gateway_config()
if not config or not config.get("admin_key"):
    print("no_config")
else:
    base_dir = os.path.expanduser(os.environ.get("HERMES_PROFILES_DIR",
        "~/.hermes/profiles"))
    home_dir = os.path.expanduser(os.environ.get("HERMES_HOME",
        "~/.hermes"))
    count = 0

    # Default profile: check hermes home root (not under profiles/)
    default_configs = [
        (os.path.join(home_dir, "amail.json"), "default", home_dir),
        (os.path.join(home_dir, "hermes-agent", "amail.json"), "default", os.path.join(home_dir, "hermes-agent")),
    ]
    for amail_json, name, profile_dir in default_configs:
        if os.path.exists(amail_json):
            break
    else:
        # No default amail.json — register it
        try:
            _auto_register_email("default", home_dir, config)
            count += 1
        except Exception as e:
            print(f"failed:default:{e}")

    # Named profiles: scan profiles/ directory
    if os.path.isdir(base_dir):
        for name in sorted(os.listdir(base_dir)):
            profile_dir = os.path.join(base_dir, name)
            if not os.path.isdir(profile_dir):
                continue
            amail_json = os.path.join(profile_dir, "amail.json")
            if os.path.exists(amail_json):
                continue
            try:
                _auto_register_email(name, profile_dir, config)
                count += 1
            except Exception as e:
                print(f"failed:{name}:{e}")
    print(f"registered:{count}")
PYEOF
)
    REG_COUNT=0
    while IFS= read -r line; do
        case "$line" in
            registered:*) REG_COUNT="${line#registered:}" ;;
            failed:*)     info "  ⚠ ${line#failed:}" ;;
            no_config)    info "  No gateway config — skip" ;;
        esac
    done <<< "$REG_OUTPUT"
    if [ "${REG_COUNT:-0}" -gt 0 ]; then
        step_ok "$T_PROFILES_REG_DONE" | sed "s/{count}/$REG_COUNT/"
    else
        step_ok "All profiles already registered, skipping"
    fi
fi

# ═══════════════════════════════════════════════════════════════
