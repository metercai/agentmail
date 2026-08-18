#!/usr/bin/env bash
# install-skill.sh — 安装 agentmail skill 到 DeerFlow skills 目录
# SKILL.md 是通用邮件处理规范(与 Hermes/OpenClaw 共用同一源),直接拷贝
# agentmail/skills/SKILL.md → {DEER_FLOW_HOME}/skills/public/agentmail/SKILL.md
set -e

REPO_DIR="$(cd "$(dirname "$(dirname "$(dirname "$0")")")" && pwd)"
SRC="$REPO_DIR/skills/SKILL.md"
DEER_FLOW_HOME="${DEER_FLOW_HOME:-$HOME/deer-flow}"
DST_DIR="${DEER_FLOW_SKILLS_DIR:-$DEER_FLOW_HOME/skills/public}/agentmail"

if [ ! -f "$SRC" ]; then
  echo "SKILL source not found: $SRC" >&2
  exit 1
fi
mkdir -p "$DST_DIR"
cp "$SRC" "$DST_DIR/SKILL.md"
cp "$REPO_DIR/skills/DESCRIPTION.md" "$DST_DIR/DESCRIPTION.md" 2>/dev/null || true

echo "installed agentmail skill → $DST_DIR/SKILL.md"
echo "verify: ls $DST_DIR"
