# AgentMail Maintenance Guide

---

## Contents

1. [Local Storage](#1-local-storage)
2. [Logs](#2-logs)
3. [check_status Diagnostics](#3-check_status-diagnostics)
4. [amail-bridge](#4-amail-bridge)
5. [Hermes Gateway](#5-hermes-gateway)
6. [Common Issues](#6-common-issues)

---

## 1. Local Storage

### Directory Structure

```
~/.agentmail/
├── {system_id}/
│   ├── agentmail_gateway.json     # Gateway connection config (gateway_url, admin_key, system_id, domain)
│   ├── agentmail.json              # Root profile agent config (email, api_key)
│   ├── board/
│   │   └── role_prompt/            # Board role prompt files (installed from board/role_prompt_en/)
│   └── profiles/
│       └── {name}/
│           └── agentmail.json      # Named profile agent config (with persona email)
├── .system_raw_key/
│   └── {system_id}_admin.key  # System admin_key raw value (integration only)
├── amail-bridge.log            # Bridge logs
├── amail_bridge.toml           # Bridge config
├── amail_routes.toml           # Bridge route table
├── bin/
│   └── amail-bridge            # Bridge binary
├── bridge.pid                  # Bridge process PID
├── {email_hash}/
│   ├── agentmail.log           # Agent processing log (per email)
│   └── raw_email/              # Raw email snapshots (if save_raw_snapshots=true)
```

### Key Files

| File | Content | Written By |
|------|---------|------------|
| `agentmail_gateway.json` | gateway_url, admin_key, system_id, domain, system_name, save_raw_snapshots, manager_address, webhook_host | Step 4 `setup_system.py` |
| `agentmail.json` (root) | email, api_key, gateway_url, domain, system_id, manager_address | `_auto_register_email()` + `_auto_activate_profile()` |
| `profiles/{name}/agentmail.json` | Same + persona-prefixed email | Same |
| `amail_bridge.toml` | mode, addr/pull config | `deploy_bridge.py` |
| `board/role_prompt/*.md` | Role prompt templates | `install-tools.sh` |

### Path Migration

All config consolidated under `~/.agentmail/{system_id}/`. Legacy `~/.hermes/` configs (`agentmail.json`, `agentmail_gateway.json`) no longer used. Clean up manually if present.

---

## 2. Logs

### Log Files

| File | Content | Location |
|------|---------|----------|
| **agentmail.log** | Mail pipeline logs (ping/pong, inbound/outbound, preprocessing) | `~/.agentmail/{email_hash}/agentmail.log` |
| **amail-bridge.log** | Bridge runtime logs (pull, forward, routing, health) | `~/.agentmail/amail-bridge.log` |
| **gateway.log** | Hermes gateway log (per profile) | `~/.hermes/gateway.log` (root) or `~/.hermes/profiles/{name}/gateway.log` |

### agentmail.log Format

One JSON object per line:

```json
{"ts":"2026-06-26T07:18:41Z","dir":"ping_intercepted","ping_id":"54deaff9cacc","from":"925457@qq.com","to":["mike@amail.token.tm"]}
```

`dir` values:
- `ping_intercepted` — webhook received ping email
- `pong_sent` — pong sent via send_mail
- `pong_returned` — pong looped back to webhook
- `inbound` — normal inbound email

### Log Rotation

No auto-rotation. Configure logrotate or cron:

```bash
# /etc/logrotate.d/agentmail
~/.agentmail/*/agentmail.log {
    daily
    rotate 7
    compress
    missingok
}
~/.agentmail/amail-bridge.log {
    daily
    rotate 7
    compress
    missingok
}
```

---

## 3. check_status Diagnostics

### Run

```bash
# Full pipeline diagnostics
python3 scripts/check_status.py

# With repair suggestions
python3 scripts/check_status.py --verbose

# JSON output
python3 scripts/check_status.py --json

# End-to-end heartbeat test
python3 scripts/check_status.py --ping
```

### 4 Layers

| Layer | Checks | Purpose |
|-------|--------|---------|
| **Level 1: gateway** | Health / whoami / domain list | Verify gateway connectivity and permissions |
| **Level 2: bridge** | Process alive / pending query / log activity | Verify bridge runtime and pull path |
| **Level 3: agent-gw** | Webhook port reachable / route config | Verify Hermes gateway ready |
| **Level 4: profile** | Config file exists / email valid | Verify agent profile completeness |

### Ping/Pong Test

```bash
python3 scripts/check_status.py --ping
```

Sends ping via SMTP to gateway to bridge to webhook, triggers auto-pong reply, verifies full loop. Expected output:

```
  Ping sent: __agentmail_ping__:a1b2c3d4e5f6
  +  1.2s    Webhook Receive (ping)         OK
  +  2.9s    Pong Sent (send_mail)          OK
  +  5.1s    Webhook Return (pong)          OK
  Total round-trip: 5.1s
  Full pipeline verified
```

---

## 4. amail-bridge

### Process Management

```bash
# Status
ps aux | grep amail-bridge
cat ~/.agentmail/bridge.pid

# Restart
kill $(cat ~/.agentmail/bridge.pid)
python3 scripts/deploy_bridge.py

# Logs
tail -f ~/.agentmail/amail-bridge.log
```

### Config

`~/.agentmail/amail_bridge.toml`:

```toml
mode = "pull"

[pull]
amail_url = "https://amail.token.tm"
admin_key = "***"
system_id = "system-xxxx"
poll_interval_sec = 5

[health]
check_interval_sec = 60
fail_threshold = 3
connect_timeout_sec = 3
```

### Dual Modes

| Mode | Use Case | Description |
|------|----------|-------------|
| `pull` | Hermes on internal network, gateway external | Bridge polls for pending emails |
| `push` | Hermes and gateway same network | Gateway pushes webhook directly (no bridge) |

---

## 5. Hermes Gateway

### Process Management

```bash
# Start root profile gateway
hermes gateway run --accept-hooks --replace

# Start named profile gateway
hermes -p {name} gateway run --accept-hooks --replace

# Status
hermes gateway status

# Ports
grep -A2 'webhook:' ~/.hermes/config.yaml
```

### Multi-Profile Gateway

Each named profile runs an independent Hermes gateway process with separate ports and webhook routes. Managed by `scripts/hermes_gateway.sh`:

```bash
bash scripts/hermes_gateway.sh
```

### Health Check

```bash
curl http://127.0.0.1:{port}/health
```

Root profile default port 8644, named profiles from 8645 sequentially.

---

## 6. Common Issues

### Ping test stuck on "pong not returned"

**Cause:** Pong email failed to loop back. Usually API key / email mismatch.

**Check:**
```bash
grep pong_status ~/.agentmail/*/agentmail.log
```

**Fix:** Verify email and api_key match in `~/.agentmail/{system_id}/agentmail.json`.

### Bridge cannot pull emails

**Check:**
```bash
ps aux | grep amail-bridge
cat ~/.agentmail/amail_bridge.toml
curl https://amail.token.tm/health
tail -20 ~/.agentmail/amail-bridge.log
```

### Gateway won't start

**Check:**
```bash
ss -tlnp | grep 8644
hermes gateway run --dry-run
cat ~/.hermes/gateway.log
```

### Re-integration

```bash
# Clean (preserves ~/.agentmail/)
bash uninstall.sh

# Re-run
bash integrate.sh
```

`integrate.sh` is idempotent — re-runs skip completed steps.

### API Key Update

If gateway-side key is rotated or invalidated:

```bash
# Option 1: Clear activation_code and api_key in agentmail.json
# Option 2: Replace api_key directly
# Option 3: Re-run integrate.sh
```
