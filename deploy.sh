#!/usr/bin/env bash
# amail-deploy.sh — 部署 amail-advanced 到云主机
#
# 用法:
#   export AMAIL_DEPLOY_HOST="1.2.3.4"
#   export AMAIL_DEPLOY_PORT="22"
#   export AMAIL_DEPLOY_USER="root"
#   # SSH key 路径（可选，默认 ~/.ssh/id_rsa）
#   export AMAIL_DEPLOY_KEY="$HOME/.ssh/id_deploy"
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
# 自动检测部署密钥（无密码）
if [ -z "$KEY" ] && [ -f "$HOME/.ssh/id_deploy" ]; then
    KEY="$HOME/.ssh/id_deploy"
fi
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
[ -n "$KEY" ] && SSH_OPTS="$SSH_OPTS -i $KEY"

SSH="ssh -p $PORT $SSH_OPTS ${USER}@${HOST}"
SCP="scp -P $PORT $SSH_OPTS"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADVANCED_BIN="${SCRIPT_DIR}/../amail-advanced/target/release/amail-advanced"
REMOTE_DIR="/usr/local/bin"
CONFIG="/etc/amail/config.toml"
WORKDIR="/var/amail"
SERVICE_NAME="amail-advanced"

upload() {
    echo "Uploading amail-advanced..."
    [ -f "$ADVANCED_BIN" ] || { echo "ERROR: binary not found at $ADVANCED_BIN"; exit 1; }
    $SCP "$ADVANCED_BIN" "${USER}@${HOST}:${REMOTE_DIR}/amail-advanced"
    $SSH "chmod +x ${REMOTE_DIR}/amail-advanced"
    echo "OK ($(ls -lh "$ADVANCED_BIN" | awk '{print $5}'))"
}

start() {
    $SSH "mkdir -p $WORKDIR && \
    systemctl cat ${SERVICE_NAME} >/dev/null 2>&1 && \
    systemctl start ${SERVICE_NAME} && echo 'started (systemd)' || \
    nohup ${REMOTE_DIR}/amail-advanced --config $CONFIG \
      > /var/log/amail-gateway.log 2>&1 & \
    echo \$! > /var/run/amail-gateway.pid && \
    echo 'started (background)'"
}

stop() {
    $SSH "systemctl stop ${SERVICE_NAME} 2>/dev/null || \
    { [ -f /var/run/amail-gateway.pid ] && \
      kill \$(cat /var/run/amail-gateway.pid) 2>/dev/null && \
      rm -f /var/run/amail-gateway.pid && echo 'stopped'; }"
}

restart() {
    stop
    sleep 1
    start
}

status() {
    $SSH "systemctl status ${SERVICE_NAME} 2>/dev/null || \
    { [ -f /var/run/amail-gateway.pid ] && \
      echo 'running (pid: '$(cat /var/run/amail-gateway.pid)')' || \
      echo 'not running'; }"
}

logs() {
    $SSH "journalctl -u ${SERVICE_NAME} --no-pager -n 50 2>/dev/null || \
    tail -50 /var/log/amail-gateway.log 2>/dev/null || echo 'no logs'"
}

health() {
    $SSH "curl -sf http://127.0.0.1:38080/health && echo 'OK' || echo 'FAILED'"
}

setup_systemd() {
    $SSH "cat > /etc/systemd/system/${SERVICE_NAME}.service << 'SYSTEMD'
[Unit]
Description=amail-gateway (advanced edition)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$WORKDIR
ExecStart=${REMOTE_DIR}/amail-advanced --config $CONFIG
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SYSTEMD
systemctl daemon-reload && echo 'systemd unit installed'"
}

case "$1" in
    upload|start|stop|restart|status|logs|health|setup-systemd) setup_systemd ;;
    *) echo "Usage: $0 {upload|start|stop|restart|status|logs|health|setup-systemd}" ;;
esac
