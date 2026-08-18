#!/usr/bin/env bash
# install-skill.sh — 安装 agentmail SKILL 到 dsh 技能目录(逐字拷贝,零改写)
#
# 用法:
#   bash install-skill.sh [DSH_HOME] [AMAIL_REPO]
#     DSH_HOME   默认 ~/.dsh(全局技能 <DSH_HOME>/skills/agentmail/)
#     AMAIL_REPO 默认 ~/agentmail(SKILL.md 源)
set -euo pipefail

DSH_HOME="${1:-$HOME/.dsh}"
AMAIL_REPO="${2:-$HOME/agentmail}"

SRC="$AMAIL_REPO/skills/SKILL.md"
DST_DIR="$DSH_HOME/skills/agentmail"

[ -f "$SRC" ] || { echo "ERROR: SKILL.md not found: $SRC"; exit 1; }

mkdir -p "$DST_DIR"
if [ -f "$DST_DIR/SKILL.md" ] && cmp -s "$SRC" "$DST_DIR/SKILL.md"; then
    echo "  ✓ SKILL 已就位且一致(跳过拷贝)"
else
    cp "$SRC" "$DST_DIR/SKILL.md"
    echo "  ✓ SKILL 已拷贝 → $DST_DIR/SKILL.md"
fi
echo "  提示:preset 技能目录(<preset>/skills/)或项目级 skills/ 亦可,零改写即可"
