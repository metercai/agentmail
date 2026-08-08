#!/usr/bin/env bash
# install-agent-wrapper.sh — 安装 openclaw agents 生命周期 wrapper（PATH 前置）
# ═══════════════════════════════════════════════════════════════════
# 1. 定位真实 openclaw 绝对路径（npm -g bin）
# 2. 生成 ~/.openclaw/bin/openclaw（wrapper，内嵌真实路径）
# 3. ~/.openclaw/bin 前置到 PATH（~/.bashrc 幂等追加）
set -e

REAL=$(readlink -f "$(command -v openclaw)" 2>/dev/null || command -v openclaw)
[ -n "$REAL" ] || { echo "openclaw not found in PATH"; exit 1; }

WRAPPER_SRC="$HOME/agentmail/scripts/openclaw/openclaw-wrapper.sh"
DEST_DIR="$HOME/.openclaw/bin"
DEST="$DEST_DIR/openclaw"

mkdir -p "$DEST_DIR"
sed "s|__REAL_OPENCLAW__|$REAL|" "$WRAPPER_SRC" > "$DEST"
chmod +x "$DEST"
echo "wrapper installed: $DEST → $REAL"

# PATH 前置（幂等）
BASHRC="$HOME/.bashrc"
LINE='export PATH="$HOME/.openclaw/bin:$PATH"'
if ! grep -qF "$LINE" "$BASHRC" 2>/dev/null; then
    printf '\n# openclaw agents lifecycle wrapper (amail integration)\n%s\n' "$LINE" >> "$BASHRC"
    echo "PATH 前置已追加到 ~/.bashrc"
else
    echo "PATH 前置已存在（跳过）"
fi

echo "提示：注册 agent 时若 AMAIL_SYSTEM_ID 已设置，agents add/delete 将自动串接 amail 注册/注销。"
echo "      审批联系人通过 AMAIL_MANAGER 环境变量提供。"
