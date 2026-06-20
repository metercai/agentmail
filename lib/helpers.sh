# ── Idempotent config helpers ──────────────────────────────────
# Read existing value from ~/.hermes/amail_gateway.json
read_config() {
    local key="$1"
    python3 -c "import sys,json,os; d={}; p=os.path.expanduser('~/.hermes/amail_gateway.json');
    d=json.load(open(p)) if os.path.exists(p) else {}; print(d.get('$key',''))" 2>/dev/null || echo ""
}

# Prompt user with existing value as default
ask_param() {
    local label="$1" env_var="$2" json_key="$3" default="$4"
    local value=""
    # Priority: env var > existing config > default
    if [ -n "${!env_var:-}" ]; then
        value="${!env_var}"
    else
        value=$(read_config "$json_key")
    fi
    if [ -z "$value" ]; then
        value="$default"
    fi


    read -r -p "  $label [$value]: " user_input
    echo "${user_input:-$value}"
}

# ── Helpers ────────────────────────────────────────────────────
step=0
step_begin() {
    step=$((step + 1))
    echo ""
    echo -e "${BOLD}${BLUE}[${step}/10]${NC} $1"
}
step_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
step_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
step_fail() { echo -e "  ${RED}✗${NC} $1"; echo ""; exit 1; }
info()      { echo -e "     $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export SCRIPT_DIR

# Check if a domain is already registered in ANY system (global uniqueness)
domain_exists_globally() {
    local check_domain="$1"
    local gateway_url="${2:-$GATEWAY_URL}"
    local admin_key="${3:-$ADMIN_KEY}"
    curl -s "$gateway_url/api/v1/admin/domains/check?domain=$check_domain" \
        -H "X-Api-Key: $admin_key" 2>/dev/null \
        | python3 -c "import sys,json; sys.exit(0) if json.load(sys.stdin).get('exists') else sys.exit(1)" 2>/dev/null
}
