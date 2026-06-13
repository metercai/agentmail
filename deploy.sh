#!/usr/bin/env bash
# amail-deploy.sh — 部署 amail-advanced + amail-bridge 到云主机
#
# 用法:
#   export AMAIL_DEPLOY_HOST="1.2.3.4"
#   export AMAIL_DEPLOY_PORT="22"
#   export AMAIL_DEPLOY_USER="root"
#   # SSH key 路径（可选，默认 ~/.ssh/id_rsa）
#   export AMAIL_DEPLOY_KEY="~/.ssh/deploy_key"
#
#   bash amail-deploy.sh upload      # 上传二进制
#   bash amail-deploy.sh start       # 启动服务
#   bash amail-deploy.sh stop        # 停止服务
#   bash amail-deploy.sh restart     # 重启
#   bash amail-deploy.sh status      # 查看状态
#   bash amail-deploy.sh logs        # 查看日志
#   bash amail-deploy.sh health      # curl /health 检查

set -eo pipefail

HOST="${AMAIL_DEPLOY_HOST:?AMAIL_DEPLOY_HOST not set}"
PORT="${AMAIL_DEPLOY_PORT:-22}"
USER="${AMAIL_DEPLOY_USER:-root}"
KEY="${AMAIL_DEPLOY_KEY:-}"
SSH_OPTS="-p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
[ -n "$KEY" ] && SSH_OPTS="$SSH_OPTS -i $KEY"

SSH="ssh $SSH_OPTS ${USER}@${HOST}"
SCP="scp $SSH_OPTS"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADVANCED_BIN="${SCRIPT_DIR}/../amail-advanced/target/release/amail-advanced"
BRIDGE_BIN="${SCRIPT_DIR}/../amail-bridge/target/release/amail-bridge"
REMOTE_DIR="/usr/local/bin"
SERVICE_NAME="amail-advanced"

upload() {
    echo "Uploading amail-advanced..."
    [ -f "$ADVANCED_BIN" ] || { echo "ERROR: binary not found at $ADVANCED_BIN"; exit 1; }
    $SCP "$ADVANCED_BIN" "${USER}@${HOST}:${REMOTE_DIR}/amail-advanced"
    $SSH "chmod +x ${REMOTE_DIR}/amail-advanced && chown root:root ${REMOTE_DIR}/amail-advanced"
    echo "OK ($(ls -lh "$ADVANCED_BIN" | awk '{print $5}'))"

    echo "Uploading amail-bridge..."
    [ -f "$BRIDGE_BIN" ] || { echo "WARN: bridge binary not found, skipping"; return; }
    $SCP "$BRIDGE_BIN" "${USER}@${HOST}:${REMOTE_DIR}/amail-bridge"
    $SSH "chmod +x ${REMOTE_DIR}/amail-bridge && chown root:root ${REMOTE_DIR}/amail-bridge"
    echo "OK ($(ls -lh "$BRIDGE_BIN" | awk '{print $5}'))"
}

start() {
    $SSH "systemctl daemon-reload 2>/dev/null; systemctl enable --now ${SERVICE_NAME} 2>/dev/null && echo 'started (systemd)' || { \
        nohup ${REMOTE_DIR}/amail-advanced --config /etc/amail-gateway/config.toml --db /var/amail/amail.db > /var/log/amail-gateway.log 2>&1 &
        echo \$! > /var/run/amail-gateway.pid
        echo 'started (background)'; }"
}

stop() {
    $SSH "systemctl stop ${SERVICE_NAME} 2>/dev/null || { \
        [ -f /var/run/amail-gateway.pid ] && kill \$(cat /var/run/amail-gateway.pid) && rm -f /var/run/amail-gateway.pid && echo 'stopped'; \
    }"
}

restart() {
    stop
    sleep 1
    start
}

status() {
    $SSH "systemctl status ${SERVICE_NAME} 2>/dev/null || { \
        [ -f /var/run/amail-gateway.pid ] && echo 'running (pid: \$(cat /var/run/amail-gateway.pid))' || echo 'not running'; \
    }"
}

logs() {
    $SSH "journalctl -u ${SERVICE_NAME} --no-pager -n 50 2>/dev/null || tail -50 /var/log/amail-gateway.log 2>/dev/null || echo 'no logs'"
}

health() {
    $SSH "curl -sf http://127.0.0.1:38080/health && echo 'OK' || echo 'FAILED'"
}

case "$1" in
    upload|start|stop|restart|status|logs|health) "$1" ;;
    *) echo "Usage: $0 {upload|start|stop|restart|status|logs|health}" ;;
esac
