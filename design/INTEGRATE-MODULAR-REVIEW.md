# integrate.sh Modular — Code Review Report

## Verification

| 检查项 | 状态 |
|--------|------|
| integrate.sh bash -n | ✅ |
| 7 lib scripts bash -n | ✅ |
| 总行数 | 393 (main) + 641 (lib) = 1034 |

## Critical

### 1. Step count exceeds "10 steps" header

Main script header says "Up to 10 steps". deploy-bridge.sh adds internal `step_begin` calls (domain key + bridge deploy + bridge key = 3 steps). Total: 5 (main) + 3 (bridge) + 5 (sub-scripts) = 13. Header should be updated.

**Fix**: Update line header comment to "Up to 13 steps" or remove step count from header.

### 2. `send-test.sh` temp key not cleaned up on failure

Creates a test agent key and domain. If the test fails mid-way (e.g. `TEST_AGENT_KEY` retrieval fails), the cleanup block is skipped. Pre-existing issue, now isolated in this file.

**Fix**: Add `trap cleanup EXIT` at the beginning of send-test.sh.

## Medium

### 3. `deploy-bridge.sh` modifies `WEBHOOK_HOST` after config saved

Bridge mode (option 3): `WEBHOOK_HOST` starts empty → Step 5 writes `webhook_host=""` → Step 5a auto-detects and sets `WEBHOOK_HOST`. The `amail_gateway.json` has stale `webhook_host=""`. Domain key update (line 19-25) only updates `admin_key`, not `webhook_host`.

Impact: `_auto_register_email` reads `webhook_host=""` → treats as local gateway, not bridge. For pull mode this is acceptable (no callback URL needed), but for push mode (direct) it could be wrong.

**Fix**: deploy-bridge.sh should update `amail_gateway.json webhook_host` after auto-detection.

### 4. `install-tools.sh` Python heredoc — `$TOOLSETS_PY` not expanded

```bash
python3 << PYEOF
path = "$TOOLSETS_PY"
```

Heredoc marker is unquoted `PYEOF` — bash will expand `$TOOLSETS_PY`. This works but is fragile if the path contains special characters.

**Fix**: Use quoted heredoc `'PYEOF'` and pass via env:

```bash
export INSTALL_TOOLSETS_PY="$TOOLSETS_PY"
python3 << 'PYEOF'
path = os.environ["INSTALL_TOOLSETS_PY"]
```

## Low

### 5. Missing `$T_DONE` message

Original script had a "Integration complete!" message before the summary. The modular version lost this — `send-test.sh` goes directly from test cleanup to summary.

### 6. `patch-profiles.sh` — `_auto_register_email` error handling

Line-level `try/except` catches all exceptions but only logs `failed:{name}:{e}`. Real failures (network error, auth failure) are logged but the script continues. Acceptable for a registration sweep, but could miss systemic issues.

## Variable Flow Audit

| Variable | Set in | Read by |
|----------|--------|---------|
| ADMIN_KEY | main (Step 2/5), deploy-bridge.sh | deploy-bridge, diagnostics, send-test, patch-profiles |
| GATEWAY_URL | main (Step 1) | deploy-bridge, diagnostics, send-test, patch-profiles |
| SYSTEM_ID | main (Step 2/5) | deploy-bridge, send-test |
| AMAIL_DOMAIN | main (Step 3/5) | deploy-bridge, send-test |
| WEBHOOK_HOST | main (Step 4), deploy-bridge | deploy-bridge, send-test |
| WEBHOOK_MODE | main (Step 4) | deploy-bridge |
| USE_PRODUCT_CODE | main (Step 2) | deploy-bridge |
| HERMES_DIR | main | install-tools, patch-webhook, patch-profiles |
| SCRIPT_DIR | main | all (via env) |
| step_counter | helpers.sh | all |

All cross-boundary variable flows are valid — no undefined variable references.

## Conclusion

- ✅ Logic: step flow preserved, all Steps 1-10 execute in order
- ✅ Safety: `set -eo pipefail` active, curl failures handled
- ✅ Idempotency: config reuse logic preserved in Step 2
- 🔴 2 criticals to fix, 3 mediums, 2 lows
