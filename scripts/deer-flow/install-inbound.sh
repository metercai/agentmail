#!/usr/bin/env bash
# install-inbound.sh — DeerFlow agentmail 入站补丁安装(仿 Hermes patch 模式,幂等)
#
# 背景(2026-08-18):DeerFlow 入站预处理并入其本地 gateway(8001)进程,
# 需要在 deer-flow 源码实施代码 patch(上游 bytedance/deer-flow 不保留
# 集成改动,git pull 保持干净)。本脚本负责:
#   1. 拷贝共享 router 源 tools/deer-flow/agentmail_inbound.py
#      → {DEER_FLOW_ROOT}/backend/app/gateway/routers/agentmail_inbound.py
#   2. patch backend/app/gateway/app.py:import + include_router(幂等)
#   3. 校验(语法 + 锚点存在)
# 安装后需重启 8001 生效。
#
# 用法:
#   bash install-inbound.sh [DEER_FLOW_ROOT] [AMAIL_REPO]
#     DEER_FLOW_ROOT  默认 ~/deer-flow
#     AMAIL_REPO      默认 ~/agentmail(agentmail_inbound.py 源所在)
set -euo pipefail

DEER_FLOW_ROOT="${1:-$HOME/deer-flow}"
AMAIL_REPO="${2:-$HOME/agentmail}"

SRC_ROUTER="$AMAIL_REPO/tools/deer-flow/agentmail_inbound.py"
G_DIR="$DEER_FLOW_ROOT/backend/app/gateway"   # 'gateway' 段变量化避免误匹配
DST_ROUTER="$G_DIR/routers/agentmail_inbound.py"
APP_PY="$G_DIR/app.py"

[ -f "$SRC_ROUTER" ] || { echo "ERROR: source router not found: $SRC_ROUTER"; exit 1; }
[ -f "$APP_PY" ] || { echo "ERROR: app.py not found: $APP_PY"; exit 1; }

# ── 1. 拷贝 router(内容一致则跳过)──────────────────────────────────
if [ -f "$DST_ROUTER" ] && cmp -s "$SRC_ROUTER" "$DST_ROUTER"; then
    echo "  ✓ router 已就位且一致(跳过拷贝)"
else
    cp "$SRC_ROUTER" "$DST_ROUTER"
    echo "  ✓ router 已拷贝 → $DST_ROUTER"
fi

# ── 2. patch app.py(幂等:import + include_router)────────────────────
PY_PATCH=$(cat <<'PY'
import sys

app_py = sys.argv[1]
src = open(app_py, encoding="utf-8").read()
changed = False

# 2a. import 行:挂在 agents 之后(字母序相邻)
import_marker = "    agents,\n"
import_line = "    agentmail_inbound,\n"
if import_line not in src:
    if import_marker in src:
        src = src.replace(import_marker, import_marker + import_line, 1)
        changed = True
    else:
        raise SystemExit("ERROR: import anchor 'agents,' not found in routers import block")

# 2b. include_router 行:挂在 agents.router 之后
route_marker = "    app.include_router(agents.router)\n"
route_line = "    app.include_router(agentmail_inbound.router)\n"
if route_line not in src:
    if route_marker in src:
        src = src.replace(route_marker, route_marker + route_line, 1)
        changed = True
    else:
        raise SystemExit("ERROR: include_router anchor 'agents.router' not found")

if changed:
    open(app_py, "w", encoding="utf-8").write(src)
    print("  ✓ app.py patched (import + include_router)")
else:
    print("  ✓ app.py 已含 agentmail_inbound(跳过)")
PY
)
"$DEER_FLOW_ROOT/backend/.venv/bin/python" -c "$PY_PATCH" "$APP_PY"

# ── 3. 校验 ─────────────────────────────────────────────────────────
"$DEER_FLOW_ROOT/backend/.venv/bin/python" -m py_compile "$DST_ROUTER" "$APP_PY"
grep -q "agentmail_inbound" "$APP_PY" || { echo "ERROR: app.py 锚点缺失"; exit 1; }
echo "  ✓ 语法校验通过 + 锚点确认"
echo ""
echo "完成。重启 DeerFlow gateway(8001)后生效:"
echo "  kill <uvicorn-pid> && cd $DEER_FLOW_ROOT/backend && DEER_FLOW_AUTH_DISABLED=1 \\"
echo "    PYTHONPATH=. PYTHONIOENCODING=utf-8 .venv/bin/uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001"
