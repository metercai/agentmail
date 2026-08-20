#!/usr/bin/env bash
# install-mcp.sh — 写 DeerFlow extensions_config.json 的 amail MCP server 块
# 复用共享 tools/amail_mcp_server.py(兜底 MCP 服务,平台无关,零适配)。
# 幂等: 已存在 amail server 块则更新路径/env,否则追加。
set -e

REPO_DIR="$(cd "$(dirname "$(dirname "$(dirname "$0")")")" && pwd)"
SERVER="$REPO_DIR/tools/amail_mcp_server.py"
DEER_FLOW_HOME="${DEER_FLOW_HOME:-$HOME/deer-flow}"
CFG="${DEER_FLOW_EXT_CFG:-$DEER_FLOW_HOME/extensions_config.json}"
AGENT_ID="${AIMAIL_AGENT_ID:-default}"

# 真实版本检测(只报检测结果,不猜测):backend/pyproject.toml 的 version
DF_VERSION="unknown"
for pp in "$DEER_FLOW_HOME/backend/pyproject.toml" "$DEER_FLOW_HOME/pyproject.toml"; do
  if [ -f "$pp" ]; then
    DF_VERSION="$(grep -m1 '^version' "$pp" | sed -E 's/.*=\s*"([^"]+)".*/\1/')"
    [ -n "$DF_VERSION" ] && break
  fi
done
IDENTITY="deerflow/${DF_VERSION:-unknown}"

if [ ! -f "$SERVER" ]; then
  echo "MCP server not found: $SERVER" >&2
  exit 1
fi

# 确保配置文件存在(缺失时以示例为模板)
if [ ! -f "$CFG" ]; then
  if [ -f "$DEER_FLOW_HOME/extensions_config.example.json" ]; then
    cp "$DEER_FLOW_HOME/extensions_config.example.json" "$CFG"
    echo "created $CFG from example"
  else
    echo '{"mcpServers": {}}' > "$CFG"
    echo "created empty $CFG"
  fi
fi

python3 - "$CFG" "$SERVER" "$AGENT_ID" "$IDENTITY" <<'PY'
import json, sys

cfg_path, server, agent_id, identity = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(cfg_path) as f:
    data = json.load(f)

servers = data.setdefault("mcpServers", {})
servers["amail"] = {
    "enabled": True,
    "type": "stdio",
    "command": "python3",
    "args": [server],
    "env": {"AIMAIL_AGENT_ID": agent_id,
            "AIMAIL_AGENT_IDENTITY": identity},
    "tool_name_prefix": True,
    "session_init_timeout": 60,
    "tool_call_timeout": 60,
    "description": "AgentMail email tools (shared fallback MCP server)",
}

with open(cfg_path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print(f"wrote mcpServers.amail → {cfg_path}")
print(f"  server: {server}")
print(f"  AIMAIL_AGENT_ID: {agent_id}")
print(f"  AIMAIL_AGENT_IDENTITY: {identity}")
PY

echo "verify: python3 -c \"import json; d=json.load(open('$CFG')); print(d['mcpServers']['amail']['args'])\""
