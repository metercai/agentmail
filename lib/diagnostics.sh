# Step 9: Diagnostics
# ═══════════════════════════════════════════════════════════════
step_begin "$T_DIAG"

DIAG=$(
export INTEGRATE_GATEWAY_URL="$GATEWAY_URL"
export INTEGRATE_ADMIN_KEY="$ADMIN_KEY"
python3 << 'PYEOF'
import sys, json, os
sys.path.insert(0, os.environ["SCRIPT_DIR"] + "/tools")
from amail_tools import verify_integration
result = verify_integration(
    gateway_url=os.environ.get("INTEGRATE_GATEWAY_URL", ""),
    admin_key=os.environ.get("INTEGRATE_ADMIN_KEY", "")
)
print(json.dumps(result, indent=2, ensure_ascii=False))
PYEOF
)

if [ $? -eq 0 ] && [ -n "$DIAG" ]; then
    ALL_PASS=$(echo "$DIAG" | python3 -c "import sys,json; print(json.load(sys.stdin).get('all_pass',False))" 2>/dev/null || echo "False")
    echo "$DIAG" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data.get('checks', []):
    icon = '✓' if c['pass'] else '✗'
    color = '[0;32m' if c['pass'] else '[0;31m'
    print(f'  {color}{icon}[0m {c[\"check\"]}: {c[\"detail\"]}')
    if not c['pass'] and c.get('fix'):
        print(f'     → {c[\"fix\"]}')
" 2>/dev/null

    if [ "$ALL_PASS" = "True" ]; then
        step_ok "$T_DIAG_ALL"
    else
        step_warn "$T_DIAG_PARTIAL"
    fi
else
    step_warn "$T_DIAG_ERR"
fi

# ═══════════════════════════════════════════════════════════════
