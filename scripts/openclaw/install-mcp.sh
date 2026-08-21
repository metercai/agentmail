#!/usr/bin/env bash
# install-mcp.sh — 给 ~/.openclaw/openclaw.json 的 amail MCP server 块注入
# 平台身份(AIMAIL_AGENT_IDENTITY=openclaw/{version}),并把 server 指向
# 自包含捆绑 ~/.agentmail/mcp/(与仓库路径解耦,改名/mv 不影响运行)。
#
# 共享 amail_mcp_server.py(兜底 MCP 服务,平台无关,零适配)。
# 身份只能由调用接口层声明(启动层 env),server 零猜测——缺 env 时
# 共享 server 报 unknown/unknown,不会目录猜测误报。
# 幂等:已存在 amail server 块则更新 env/路径,否则追加;其余配置原样保留。
set -e

REPO_DIR="$(cd "$(dirname "$(dirname "$(dirname "$0")")")" && pwd)"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CFG="$OC_HOME/openclaw.json"
AGENT_ID="${AIMAIL_AGENT_ID:-main}"
BUNDLE_DIR="${AIMAIL_MCP_BUNDLE:-$HOME/.agentmail/mcp}"

[ -f "$CFG" ] || { echo "openclaw.json not found: $CFG (OpenClaw not installed?)" >&2; exit 1; }

# ── 1. 安装/更新 MCP 捆绑(源: pip aimail > 仓库 tools/)────────────
python3 "$REPO_DIR/scripts/runtime_bundle.py" install mcp --dest "$BUNDLE_DIR"
SERVER="$BUNDLE_DIR/amail_mcp_server.py"
[ -f "$SERVER" ] || { echo "MCP bundle missing: $SERVER" >&2; exit 1; }

# ── 2. 真实版本检测(只报检测结果,不猜测):openclaw --version ────────
OC_VERSION="unknown"
if command -v openclaw >/dev/null 2>&1; then
  OC_VERSION="$(openclaw --version 2>/dev/null | grep -oE '[0-9][0-9.]*-?[0-9]*' | head -1 || true)"
fi
[ -n "$OC_VERSION" ] || OC_VERSION="unknown"
IDENTITY="openclaw/${OC_VERSION}"

python3 - "$CFG" "$SERVER" "$AGENT_ID" "$IDENTITY" <<'PY'
import json, sys

cfg_path, server, agent_id, identity = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(cfg_path) as f:
    data = json.load(f)

servers = data.setdefault("mcp", {}).setdefault("servers", {})
amail = servers.setdefault("amail", {})
amail["command"] = "python3"
amail["args"] = [server]
amail.setdefault("transport", "stdio")
env = amail.setdefault("env", {})
env.setdefault("AIMAIL_AGENT_ID", agent_id)
env["AIMAIL_AGENT_IDENTITY"] = identity

with open(cfg_path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print(f"updated mcp.servers.amail → {cfg_path}")
print(f"  server: {server}")
print(f"  AIMAIL_AGENT_ID: {env['AIMAIL_AGENT_ID']}")
print(f"  AIMAIL_AGENT_IDENTITY: {identity}")
PY

echo "verify: python3 -c \"import json; d=json.load(open('$CFG')); print(d['mcp']['servers']['amail']['args'])\""
