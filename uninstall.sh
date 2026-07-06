#!/usr/bin/env bash
# uninstall.sh — Remove all amail integration changes from Hermes
# Usage: bash uninstall.sh
# Reads no env vars. Requires Python 3.
set -eo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
BOLD='\033[1m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BOLD}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        Amail — Hermes Integration Uninstall                 ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}This will:${NC}"
echo "  1. Stop Hermes gateway + amail bridge processes"
echo "  2. Restore 3 Hermes source files via git checkout"
echo "  3. Remove agentmail-inbound route from webhook_subscriptions.json"
echo "  4. Remove amail from config.yaml platform_toolsets"
echo "  5. Delete all amail config/skill/tool files from ~/.hermes/"
echo ""

echo -n -e "${BOLD}Continue? [y/N]: ${NC}"
read -r CONFIRM
if [ "${CONFIRM:-N}" != "y" ] && [ "${CONFIRM:-N}" != "Y" ]; then
    echo "  Cancelled."
    exit 0
fi

echo ""
python3 "$SCRIPT_DIR/scripts/uninstall_hermes.py"

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}${BOLD}Uninstall complete.${NC}"
else
    echo -e "${RED}${BOLD}Uninstall encountered issues (exit code $EXIT_CODE).${NC}"
    echo "  Check output above for details."
fi
echo ""
