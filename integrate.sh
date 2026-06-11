#!/usr/bin/env bash
# integrate.sh — amail Hermes one-click integration script
# =============================================================================
# Usage: bash integrate.sh [--auto]
#
#   --auto    non-interactive mode (from env vars, suitable for CI/scripts)
#             env vars: AMAIL_URL, AMAIL_ADMIN_KEY,
#                       AMAIL_PRODUCT_CODE, AMAIL_DOMAIN, AMAIL_SAVE_SNAPSHOTS,
#                       AMAIL_MANAGER_ADDRESS
#
# When using a product activation code (AMAIL_PRODUCT_CODE), AMAIL_ADMIN_KEY
# is not required. Step 3 (domain) is skipped automatically.
#
# Up to 10 steps (product_code path auto-skips Step 3):
#   [1]  gateway connect   [2]  auth method     [3]  domain (skipped for product_code)
#   [4]  basic config    [5]  save config / activate
#   [6]  install tools   [7]  patch webhook   [8]  patch profiles
#   [9]  diagnostics     [10] send/receive test
# =============================================================================

set -eo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
BOLD='\033[1m'

AUTO_MODE=false
for arg in "$@"; do
    case "$arg" in --auto) AUTO_MODE=true ;; *) ;; esac
done

# ── Language selection ──────────────────────────────────────────
LANG_CHOICE="${AMAIL_LANG:-}"
if ! $AUTO_MODE && [ -z "$LANG_CHOICE" ]; then
    echo ""
    echo -e "${BOLD}Select language / 选择语言:${NC}"
    echo "  [1] English (default)"
    echo "  [2] 中文"
    echo -n "  Choice [1/2]: "
    read -r LANG_ANS
    LANG_ANS="${LANG_ANS:-1}"
    [ "$LANG_ANS" = "2" ] && LANG_CHOICE="zh" || LANG_CHOICE="en"
elif $AUTO_MODE; then
    LANG_CHOICE="${LANG_CHOICE:-en}"
fi

# ── Strings by language ─────────────────────────────────────────
if [ "$LANG_CHOICE" = "zh" ]; then
    T_TITLE="amail Hermes 集成向导"
    T_GATEWAY="配置 gateway 连接"
    T_DETECT="检测到 gateway 运行在"
    T_CHECKING="检测 gateway 连通性..."
    T_FAILED="失败"
    T_GATEWAY_OK="gateway 连接正常 (已运行"
    T_AUTH="配置认证方式 (admin_key / 产品激活码)"
    T_AUTH_READ="从 AMAIL_ADMIN_KEY 读取"
    T_AUTH_READ_PC="从 AMAIL_PRODUCT_CODE 读取 (system_id/domain 由服务器生成)"
    T_AUTH_NEED_ONE="AMAIL_ADMIN_KEY 或 AMAIL_PRODUCT_CODE 至少需设置一个"
    T_SELECT_AUTH="选择认证方式:"
    T_AUTH_OPT1="输入已有的 admin_key"
    T_AUTH_OPT2="使用激活码激活 product code"
    T_CHOOSE="请选择"
    T_PC_HELP="产品激活码由平台管理员预先生成并提供。兑换后自动创建系统并返回 admin_key。"
    T_PC_PROMPT="product_code: "
    T_PC_EMPTY="product_code 不能为空"
    T_PC_USING="使用产品激活码"
    T_PC_AUTO="system_id/domain 由服务器自动生成"
    T_DETECT_KEY="检测到 admin_key"
    T_USE_KEY="使用此 key?"
    T_KEY_HINT="base 版 gateway 启动后，admin_key 保存在 {db}.admin_key 文件中"
    T_KEY_PROMPT="admin_key: "
    T_VERIFY="验证权限..."
    T_SCOPE_FAIL="admin_key 权限不足 — 需要 platform 或 system scope"
    T_DOMAIN="配置 agent email domain"
    T_DOMAIN_ENV="从 AMAIL_DOMAIN 读取"
    T_DOMAIN_EMPTY="<空>"
    T_DOMAIN_QUERY="查询系统已有域..."
    T_DOMAIN_EXISTING="已有域名"
    T_DOMAIN_SELECT="选择域编号 (或输入新域名): "
    T_DOMAIN_NONE="该系统暂无配置域，请新建一个"
    T_DOMAIN_HINT="domain (如 'admin.local'): "
    T_DOMAIN_UNSET="未指定 domain (后续可通过 profile 设置)"
    T_SNAP="配置邮件快照保存"
    T_SNAP_ENV="从 AMAIL_SAVE_SNAPSHOTS 读取"
    T_SNAP_PROMPT="保存邮件原始快照到本地? (y/N): "
    T_SNAP_ON="save_raw_snapshots = true (入站/出站邮件将持久化到本地)"
    T_SNAP_OFF="save_raw_snapshots = false (不在本地保存邮件快照)"
    T_SNAP_CONFIG="基本配置"
    T_MANAGER_PROMPT="默认管理员邮箱: "
    T_SAVE="保存配置到 ~/.hermes/amail_gateway.json"
    T_CONFIG_FAIL="配置写入失败"
    T_ACTIVATED="系统激活成功！"
    T_ACT_FAIL="激活失败 — 未能提取 admin_key（可稍后手动查询）"
    T_CONFIG_OK="配置已保存到"
    T_CONFIG_WARN="配置文件可能未正确更新，请手动检查"
    T_TOOLS="安装 amail 工具到 Hermes"
    T_TOOLS_COPY="已复制 amail_tools.py 到 Hermes 工具目录"
    T_TOOLS_REG="已在 toolsets.py 注册工具"
    T_TOOLS_SKIP="工具已安装 (跳过)"
    T_TOOLS_FAIL="工具安装失败 — 请按 INSTALL-TOOLS.md 手动操作"
    T_WEBHOOK="Patch Hermes — webhook 预处理器"
    T_WEBHOOK_MISS="找不到 webhook.py — 跳过 webhook 预处理 patch"
    T_WEBHOOK_HINT="设置 HERMES_DIR 环境变量指定 Hermes 安装路径"
    T_WEBHOOK_OK="webhook.py 已含预处理器支持 (跳过)"
    T_WEBHOOK_APPLY="应用 patch..."
    T_WEBHOOK_DONE="webhook.py patch 完成"
    T_WEBHOOK_FAIL="webhook.py patch 失败 — 入站预处理可能不生效"
    T_PROFILES="Patch Hermes — profile hooks"
    T_PROFILES_MISS="找不到 profiles.py — 跳过 profile hook patch"
    T_PROFILES_OK="profiles.py 已含 amail hooks (跳过)"
    T_PROFILES_APPLY="应用 patch..."
    T_PROFILES_DONE="profiles.py patch 完成"
    T_PROFILES_FAIL="profiles.py patch 失败 — profile 生命周期 hook 不生效"
    T_PROFILES_REGISTER="为已有 profile 注册 amail 地址"
    T_PROFILES_REG_DONE="已注册 {count} 个已有 profile"
    T_PROFILES_REG_SKIP="所有已有 profile 均已注册"
    T_DIAG="综合诊断 (verify_integration)"
    T_DIAG_ALL="所有诊断通过"
    T_DIAG_PARTIAL="部分检查未通过 (见上)，集成仍可继续使用"
    T_DIAG_ERR="诊断执行失败 (非致命)"
    T_TEST="在线收发测试"
    T_TEST_CREATE="创建测试 agent key..."
    T_TEST_FAIL_KEY="无法创建测试 key — 跳过在线测试"
    T_TEST_REG="注册测试域..."
    T_TEST_SEND="发送测试邮件..."
    T_TEST_OK="在线收发测试通过 — gateway 发信正常"
    T_TEST_FAIL_SEND="发信测试失败 — 请检查 gateway 配置和白名单"
    T_TEST_CLEAN="清理测试数据..."
    T_DONE="集成完成！"
    T_SUMMARY="配置摘要"
    T_AUTH_LABEL="认证方式"
    T_AUTH_LABEL_PC="产品激活码"
    T_UNSET="<未设置>"
    T_PATCH="Hermes Patch"
    T_PATCHED="已 patch"
    T_NOT_PATCHED="未 patch"
    T_NEXT="后续步骤"
    T_NEXT_1="创建 Hermes profile → agent 地址自动注册、激活码自动生成"
    T_NEXT_2="启动 agent → 自动激活 (agent_startup_activate)"
    T_NEXT_3="参考文档"
    T_ERR_NO_TOOLS="找不到 amail_tools.py"
    T_ADMIN_KEY_OK="admin_key 有效"
    T_OK="OK"
else
    T_TITLE="amail Hermes Integration Wizard"
    T_GATEWAY="Configure gateway connection"
    T_DETECT="gateway detected at"
    T_CHECKING="Checking gateway connectivity..."
    T_FAILED="FAILED"
    T_GATEWAY_OK="gateway connected (uptime"
    T_AUTH="Configure authentication (admin_key / product code)"
    T_AUTH_READ="Read from AMAIL_ADMIN_KEY"
    T_AUTH_READ_PC="Read from AMAIL_PRODUCT_CODE (system_id/domain generated by server)"
    T_AUTH_NEED_ONE="At least one of AMAIL_ADMIN_KEY or AMAIL_PRODUCT_CODE must be set"
    T_SELECT_AUTH="Select auth method:"
    T_AUTH_OPT1="Enter existing admin_key"
    T_AUTH_OPT2="Activate with product code"
    T_CHOOSE="Choice"
    T_PC_HELP="Product codes are pre-generated by the platform admin. Activation creates a new system and returns an admin_key."
    T_PC_PROMPT="product_code: "
    T_PC_EMPTY="product_code cannot be empty"
    T_PC_USING="Using product code"
    T_PC_AUTO="system_id/domain auto-generated by server"
    T_DETECT_KEY="admin_key found"
    T_USE_KEY="Use this key?"
    T_KEY_HINT="After starting base edition gateway, the admin_key is saved in {db}.admin_key"
    T_KEY_PROMPT="admin_key: "
    T_VERIFY="Verifying permissions..."
    T_SCOPE_FAIL="admin_key permission denied — requires platform or system scope"
    T_DOMAIN="Configure agent email domain"
    T_DOMAIN_ENV="Read from AMAIL_DOMAIN"
    T_DOMAIN_EMPTY="<empty>"
    T_DOMAIN_QUERY="Querying existing domains..."
    T_DOMAIN_EXISTING="Existing domains"
    T_DOMAIN_SELECT="Select domain number (or enter new domain): "
    T_DOMAIN_NONE="No domains configured for this system, create a new one"
    T_DOMAIN_HINT="domain (e.g. 'admin.local'): "
    T_DOMAIN_UNSET="Domain not set (can be configured later via profile)"
    T_SNAP="Configure email snapshot saving"
    T_SNAP_ENV="Read from AMAIL_SAVE_SNAPSHOTS"
    T_SNAP_PROMPT="Save raw email snapshots locally? (y/N): "
    T_SNAP_ON="save_raw_snapshots = true (inbound/outbound mail will be persisted locally)"
    T_SNAP_OFF="save_raw_snapshots = false (no local snapshot storage)"
    T_SNAP_CONFIG="Basic configuration"
    T_MANAGER_PROMPT="Default manager email address: "
    T_SAVE="Save config to ~/.hermes/amail_gateway.json"
    T_CONFIG_FAIL="Config write failed"
    T_ACTIVATED="System activated!"
    T_ACT_FAIL="Activation failed — could not extract admin_key (retry manually later)"
    T_CONFIG_OK="Config saved to"
    T_CONFIG_WARN="Config file may not be updated correctly, please check manually"
    T_TOOLS="Install amail tools into Hermes"
    T_TOOLS_COPY="Copied amail_tools.py to Hermes tools directory"
    T_TOOLS_REG="Registered tools in toolsets.py"
    T_TOOLS_SKIP="Tools already installed (skip)"
    T_TOOLS_FAIL="Tool installation failed — follow INSTALL-TOOLS.md manually"
    T_WEBHOOK="Patch Hermes — webhook preprocessor"
    T_WEBHOOK_MISS="webhook.py not found — skipping webhook preprocessor patch"
    T_WEBHOOK_HINT="Set HERMES_DIR env var to specify Hermes install path"
    T_WEBHOOK_OK="webhook.py already has preprocessor support (skipping)"
    T_WEBHOOK_APPLY="Applying patch..."
    T_WEBHOOK_DONE="webhook.py patch complete"
    T_WEBHOOK_FAIL="webhook.py patch failed — inbound preprocessor may not work"
    T_PROFILES="Patch Hermes — profile hooks"
    T_PROFILES_MISS="profiles.py not found — skipping profile hook patch"
    T_PROFILES_OK="profiles.py already has amail hooks (skipping)"
    T_PROFILES_APPLY="Applying patch..."
    T_PROFILES_DONE="profiles.py patch complete"
    T_PROFILES_FAIL="profile hooks patch failed — profile lifecycle hooks may not work"
    T_PROFILES_REGISTER="Register existing profiles with amail"
    T_PROFILES_REG_DONE="Registered {count} existing profile(s)"
    T_PROFILES_REG_SKIP="All existing profiles already registered"
    T_DIAG="Diagnostics (verify_integration)"
    T_DIAG_ALL="All diagnostics passed"
    T_DIAG_PARTIAL="Some checks did not pass (see above), integration still usable"
    T_DIAG_ERR="Diagnostics execution failed (non-fatal)"
    T_TEST="Send/receive test"
    T_TEST_CREATE="Creating test agent key..."
    T_TEST_FAIL_KEY="Cannot create test key — skipping online test"
    T_TEST_REG="Registering test domain..."
    T_TEST_SEND="Sending test email..."
    T_TEST_OK="Send/receive test passed — gateway sending works"
    T_TEST_FAIL_SEND="Send test failed — check gateway config and whitelist"
    T_TEST_CLEAN="Cleaning up test data..."
    T_DONE="Integration complete!"
    T_SUMMARY="Configuration summary"
    T_AUTH_LABEL="Auth method"
    T_AUTH_LABEL_PC="Product code"
    T_UNSET="<not set>"
    T_PATCH="Hermes Patch"
    T_PATCHED="patched"
    T_NOT_PATCHED="not patched"
    T_NEXT="Next steps"
    T_NEXT_1="Create Hermes profile → agent address auto-registered, activation code auto-generated"
    T_NEXT_2="Start agent → auto-activates (agent_startup_activate)"
    T_NEXT_3="Reference docs"
    T_ERR_NO_TOOLS="Cannot find amail_tools.py"
    T_ADMIN_KEY_OK="admin_key valid"
    T_OK="OK"
fi

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
    
    if $AUTO_MODE; then
        echo "$value"
        return
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
TOOLS_PY="$SCRIPT_DIR/tools/amail_tools.py"
HERMES_DIR="${HERMES_DIR:-$HOME/.hermes/hermes-agent}"

if [ ! -f "$TOOLS_PY" ]; then
    echo -e "${RED}[ERROR] $T_ERR_NO_TOOLS: $TOOLS_PY${NC}"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         ${T_TITLE}                       ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"

# ═══════════════════════════════════════════════════════════════
# Step 1: gateway_url
# ═══════════════════════════════════════════════════════════════
step_begin "$T_GATEWAY"

if $AUTO_MODE; then
    GATEWAY_URL="${AMAIL_URL:-}"
    [ -z "$GATEWAY_URL" ] && step_fail "AMAIL_URL not set (required for --auto mode)"
    info "Read from AMAIL_URL: $GATEWAY_URL"
else
    DEFAULT_URL="http://127.0.0.1:38080"
    if curl -s -o /dev/null -w '%{http_code}' "$DEFAULT_URL/health" 2>/dev/null | grep -q 200; then
        info "$T_DETECT $DEFAULT_URL"
    fi
    GATEWAY_URL=$(ask_param "gateway_url" "AMAIL_URL" "gateway_url" "$DEFAULT_URL")
fi

echo -n "  $T_CHECKING "
HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "$GATEWAY_URL/health" 2>/dev/null || echo "000")
[ "$HEALTH" != "200" ] && { echo -e "${RED}$T_FAILED (HTTP $HEALTH)${NC}"; step_fail "Cannot reach $GATEWAY_URL/health"; }
UPTIME=$(curl -s "$GATEWAY_URL/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('uptime_secs','?'))" 2>/dev/null || echo "?")
echo -e "${GREEN}$T_OK${NC}"
step_ok "$T_GATEWAY_OK ${UPTIME}s)"

# ═══════════════════════════════════════════════════════════════
# Step 2: auth method — admin_key or product activation code
# ═══════════════════════════════════════════════════════════════
step_begin "$T_AUTH"

PRODUCT_CODE=""
USE_PRODUCT_CODE=false

if $AUTO_MODE; then
    ADMIN_KEY="${AMAIL_ADMIN_KEY:-}"
    PRODUCT_CODE="${AMAIL_PRODUCT_CODE:-}"
    if [ -n "$ADMIN_KEY" ]; then
        info "$T_AUTH_READ"
    elif [ -n "$PRODUCT_CODE" ]; then
        USE_PRODUCT_CODE=true
        info "$T_AUTH_READ_PC"
    else
        step_fail "$T_AUTH_NEED_ONE"
    fi
else
    echo ""
    info "$T_SELECT_AUTH"
    info "  [1] $T_AUTH_OPT1"
    info "  [2] $T_AUTH_OPT2"
    echo -n "  $T_CHOOSE [1/2] (default 1): "; read -r AUTH_MODE
    AUTH_MODE="${AUTH_MODE:-1}"

    if [ "$AUTH_MODE" = "2" ]; then
        USE_PRODUCT_CODE=true
        echo "  $T_PC_HELP"
        read -r -p "  $T_PC_PROMPT" PRODUCT_CODE
        [ -z "$PRODUCT_CODE" ] && step_fail "$T_PC_EMPTY"
        info "$T_PC_USING: ${PRODUCT_CODE:0:8}..."
        info "  $T_PC_AUTO"
    else
        # admin_key path — auto-detect file + manual input
        AUTO_KEY=""; AUTO_PATH=""
        for dir in "." "/tmp/amail-gateway"; do
            [ -d "$dir" ] || continue
            found=$(find "$dir" -maxdepth 1 -name "*.admin_key" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2)
            [ -n "$found" ] && [ -f "$found" ] && AUTO_KEY=$(head -1 "$found") && AUTO_PATH="$found" && break
        done
        if [ -n "$AUTO_KEY" ]; then
            info "$T_DETECT_KEY: $AUTO_PATH (${AUTO_KEY:0:8}...)"
            echo -n "  $T_USE_KEY [Y/n]: "; read -r USE_AUTO
            if [ "${USE_AUTO:-Y}" = "Y" ] || [ "${USE_AUTO:-y}" = "y" ]; then
                ADMIN_KEY="$AUTO_KEY"
            fi
        fi
        if [ -z "$ADMIN_KEY" ]; then
            echo "  $T_KEY_HINT"
            ADMIN_KEY=$(ask_param "$T_KEY_PROMPT" "AMAIL_ADMIN_KEY" "admin_key" "")
        fi
    fi
fi

if $USE_PRODUCT_CODE; then
    step_ok "$T_PC_USING (prefix: ${PRODUCT_CODE:0:8}...)"
else
    [ -z "$ADMIN_KEY" ] && step_fail "admin_key cannot be empty"

    echo -n "  $T_VERIFY "
    WHOAMI=$(curl -s "$GATEWAY_URL/api/v1/whoami" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo '{}')
    SCOPE=$(echo "$WHOAMI" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('scope','') or ','.join(d.get('scopes',[])))" 2>/dev/null || echo "")
    CATEGORY=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category','?'))" 2>/dev/null || echo "?")
    SYSTEM_ID=$(echo "$WHOAMI" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null || echo "")
    [ -z "$SYSTEM_ID" ] && step_fail "Failed to determine system_id from whoami"
    if echo "$SCOPE" | grep -qE "platform|system"; then
        echo -e "${GREEN}$T_OK${NC}"
        step_ok "$T_ADMIN_KEY_OK (prefix: ${ADMIN_KEY:0:8}..., scope: $SCOPE, category: $CATEGORY, system_id: $SYSTEM_ID)"
    else
        echo -e "${RED}$T_FAILED${NC}"
        step_fail "$T_SCOPE_FAIL"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# Step 3: domain (admin_key only; product_code skips)
# ═══════════════════════════════════════════════════════════════
if ! $USE_PRODUCT_CODE; then
    step_begin "$T_DOMAIN"

    if $AUTO_MODE; then
        AMAIL_DOMAIN="${AMAIL_DOMAIN:-}"
        info "$T_DOMAIN_ENV: ${AMAIL_DOMAIN:-$T_DOMAIN_EMPTY}"
    else
        info "$T_DOMAIN_QUERY"

        DOMAINS_JSON=$(curl -s "$GATEWAY_URL/api/v1/admin/systems/$SYSTEM_ID/domains" -H "X-Api-Key: $ADMIN_KEY" 2>/dev/null || echo "[]")
        DOMAIN_COUNT=$(echo "$DOMAINS_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

        if [ "$DOMAIN_COUNT" -gt 0 ]; then
            echo -e "  ${BOLD}$T_DOMAIN_EXISTING:${NC}"
            echo "$DOMAINS_JSON" | python3 -c "
import sys,json
entries = [d for d in json.load(sys.stdin) if '@' not in d.get('domain','')]
for i,d in enumerate(entries,1):
    print(f'    [{i}] {d.get(\"domain\",\"?\")}  {\"(inactive)\" if not d.get(\"is_active\") else \"\"}')
" 2>/dev/null
            echo -n "  $T_DOMAIN_SELECT"; read -r DOMAIN_CHOICE
            if [[ "$DOMAIN_CHOICE" =~ ^[0-9]+$ ]]; then
                AMAIL_DOMAIN=$(echo "$DOMAINS_JSON" | python3 -c "
import sys,json
entries = [d for d in json.load(sys.stdin) if '@' not in d.get('domain','')]
print(entries[$DOMAIN_CHOICE-1]['domain'])
" 2>/dev/null || echo "")
            else
                AMAIL_DOMAIN="$DOMAIN_CHOICE"
            fi
        else
            echo "  $T_DOMAIN_NONE"
            read -r -p "  $T_DOMAIN_HINT" AMAIL_DOMAIN
        fi
    fi
    if [ -n "$AMAIL_DOMAIN" ]; then
        step_ok "domain = $AMAIL_DOMAIN"
    else
        step_ok "$T_DOMAIN_UNSET"
    fi
else
    # product_code: skip Step 3 entirely, advance step counter
    step=$((step + 1))
    SYSTEM_ID=""
    AMAIL_DOMAIN=""
fi

# ═══════════════════════════════════════════════════════════════
# Step 4: basic configuration (snapshot + manager_address)
# ═══════════════════════════════════════════════════════════════
step_begin "$T_SNAP_CONFIG"

if $AUTO_MODE; then
    SAVE_SNAPSHOTS="${AMAIL_SAVE_SNAPSHOTS:-false}"
    SAVE_SNAPSHOTS=$(echo "$SAVE_SNAPSHOTS" | tr '[:upper:]' '[:lower:]')
    info "$T_SNAP_ENV: $SAVE_SNAPSHOTS"
    MANAGER_ADDRESS="${AMAIL_MANAGER_ADDRESS:-}"
    info "manager_address: ${MANAGER_ADDRESS:-<empty>}"
    WEBHOOK_HOST="${AMAIL_WEBHOOK_HOST:-}"
    info "webhook_host: ${WEBHOOK_HOST:-<empty>}"
else
    SAVE_SNAPSHOTS=$(ask_param "$T_SNAP_PROMPT (true/false)" "AMAIL_SAVE_SNAPSHOTS" "save_raw_snapshots" "false")
    MANAGER_ADDRESS=$(ask_param "$T_MANAGER_PROMPT" "AMAIL_MANAGER_ADDRESS" "manager_address" "")
    if [ -z "$AMAIL_WEBHOOK_HOST" ]; then
        info "Webhook host (gateway callback address, leave empty for auto-detect)"
    fi
    WEBHOOK_HOST=$(ask_param "  webhook_host [host:port]:" "AMAIL_WEBHOOK_HOST" "webhook_host" "")
fi
if [ "$SAVE_SNAPSHOTS" = "true" ]; then
    step_ok "snapshots = true (inbound/outbound mail will be persisted locally)"
else
    step_ok "snapshots = false (no local snapshot storage)"
fi

# ═══════════════════════════════════════════════════════════════
# Step 5: write config (product_code path also activates)
# ═══════════════════════════════════════════════════════════════
step_begin "$T_SAVE"

SETUP_RESULT=$(python3 << PYEOF
import sys, json, os
sys.path.insert(0, "$SCRIPT_DIR/tools")
from amail_tools import setup
kwargs = dict(
    gateway_url="$GATEWAY_URL",
    system_id="$SYSTEM_ID",
    domain=os.environ.get("AMAIL_DOMAIN", "$AMAIL_DOMAIN") or "",
    save_raw_snapshots=os.environ.get("AMAIL_SAVE_SNAPSHOTS", "$SAVE_SNAPSHOTS") == "true",
    manager_address=os.environ.get("AMAIL_MANAGER_ADDRESS", "$MANAGER_ADDRESS") or "",
    webhook_host=os.environ.get("AMAIL_WEBHOOK_HOST", "$WEBHOOK_HOST") or "",
)
if $USE_PRODUCT_CODE; then
    kwargs["product_code"] = "$PRODUCT_CODE"
else
    kwargs["admin_key"] = "$ADMIN_KEY"
fi
result = setup(**kwargs)
print(json.dumps(result, indent=2, ensure_ascii=False))
if not result.get("success"): sys.exit(1)
PYEOF
)
EXIT_CODE=$?
echo "$SETUP_RESULT"
[ $EXIT_CODE -ne 0 ] && step_fail "$T_CONFIG_FAIL"

# If using product_code, extract exchanged admin_key + system_id + domain from setup()
if $USE_PRODUCT_CODE; then
    NEW_ADMIN_KEY=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('admin_key','') or d.get('raw_key',''))" 2>/dev/null || echo "")
    NEW_SYSTEM_ID=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('system_id',''))" 2>/dev/null || echo "")
    NEW_DOMAIN=$(echo "$SETUP_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('domain',''))" 2>/dev/null || echo "")

    if [ -n "$NEW_ADMIN_KEY" ]; then
        ADMIN_KEY="$NEW_ADMIN_KEY"
        SYSTEM_ID="$NEW_SYSTEM_ID"
        AMAIL_DOMAIN="$NEW_DOMAIN"
        echo ""
        echo -e "  ${BOLD}$T_ACTIVATED${NC}"
        echo "  ├─ system_id:  ${SYSTEM_ID:-?}"
        echo "  ├─ domain:     ${AMAIL_DOMAIN:-?}"
        echo "  └─ admin_key:  ${ADMIN_KEY:0:8}..."
    else
        step_warn "$T_ACT_FAIL"
    fi
fi

CONFIG_FILE="$HOME/.hermes/amail_gateway.json"
if [ -f "$CONFIG_FILE" ]; then
    step_ok "$T_CONFIG_OK $CONFIG_FILE"
else
    step_warn "$T_CONFIG_WARN $CONFIG_FILE"
fi

# ═══════════════════════════════════════════════════════════════
# Step 5.5: Bridge deployment (remote gateway only)
# ═══════════════════════════════════════════════════════════════
BRIDGE_NEEDED=false
if ! echo "$GATEWAY_URL" | grep -qE "127\.0\.0\.1|0\.0\.0\.0|localhost|::1"; then
    echo ""
    echo -e "${BOLD}${BLUE}[5.5]${NC} Auto-deploy amail-bridge"
    
    BRIDGE_DIR="$HOME/.hermes/bin"
    BRIDGE_LINK="$BRIDGE_DIR/amail-bridge"
    mkdir -p "$BRIDGE_DIR"

    # TODO: multi-platform binaries — currently only linux-amd64 available
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
    RELEASE_API="https://api.github.com/repos/metercai/amail-bridge/releases/latest"

    LATEST_TAG=$(curl -fsS "$RELEASE_API" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || echo "")

    BRIDGE_URL="https://github.com/metercai/amail-bridge/releases/download/${LATEST_TAG}/amail-bridge-${OS}-${ARCH}-${LATEST_TAG}"

    if [ -n "$LATEST_TAG" ]; then
        BRIDGE_VERSIONED="$BRIDGE_DIR/amail-bridge-${OS}-${ARCH}-${LATEST_TAG}"

        if [ -x "$BRIDGE_VERSIONED" ]; then
            echo "  Bridge ${LATEST_TAG} up to date — skip download"
        else
            echo -n "  Downloading bridge (${LATEST_TAG})... "
            if curl -fsSL "$BRIDGE_URL" -o "$BRIDGE_VERSIONED" 2>/dev/null; then
                chmod +x "$BRIDGE_VERSIONED"
                echo "$T_OK"
            else
                echo "$T_FAILED"
                step_warn "Bridge download failed — will use webhook push mode"
            fi
        fi
        # Symlink to current version (atomically replaces old target)
        [ -x "$BRIDGE_VERSIONED" ] && ln -sf "$(basename "$BRIDGE_VERSIONED")" "$BRIDGE_LINK"
    else
        # API unavailable — use latest redirect, version unknown
        FALLBACK_URL="https://github.com/metercai/amail-bridge/releases/latest/download/amail-bridge-${OS}-${ARCH}"
        echo -n "  Downloading bridge (version unknown)... "
        if curl -fsSL "$FALLBACK_URL" -o "$BRIDGE_LINK" 2>/dev/null; then
            chmod +x "$BRIDGE_LINK"
            echo "$T_OK"
        else
            echo "$T_FAILED"
            step_warn "Bridge download failed — will use webhook push mode"
        fi
    fi
    
    if [ -x "$BRIDGE_LINK" ]; then
        # ── Resolve bridge addr from webhook_host ──
        BRIDGE_ADDR="${WEBHOOK_HOST:-$(read_config webhook_host)}"
        BRIDGE_ADDR="${BRIDGE_ADDR:-127.0.0.1:80}"
        # Ensure port: append 80 if bare IP (best firewall pass-through)
        if ! echo "${BRIDGE_ADDR}" | grep -q ":"; then
            BRIDGE_ADDR="${BRIDGE_ADDR}:80"
        fi

        # ── Probe gateway → agent reachability to pick push vs pull ──
        BRIDGE_MODE="push"
        echo -n "  Probing gateway reachability to ${BRIDGE_ADDR}... "
        PROBE_RESULT=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/probe-webhook" \
            -H "X-Api-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
            -d "{\"addr\":\"${BRIDGE_ADDR}\"}" 2>/dev/null || echo '{"reachable":false,"error":"curl_failed"}')
        if echo "$PROBE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reachable',False))" 2>/dev/null | grep -q "True"; then
            echo "OK (push mode)"
        else
            BRIDGE_MODE="pull"
            PROBE_ERR=$(echo "$PROBE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','?'))" 2>/dev/null || echo "?")
            echo "unreachable (pull mode, reason: $PROBE_ERR)"
        fi

        # ── Write bridge_url to amail_gateway.json (used by _auto_register_email) ──
        python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg['bridge_url'] = 'http://${BRIDGE_ADDR}/webhooks/amail-inbound'
json.dump(cfg, open(p, 'w'), indent=2)
"

        # Write bridge config
        if [ "$BRIDGE_MODE" = "push" ]; then
            cat > "$HOME/.hermes/amail_bridge.toml" << EOF
mode = "push"

[push]
bind_addr = "${BRIDGE_ADDR}"
EOF
        else
            cat > "$HOME/.hermes/amail_bridge.toml" << EOF
mode = "pull"

[pull]
gateway_url = "$GATEWAY_URL"
admin_key = "$ADMIN_KEY"
system_id = "$SYSTEM_ID"
poll_interval_sec = 10
EOF
        fi
        
        # Start bridge
        nohup "$BRIDGE_LINK" > "$HOME/.hermes/bridge.log" 2>&1 &
        BRIDGE_PID=$!
        echo $BRIDGE_PID > "$HOME/.hermes/bridge.pid"
        sleep 2
        
        if kill -0 "$BRIDGE_PID" 2>/dev/null; then
            step_ok "Bridge started (pid $BRIDGE_PID, ${BRIDGE_ADDR}, mode=${BRIDGE_MODE})"
            BRIDGE_NEEDED=true
        else
            step_warn "Bridge failed to start — check $HOME/.hermes/bridge.log"
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════
# Step 6: Install amail tools into Hermes
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TOOLS"

TOOLSETS_PY="$HERMES_DIR/toolsets.py"
TOOLS_DST="$HERMES_DIR/tools/amail_tools.py"

if [ -f "$TOOLS_DST" ] && grep -q "send_mail" "$TOOLSETS_PY" 2>/dev/null; then
    step_ok "$T_TOOLS_SKIP"
else
    # Copy the tool file
    mkdir -p "$HERMES_DIR/tools"
    echo -n "  $T_TOOLS_COPY "
    if cp "$TOOLS_PY" "$TOOLS_DST" 2>/dev/null; then
        echo "$T_OK"
    else
        echo "$T_FAILED"
        step_fail "$T_TOOLS_FAIL"
    fi

    # Register in toolsets.py
    echo -n "  $T_TOOLS_REG "
    if [ -f "$TOOLSETS_PY" ]; then
        python3 << PYEOF
import re
path = "$TOOLSETS_PY"
with open(path) as f:
    content = f.read()

needs_write = False

# Add tool names to _HERMES_CORE_TOOLS if not present
tool_names = ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"]
for name in tool_names:
    if f'"{name}"' not in content.strip():
        content = re.sub(r'(_HERMES_CORE_TOOLS\\s*=\\s*\\[)', r'\\1\\n    "' + name + '",', content, count=1)
        needs_write = True

# Add amail toolset to TOOLSETS if not present
if '"amail"' not in content:
    amail_block = '''    "amail": {
        "description": "Agent email tools: send, contacts, contact profiles, and thread summaries via amail",
        "tools": ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"],
        "includes": [],
    },'''
    content = re.sub(r'(TOOLSETS\\s*=\\s*\\{)', r'\\1\\n' + amail_block, content, count=1)
    needs_write = True

if needs_write:
    with open(path, 'w') as f:
        f.write(content)
    print("updated")
else:
    print("nochange")
PYEOF
        echo "$T_OK"
    else
        echo "$T_FAILED"
        step_warn "$T_TOOLS_FAIL"
    fi
fi

# ═══════════════════════════════════════════════════════════════
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
        python3 "$SCRIPT_DIR/patches/apply_profiles_patch.py" "$PROFILES_PY" 2>/dev/null && echo "$T_OK" || echo "$T_FAILED"
        if grep -q "trigger_profile_hooks" "$PROFILES_PY" 2>/dev/null; then
            step_ok "$T_PROFILES_DONE"
        else
            step_warn "$T_PROFILES_FAIL"
        fi
    fi

    # Register existing profiles that don't have amail.json yet
    info "$T_PROFILES_REGISTER"
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
    echo "$REG_OUTPUT" | while IFS=: read key val; do
        case "$key" in
            registered) REG_COUNT="$val" ;;
            failed) info "  ⚠ $val" ;;
            no_config) info "  No gateway config — skip" ;;
        esac
    done
    REG_COUNT=$(echo "$REG_OUTPUT" | grep '^registered:' | cut -d: -f2)
    if [ "${REG_COUNT:-0}" -gt 0 ]; then
        echo "  $T_PROFILES_REG_DONE" | sed "s/{count}/$REG_COUNT/"
    else
        info "$T_PROFILES_REG_SKIP"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# Step 9: Diagnostics
# ═══════════════════════════════════════════════════════════════
step_begin "$T_DIAG"

DIAG=$(python3 << PYEOF
import sys, json
sys.path.insert(0, "$SCRIPT_DIR/tools")
from amail_tools import verify_integration
result = verify_integration(gateway_url="$GATEWAY_URL", admin_key="$ADMIN_KEY")
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
echo "  ├─ bridge:      $( [ "$BRIDGE_NEEDED" = true ] && echo "deployed" || echo "not needed" )"
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
