#!/usr/bin/env bash
# install-skill.sh — 安装 agentmail skill 到 OpenClaw 运行时目录
# SKILL.md 是通用邮件处理规范（与 Hermes 共用同一源），直接拷贝
# agentmail/skills/SKILL.md → ~/.openclaw/skills/agentmail/SKILL.md
set -e
REPO_DIR="$(cd "$(dirname "$(dirname "$(dirname "$0")")")" && pwd)"
SRC="$REPO_DIR/skills/SKILL.md"
DST_DIR="${OPENCLAW_SKILLS_DIR:-$HOME/.openclaw/skills}/agentmail"

mkdir -p "$DST_DIR"
cp "$SRC" "$DST_DIR/SKILL.md"

echo "installed agentmail skill → $DST_DIR/SKILL.md"
echo "verify: openclaw skills list | grep agentmail"
