#!/usr/bin/env bash
# openclaw — PATH 前置 wrapper：agents 生命周期串接 amail 注册/注销链
# ═══════════════════════════════════════════════════════════════════
# 行为对齐 Hermes（profile 创建→_auto_register_email / 删除→_auto_deregister_email）：
#   openclaw agents add <name>    → 原命令成功后执行 register_agent.py（amail 注册）
#   openclaw agents delete <id>   → deregister_agent.py（5 步注销链，内含 agents delete）
#   openclaw <其他>               → 原样透传真实 openclaw
# 由 install-agent-wrapper.sh 生成（内嵌真实 openclaw 绝对路径）。
set -u
REAL_OPENCLAW="__REAL_OPENCLAW__"
REPO="${AGENTMAIL_REPO:-$HOME/agentmail}"
SYS_ID="${AMAIL_SYSTEM_ID:-}"

err() { echo "[amail-wrapper] $*" >&2; }

# 未生成完整（REAL 不可执行，如占位符未替换）→ 直接透传
if [ ! -x "$REAL_OPENCLAW" ]; then
    exec openclaw "$@"
fi

sub="${1:-}"
cmd="${2:-}"

case "${sub}:${cmd}" in
    agents:add)
        name="${3:-}"
        if [ -z "$name" ]; then
            # 无 name 的 agents add 是交互式引导——透传（无法自动串接）
            exec "$REAL_OPENCLAW" "$@"
        fi
        "$REAL_OPENCLAW" agents add "$name" "${@:4}"
        rc=$?
        [ $rc -ne 0 ] && exit $rc
        if [ -z "$SYS_ID" ]; then
            err "agent '$name' 已创建，但 AMAIL_SYSTEM_ID 未设置——跳过 amail 注册"
            exit 0
        fi
        python3 "$REPO/scripts/openclaw/register_agent.py" --agent "$name" --system-id "$SYS_ID"
        exit $?
        ;;
    agents:delete)
        name="${3:-}"
        if [ -z "$name" ]; then
            exec "$REAL_OPENCLAW" "$@"
        fi
        if [ -z "$SYS_ID" ]; then
            err "AMAIL_SYSTEM_ID 未设置——直接执行 agents delete（跳过 amail 注销）"
            exec "$REAL_OPENCLAW" agents delete "$name" "${@:4}"
        fi
        # deregister_agent.py 内含 openclaw agents delete 步骤（注销链第 5 步）——不双删
        python3 "$REPO/scripts/openclaw/deregister_agent.py" --agent "$name" --system-id "$SYS_ID"
        exit $?
        ;;
    *)
        exec "$REAL_OPENCLAW" "$@"
        ;;
esac
