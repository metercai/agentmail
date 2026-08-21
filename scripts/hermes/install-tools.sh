#!/usr/bin/env bash
# install-tools.sh — 安装 aimail 运行时到 Hermes(捆绑 + toolsets 注册 + board role + skill)。
#
# 职责:
#   1. 运行时捆绑(core+bootstrap+适配器,自包含+版本戳)→ $HERMES_DIR/tools
#      (源 pip aimail > 仓库 tools/,经 runtime_bundle.py;运行与仓库路径解耦)
#   2. toolsets.py 注册 _HERMES_CORE_TOOLS tool names(幂等)
#   3. board role 文件 → ~/.agentmail/systems/${SYSTEM_ID}/board/role_prompt
#   4. skill(SKILL.md+DESCRIPTION.md)→ 每个 Hermes profile 的 skills/agentmail
#
# 用法: install-tools.sh   (HERMES_DIR / SYSTEM_ID 经 env,CLI 传入)
set -euo pipefail

HERMES_DIR="${HERMES_DIR:-$HOME/.hermes/hermes-agent}"
SYSTEM_ID="${SYSTEM_ID:-default}"
TOOLS_DST="$HERMES_DIR/tools"
TOOLSETS_PY="$HERMES_DIR/toolsets.py"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RB="$REPO_DIR/scripts/runtime_bundle.py"
PY="${PYTHON:-python3}"

# 源解析(pip 包优先,仓库 tools/ 兜底);不可解析则降级跳过(hermes 未装时)
if ! $PY "$RB" source >/dev/null 2>&1; then
    echo "  [WARN] aimail 运行时源不可解析(pip 包 / 仓库 tools/),跳过 hermes tool 安装"
    exit 0
fi

# ── 1. 运行时捆绑(自包含 + 版本戳)──────────────────────────────────
$PY "$RB" install hermes --dest "$TOOLS_DST"
echo "  hermes tool bundle: $TOOLS_DST"

# ── 2. toolsets.py 注册 _HERMES_CORE_TOOLS tool names(幂等)──────────
if [ -f "$TOOLSETS_PY" ]; then
    $PY - "$TOOLSETS_PY" <<'PYEOF'
import re, sys
path = sys.argv[1]
content = open(path, encoding="utf-8").read()
needs_write = False
tool_names = ["send_mail", "manage_contacts", "contact_profile",
              "set_contact_profile", "email_summary", "set_email_summary"]
for name in tool_names:
    if f'"{name}"' not in content:
        content = re.sub(r'(_HERMES_CORE_TOOLS\s*=\s*\[)',
                         r'\1\n    "' + name + '",', content, count=1)
        needs_write = True
if needs_write:
    open(path, "w", encoding="utf-8").write(content)
    print("  hermes toolsets: registered core tool names")
else:
    print("  hermes toolsets: already registered (skip)")
PYEOF
else
    echo "  hermes toolsets: $TOOLSETS_PY 缺失(跳过注册)"
fi

# ── 3. board role 文件 → systems/${SYSTEM_ID}/board/role_prompt ─────
ROLE_SRC=$($PY "$RB" resource board-role)
ROLE_DST="$HOME/.agentmail/systems/$SYSTEM_ID/board/role_prompt"
mkdir -p "$ROLE_DST"
for f in "$ROLE_SRC"/*.md; do
    [ -f "$f" ] || continue
    fname="$(basename "$f")"
    if [ ! -f "$ROLE_DST/$fname" ] || [ "$f" -nt "$ROLE_DST/$fname" ]; then
        cp "$f" "$ROLE_DST/$fname"
    fi
done
echo "  hermes board role: $ROLE_DST"

# ── 4. skill → 每个 Hermes profile 的 skills/agentmail ──────────────
SKILL_SRC=$($PY "$RB" resource skills)
for prof_dir in "$HOME/.hermes/profiles"/*/; do
    [ -d "$prof_dir" ] || continue
    prof_skill_dir="$prof_dir/skills/agentmail"
    for fname in SKILL.md DESCRIPTION.md; do
        [ -f "$SKILL_SRC/$fname" ] || continue
        dst="$prof_skill_dir/$fname"
        if [ ! -f "$dst" ] || ! cmp -s "$SKILL_SRC/$fname" "$dst"; then
            mkdir -p "$prof_skill_dir"
            cp "$SKILL_SRC/$fname" "$dst"
        fi
    done
done
echo "  hermes skill: ~/.hermes/profiles/*/skills/agentmail"
