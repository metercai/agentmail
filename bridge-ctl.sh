#!/usr/bin/env bash
# bridge-ctl.sh — standalone bridge lifecycle manager
# Usage:
#   bash bridge-ctl.sh start     Start bridge daemon
#   bash bridge-ctl.sh stop      Stop bridge gracefully
#   bash bridge-ctl.sh restart   Restart bridge (stop + start)
#   bash bridge-ctl.sh status    Check if bridge is running
#   bash bridge-ctl.sh log       Tail bridge log

set -eo pipefail

BIN="${HOME}/.agentmail/bin/amail-bridge"
CFG="${HOME}/.agentmail/amail_bridge.toml"
PID="${HOME}/.agentmail/bridge.pid"
LOG="${HOME}/.agentmail/amail-bridge.log"
NAME="amail-bridge"

# ── Help ────────────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    sed -n '3,8p' "$0"
    exit 0
fi

# ── Ensure binary exists ────────────────────────────────────────
require_bin() {
    if [ ! -x "$BIN" ]; then
        echo "✗ Binary not found: $BIN"
        echo "  Run 'bash integrate.sh' to deploy, or build manually:"
        echo "    cd amail-bridge && cargo build --release && cp target/release/amail-bridge $BIN"
        exit 1
    fi
}

# ── Wait for process to be alive ────────────────────────────────
wait_alive() {
    local pid=$1 max=10 i=0
    while kill -0 "$pid" 2>/dev/null; do
        return 0
    done
    for ((i=0; i<max; i++)); do
        sleep 0.5
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

# ── Commands ────────────────────────────────────────────────────
case "$1" in
start)
    require_bin
    if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
        echo "✓ ${NAME} already running (pid $(cat "$PID"))"
        exit 0
    fi
    echo "  Starting ${NAME}..."
    mkdir -p "$(dirname "$LOG")"
    nohup "$BIN" -c "$CFG" >> "$LOG" 2>&1 &
    BGPID=$!
    echo "$BGPID" > "$PID"
    if wait_alive "$BGPID"; then
        echo "✓ ${NAME} started (pid $BGPID)"
    else
        echo "✗ ${NAME} failed to start"
        tail -3 "$LOG" 2>/dev/null
        exit 1
    fi
    ;;

stop)
    if [ ! -f "$PID" ]; then
        # Try pkill fallback
        if pgrep -f "${BIN}" >/dev/null 2>&1; then
            echo "  Stopping ${NAME} (pkill)..."
            pkill -f "${BIN}" 2>/dev/null || true
        else
            echo "✓ ${NAME} not running"
            exit 0
        fi
    else
        OLLDPID=$(cat "$PID")
        if kill -0 "$OLLDPID" 2>/dev/null; then
            echo "  Stopping ${NAME} (pid $OLLDPID)..."
            kill "$OLLDPID" 2>/dev/null || true
            sleep 1
        fi
        rm -f "$PID"
    fi
    # Clean up orphan processes
    pkill -f "${BIN}" 2>/dev/null || true
    sleep 1
    if pgrep -f "${BIN}" >/dev/null 2>&1; then
        echo "✗ ${NAME} still running — force kill"
        pkill -9 -f "${BIN}" 2>/dev/null || true
    fi
    echo "✓ ${NAME} stopped"
    ;;

restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;

status)
    if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
        PIDVAL=$(cat "$PID")
        echo "✓ ${NAME} is running (pid $PIDVAL)"
        echo "  Binary: $BIN"
        echo "  Config: $CFG"
        echo "  Log:    $LOG"
        exit 0
    elif pgrep -f "${BIN}" >/dev/null 2>&1; then
        echo "⚠ ${NAME} is running (no pid file)"
        pgrep -la "${BIN}" | head -3
        exit 0
    else
        echo "✗ ${NAME} is not running"
        exit 1
    fi
    ;;

log)
    if [ -f "$LOG" ]; then
        tail -f "$LOG"
    else
        echo "Log not found: $LOG"
        exit 1
    fi
    ;;

*)
    echo "Unknown command: $1"
    echo "Usage: $0 {start|stop|restart|status|log}"
    exit 1
    ;;
esac
