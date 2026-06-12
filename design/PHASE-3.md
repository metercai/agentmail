# Phase 3: integrate.sh — Step 4 合并 + 删除 Step 5.5

## 总体改动

1. Step 4 扩展：在 snapshot + manager_address 输入之后，增加 webhook 回调配置
2. 删除 Step 5.5 整个 section
3. 删除 `BRIDGE_DEPLOY`、`BRIDGE_MODE`、`BRIDGE_NEEDED` 变量
4. 删除 `delivery_mode`、`bridge_url` 写入

## Step 4 新增 webhook 配置块

在现有的 snapshot + manager_address 之后（Step 4 原内容之后），插入：

```bash
# ═══════════════════════════════════════════════════════════════
# Step 4.5: Webhook 回调配置
# ═══════════════════════════════════════════════════════════════

# 1. GATEWAY_URL 是否本机?
_is_local_gateway() {
    local host
    host=$(echo "$GATEWAY_URL" | sed 's|^https\?://||;s|:.*||;s|/.*||')
    if echo "$host" | grep -qE '^(127\.|0\.0\.0\.0|localhost|::1)$'; then
        return 0
    fi
    # 检查是否本机 IP
    local my_ip
    my_ip=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(1)
try:
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
except:
    print('')
" 2>/dev/null)
    [ -n "$my_ip" ] && [ "$host" = "$my_ip" ]
}

if _is_local_gateway; then
    WEBHOOK_HOST=""
    info "Gateway is local — no bridge needed"
    python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg['webhook_host'] = ''
json.dump(cfg, open(p, 'w'), indent=2)
"
else
    # 2. 选择模式
    echo ""
    info "Webhook callback — how gateway delivers inbound emails:"
    info "  [1] Public address (self-host bridge on public IP)"
    info "  [2] Internal bridge (existing bridge on LAN)"
    info "  [3] Self-host bridge (no public IP, auto-detect, pull mode)"
    echo -n "  Choose [1/2/3] (default 3): "; read -r WH_MODE
    WH_MODE="${WH_MODE:-3}"

    case "$WH_MODE" in
    1)  # direct
        read -r -p "  Public addr [ip:port or domain:port]: " WEBHOOK_HOST
        while echo "$WEBHOOK_HOST" | grep -qE '^(10\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[0-1]\.|192\.168\.|127\.|0\.|::1|localhost)'; do
            info "  Must be public address (not private/loopback)"
            read -r -p "  Public addr [ip:port or domain:port]: " WEBHOOK_HOST
        done
        step_ok "public address = $WEBHOOK_HOST"

        # 部署 bridge
        _deploy_bridge "$WEBHOOK_HOST" "push"
        ;;

    2)  # internal
        read -r -p "  Internal bridge addr [ip:port]: " WEBHOOK_HOST
        while ! echo "$WEBHOOK_HOST" | grep -qE '^(10\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[0-1]\.|192\.168\.)'; do
            info "  Must be internal IP:port (10.x/172.16-31.x/192.168.x)"
            read -r -p "  Internal bridge addr [ip:port]: " WEBHOOK_HOST
        done
        step_ok "internal bridge = $WEBHOOK_HOST"

        # 验证远端 bridge 存活
        echo -n "  Verifying bridge... "
        if curl -sf "http://$WEBHOOK_HOST/health" > /dev/null 2>&1; then
            echo "$T_OK"
        else
            echo "$T_FAILED"
            step_warn "Bridge at $WEBHOOK_HOST not reachable — check address"
        fi
        ;;

    3|*)  # bridge (self-host, pull)
        echo -n "  Auto-detecting bridge address... "
        BRIDGE_IP=$(python3 -c "
import socket, struct, fcntl, os
# 遍历网卡取第一个非 loopback IPv4
try:
    for ifname in os.listdir('/sys/class/net/'):
        if ifname == 'lo':
            continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ip = socket.inet_ntoa(
                fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', ifname.encode()))[20:24]
            )
            s.close()
            if not ip.startswith('127.'):
                print(ip)
                break
        except:
            continue
except:
    print('127.0.0.1')
" 2>/dev/null)
        BRIDGE_ADDR="${BRIDGE_IP:-127.0.0.1}:38081"
        WEBHOOK_HOST="$BRIDGE_ADDR"
        echo "$BRIDGE_ADDR"

        # 部署 bridge
        _deploy_bridge "$BRIDGE_ADDR" "pull"
        ;;
    esac

    # 写入 amail_gateway.json
    python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg['webhook_host'] = '${WEBHOOK_HOST}'
json.dump(cfg, open(p, 'w'), indent=2)
"
fi
```

## 新增辅助函数 `_deploy_bridge`

```bash
_deploy_bridge() {
    local addr=$1 mode=$2
    local bridge_dir="$HOME/.hermes/bin"
    local bridge_link="$bridge_dir/amail-bridge"
    local hostname="${WEBHOOK_HOST}"

    mkdir -p "$bridge_dir"

    # 定位二进制
    local bridge_bin=""
    if [ -n "${AMAIL_BRIDGE_BIN:-}" ] && [ -x "$AMAIL_BRIDGE_BIN" ]; then
        bridge_bin="$AMAIL_BRIDGE_BIN"
        ln -sf "$bridge_bin" "$bridge_link"
    else
        # GitHub 下载逻辑 (从原 Step 5.5 保留)
        local os_name arch_name
        os_name=$(uname -s | tr '[:upper:]' '[:lower:]')
        arch_name=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')

        local latest_tag
        latest_tag=$(curl -fsS "https://api.github.com/repos/metercai/amail-bridge/releases/latest" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || echo "")

        if [ -n "$latest_tag" ]; then
            local versioned="$bridge_dir/amail-bridge-${os_name}-${arch_name}-${latest_tag}"
            if [ ! -x "$versioned" ]; then
                echo -n "  Downloading bridge (${latest_tag})... "
                curl -fsSL "https://github.com/metercai/amail-bridge/releases/download/${latest_tag}/amail-bridge-${os_name}-${arch_name}-${latest_tag}" -o "$versioned" 2>/dev/null && chmod +x "$versioned" && echo "$T_OK" || echo "$T_FAILED"
            fi
            [ -x "$versioned" ] && bridge_bin="$versioned"
        fi

        [ -z "$bridge_bin" ] && step_warn "Bridge binary not found — skip" && return
        ln -sf "$bridge_bin" "$bridge_link"
    fi

    # 写 bridge.toml
    cat > "$HOME/.hermes/amail_bridge.toml" << EOF
addr = "${addr}"
hostname = "${hostname}"
mode = "${mode}"
EOF

    # 启动 bridge
    nohup "$bridge_link" -c "$HOME/.hermes/amail_bridge.toml" > "$HOME/.hermes/bridge.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$HOME/.hermes/bridge.pid"
    sleep 2

    if kill -0 "$pid" 2>/dev/null; then
        step_ok "Bridge started (pid $pid, ${addr}, mode=${mode})"

        # direct 模式加 probe-webhook 验证
        if [ "$WH_MODE" = "1" ]; then
            echo -n "  Probing gateway reachability... "
            local probe_result
            probe_result=$(curl -s -X POST "$GATEWAY_URL/api/v1/admin/probe-webhook" \
                -H "X-Api-Key: $ADMIN_KEY" \
                -H "Content-Type: application/json" \
                -d "{\"addr\":\"${WEBHOOK_HOST}\"}" 2>/dev/null || echo '{"reachable":false}')
            if echo "$probe_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reachable',False))" 2>/dev/null | grep -q "True"; then
                echo "reachable"
            else
                echo "unreachable — push delivery may fail"
            fi
        fi
    else
        step_warn "Bridge failed to start — check $HOME/.hermes/bridge.log"
    fi
}
```

## 删除内容

1. **Step 5.5 整个 section**（行 670-860 左右）
2. `BRIDGE_DEPLOY`、`BRIDGE_MODE`、`BRIDGE_NEEDED` 变量定义
3. `delivery_mode` 写入（行 815 的 `cfg['delivery_mode'] = '${BRIDGE_MODE}'`）
4. `bridge_url` 写入（已不存在，确认即可）
5. `amail_bridge.toml` 中 `[push]` section（新模板只 `addr` + `hostname` + `mode`）

## 检测方法

```bash
cd /home/ubuntu/agentmail

# 语法
bash -n integrate.sh && echo "syntax OK"

# 三种模式各跑一遍 (在测试环境):
./integrate.sh  # [3] bridge (default)
# 验证: bridge 启动, /health 200, amail_gateway.json webhook_host 正确

./integrate.sh  # [1] direct + 公网 IP
# 验证: probe-webhook 探测, bridge 启动

./integrate.sh  # [2] internal + 内网 IP
# 验证: bridge 不部署, /health 200, 配置正确

# 二次运行(幂等):
./integrate.sh
# 验证: 已有值作为默认值, 不重复部署
```
