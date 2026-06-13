# Webhook Configuration Chain Revision — Master Plan

## Overview

Refactor amail ecosystem webhook configuration chain:
- Remove delivery_mode field (use webhook_url empty/non-empty)
- Unify push/pull decision to bridge-side
- Simplify integrate.sh flow (merge Step 4 + 5.5)
- Add multi-level API key permissions with category/domain_addr contract

## Part A: Completed (Pushed to All Repos)

### A1. Bridge Enhancement

- hostname/tls_cert/tls_key/acme_cache promoted from [push] to top-level config
- has_tls() now checks if hostname is domain (not IP)
- is_dual_port() guards against IP hostname false positive
- POST /api/v1/routes returns {"status":"ok","webhook_url":"..."}
  - push mode: http(s)://bridge_addr/webhooks/amail-inbound
  - pull mode: "" (empty string)
- Protocol detection: IP hostname -> http, domain hostname -> https
- Auto-discovery (profile scanning) removed — routes loaded from amail_routes.toml only
- Simplified file watcher: only monitors amail_routes.toml for hot-reload
- write_current_routes() eliminates read-modify-write race in update_route/remove_route

### A2. Gateway delivery_mode Removal

- system_domains.delivery_mode column removed from DDL and all queries
- webhook.rs: d.delivery_mode == "pull" -> d.webhook_url.trim().is_empty()
- SystemDomainRecord: delivery_mode field removed
- factory.rs create_domain/update_domain: delivery_mode parameter removed
- types.rs: 3 request structs (CreateSystemDomain, RegisterAddress, UpdateSystemDomain) — delivery_mode removed
- http.rs: 3 handlers — delivery_mode parameter removed
- amail-advanced: 2 call sites (activation.rs, server.rs) — extra None parameter removed

### A3. amail_tools.py Rewrite

- _auto_register_email:
  - webhook_host="" -> direct Hermes webhook (local gateway)
  - webhook_host=non-empty -> call bridge POST /api/v1/routes -> get webhook_url
  - Protocol: IP -> http, domain -> https
- _auto_activate_profile: port change detection -> re-register bridge route
- delivery_mode completely removed from GatewayClient.register_email
- bridge_url legacy migration code deleted
- _wh_port persisted to amail.json for port change tracking

### A4. integrate.sh Simplification

- Step 5.5 (Bridge Deployment) entire section deleted
- _is_local_gateway check added at Step 4 entry
  - gateway is local -> webhook_host="", skip bridge
  - gateway is remote -> show 3 options (direct/internal/bridge)
- BRIDGE_DEPLOY/BRIDGE_MODE/BRIDGE_NEEDED variables deleted
- delivery_mode write deleted
- AMAIL_DELIVERY_MODE env export deleted
- Bash syntax validated, re-runnable (idempotent)

### A5. Pending TTL Cleanup

- WebhookConfig.pending_ttl_hours added (default 72)
- cleanup_deliveries(ttl_hours) now deletes stale pending records
- Scheduler spawns periodic cleanup task every ttl/2 hours

### A6. Documentation

- delivery_mode and bridge_url removed from hermes-amail-integration.md (EN/ZH)
- Design documents: REVISION-WEBHOOK-CHAIN.md, INTEGRATED-VIEW.md
- Audit reports: BRIDGE-CODE-REVIEW.md, GATEWAY-BASE-AUDIT.md, SECOND-AUDIT.md
- Phase guides: PHASE-1A.md through PHASE-4-5.md

## Part B: Planned (Design Approved, Not Yet Implemented)

### B1. Pull Performance: Remove Email Filter

Problem: Bridge sends all known emails in POST /api/v1/admin/pending body.
  1000 addresses = 30KB JSON per poll, SQLite 999 param limit.

Solution: Bridge pulls all pending for system_id, filters locally with router.lookup().

Changes:
  bridge pull.rs: remove emails array from fetch_pending body
  bridge pull.rs: filter deliveries by router.lookup(email) before forwarding
  gateway: no changes (emails parameter is already Optional)

### B2. Category/domain_addr Contract

Final model:

| category | domain_addr | Role | quota counted | require_domain_match |
|----------|-------------|------|--------------|---------------------|
| "platform" | "" | Platform admin | no | system_id="admin" bypass |
| "system" | bare domain | Domain admin | no | match target bare domain |
| "agent" | email | Agent | yes | exact email match |
| "bridge" | "bridge.{uuid}" | Bridge instance | no | not applicable |

Creation validation (POST /api/v1/api-keys):
  "platform": domain_addr must be empty
  "system": domain_addr must NOT contain '@' (bare domain)
  "agent": domain_addr MUST contain '@' (email)
  "bridge": domain_addr arbitrary (recommend "bridge.{uuid}")

Quota count:
  SELECT COUNT(*) FROM api_keys WHERE system_id = ?1 AND category = 'agent'

Bonus fix: SystemAdmin list_api_keys filters by category="agent" but no keys
currently have that category (all are "system"). Adding "agent" fixes this.

### B3. require_domain_match Extension

Add bare domain matching layer:

```rust
if !key.email_address.contains('@') {
    let target_domain = target_email.rsplit('@').next().unwrap_or("");
    if key.email_address == target_domain {
        return Ok(());
    }
}
```

Priority: admin system_id > email_address="" > bare domain match > exact email match

### B4. Bridge Independent API Keys

Goal: Each bridge gets its own bridge-scope API key instead of sharing admin_key.

Changes:
  integrate.sh: POST /api/v1/api-keys with {scopes:["bridge"], category:"bridge", domain_addr:"bridge.{uuid}"}
  bridge config.rs: PullConfig add api_key field (alongside admin_key for backward compat)
  bridge pull.rs: X-Api-Key: state.config.pull.api_key
  gateway: no changes (pending/ack already accept bridge scope)

## Implementation Order

| Phase | Content | Risk |
|-------|---------|------|
| A1-A3 | Core refactor (done) | — |
| A4 | integrate.sh merge (done) | — |
| A5 | Pending TTL (done) | — |
| B1 | Pull perf — remove email filter | low (bridge 5 lines) |
| B2 | Category contract + quota fix + creation validation | medium (~30 lines) |
| B3 | Domain-level admin matching | low (auth.rs ~8 lines) |
| B4 | Bridge independent keys | medium (integrate.sh + bridge) |

## Cross-Platform

- Rust crates (bridge, gateway, advanced): compile on Linux/macOS/Windows
- notify crate dispatches to platform-native file watcher
- Python agent: pure stdlib, cross-platform
- integrate.sh: requires bash (Linux/macOS/WSL)
