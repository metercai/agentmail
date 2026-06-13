# Step 5a: Domain-level admin key + bridge deployment
# ═══════════════════════════════════════════════════════════════

if [ -n "$AMAIL_DOMAIN" ] && [ -n "$ADMIN_KEY" ] && [ -n "$GATEWAY_URL" ] && [ -n "$SYSTEM_ID" ]; then

    # Create domain-level admin key
    step_begin "Create domain-level admin key"
    DOMAIN_KEY_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/api-keys" \
        -H "X-Api-Key: $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d '{"system_id":"'"$SYSTEM_ID"'","email_address":"'"$AMAIL_DOMAIN"'","scopes":["system"],"category":"system"}' 2>/dev/null)
    DOMAIN_ADMIN_KEY=$(echo "$DOMAIN_KEY_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("raw_key",""))' 2>/dev/null)

    if [ -n "$DOMAIN_ADMIN_KEY" ]; then
        SYSTEM_ADMIN_KEY="$ADMIN_KEY"
        ADMIN_KEY="$DOMAIN_ADMIN_KEY"
        step_ok "domain admin key created ($AMAIL_DOMAIN)"

        python3 -c '
import json, os
p = os.path.expanduser("~/.hermes/amail_gateway.json")
cfg = json.load(open(p))
cfg["admin_key"] = "'"$ADMIN_KEY"'"
json.dump(cfg, open(p, "w"), indent=2)
' 2>/dev/null || true

        if $USE_PRODUCT_CODE && [ -n "$SYSTEM_ADMIN_KEY" ]; then
            echo "$SYSTEM_ADMIN_KEY" > "$HOME/.hermes/amail_system.key"
            chmod 600 "$HOME/.hermes/amail_system.key"
            step_ok "system admin key saved to ~/.hermes/amail_system.key"
        fi
    else
        step_warn "domain admin key creation failed — continuing with system admin key"
    fi

    # Bridge deployment
    if [ -n "$WEBHOOK_HOST" ] && [ "$WEBHOOK_MODE" != "internal" ]; then
        step_begin "Deploy amail-bridge"

        BRIDGE_DIR="$HOME/.hermes/bin"
        BRIDGE_BIN="${AMAIL_BRIDGE_BIN:-$BRIDGE_DIR/amail-bridge}"
        mkdir -p "$BRIDGE_DIR"

        if [ ! -x "$BRIDGE_BIN" ]; then
            BRIDGE_VERSION="${AMAIL_BRIDGE_VERSION:-v0.5.0}"
            curl -sL "https://github.com/metercai/amail-bridge/releases/download/${BRIDGE_VERSION}/amail-bridge-${BRIDGE_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
                | tar xz -C "$BRIDGE_DIR" amail-bridge 2>/dev/null || true
        fi

        if [ -x "$BRIDGE_BIN" ]; then
            if [ "$WEBHOOK_MODE" = "bridge" ]; then
                BRIDGE_ADDR="$(ip -4 addr show scope global 2>/dev/null | grep -oP 'inet \K[\d.]+' | grep -v 127.0.0.1 | head -1):38081"
                [ -z "$BRIDGE_ADDR" ] && BRIDGE_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}'):38081"
                [ -z "$BRIDGE_ADDR" ] && BRIDGE_ADDR="127.0.0.1:38081"
                WEBHOOK_HOST="$BRIDGE_ADDR"
            fi

            # Update amail_gateway.json with resolved webhook_host
            python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p))
cfg['webhook_host'] = '$WEBHOOK_HOST'
json.dump(cfg, open(p, 'w'), indent=2)
" 2>/dev/null || true

            BRIDGE_MODE="push"
            [ "$WEBHOOK_MODE" = "bridge" ] && BRIDGE_MODE="pull"

            PID_FILE="$HOME/.hermes/bridge.pid"
            [ -f "$PID_FILE" ] && kill "$(cat "$PID_FILE")" 2>/dev/null && rm -f "$PID_FILE"

            cat > "$HOME/.hermes/amail_bridge.toml" << EOF
addr = "${WEBHOOK_HOST}"
mode = "${BRIDGE_MODE}"

[pull]
amail_url = "${GATEWAY_URL}"
admin_key = "${ADMIN_KEY}"
system_id = "${SYSTEM_ID}"
poll_interval_sec = 10
EOF

            nohup "$BRIDGE_BIN" -c "$HOME/.hermes/amail_bridge.toml" > "$HOME/.hermes/bridge.log" 2>&1 &
            echo $! > "$PID_FILE"
            sleep 1

            if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
                step_ok "bridge started (mode=$BRIDGE_MODE, $WEBHOOK_HOST)"
            else
                step_warn "bridge failed to start — check $HOME/.hermes/bridge.log"
            fi
        else
            step_warn "bridge binary not found"
        fi
    elif [ -n "$WEBHOOK_HOST" ] && [ "$WEBHOOK_MODE" = "internal" ]; then
        cat > "$HOME/.hermes/amail_bridge.toml" << EOF
mode = "pull"

[pull]
amail_url = "${GATEWAY_URL}"
admin_key = "${ADMIN_KEY}"
system_id = "${SYSTEM_ID}"
poll_interval_sec = 10
EOF
        step_ok "bridge config written (pull mode, remote $WEBHOOK_HOST)"
    fi

    # Create bridge API key
    BRIDGE_DOMAIN="bridge-$(uuidgen 2>/dev/null | tr -d '-' | head -c 8 || openssl rand -hex 4)"
    BRIDGE_KEY_RESP=$(curl -s -X POST "$GATEWAY_URL/api/v1/api-keys" \
        -H "X-Api-Key: $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d '{"system_id":"'"$SYSTEM_ID"'","email_address":"'"${BRIDGE_DOMAIN}"'","scopes":["bridge"],"category":"bridge"}' 2>/dev/null)
    BRIDGE_API_KEY=$(echo "$BRIDGE_KEY_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("raw_key",""))' 2>/dev/null)
    if [ -n "$BRIDGE_API_KEY" ]; then
        python3 -c '
import os
p = os.path.expanduser("~/.hermes/amail_bridge.toml")
with open(p) as f:
    cfg = f.read()
if "api_key" not in cfg:
    cfg = cfg.replace("[pull]", "[pull]\napi_key = \"'"$BRIDGE_API_KEY"'\")
    with open(p, "w") as f:
        f.write(cfg)
' 2>/dev/null || true
        step_ok "bridge API key created (category=bridge, exempt)"
    fi
fi

