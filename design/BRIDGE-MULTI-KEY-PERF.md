# Bridge Security and Performance Plan (Final)

## 0. Done: pending TTL

pending_ttl_hours (default 72h) added to WebhookConfig, scheduler cleanup.

## 1. Quota Fix: category="agent"

### 1.1 Current State

| key type | category | system_id | counts toward max_addresses |
|----------|----------|-----------|---------------------------|
| admin | "platform" | "admin" | no (different system_id) |
| agent | "system" (default) | "base-xxx" | yes |
| domain admin | "system" (default) | "base-xxx" | yes |
| future bridge | "system" (default) | "base-xxx" | yes |

Problem: all share same category, no way to distinguish for quota.

### 1.2 Target State

| key type | category | quota counted |
|----------|----------|--------------|
| admin | "platform" | no |
| agent | "agent" | yes |
| domain admin | "system" | yes |
| bridge | "bridge" | no |

### 1.3 Changes

agent key creation: set category="agent" instead of default "system"

files:
  amail_tools.py _auto_register_email: add category="agent" to register body
  OR gateway activation.rs: set category="agent" during activate_address_handler

quota counter:
  advanced/storage.rs count_api_keys_by_system_id:
    SELECT COUNT(*) FROM api_keys WHERE system_id = ?1 AND category = 'agent'

bonus: fixes pre-existing bug where SystemAdmin list_api_keys filters
by category="agent" but no keys have that category -- returns empty list.

## 2. Bridge Security: Independent API Keys

### 2.1 Current

All bridges share admin_key with system scope.
One leak compromises all bridges.

### 2.2 Target

Each bridge gets its own bridge-scope API key.

```
system_id = base-xxx
  bridge-A: api_key_001 (scope: bridge, category: bridge)
  bridge-B: api_key_002 (scope: bridge, category: bridge)
  agent-alice: api_key_xxx (scope: agent, category: agent)
```

### 2.3 Changes

integrate.sh:
  after bridge deploy, POST /api/v1/api-keys with:
    { system_id, domain_addr: "bridge-{uuid}", scopes: ["bridge"], category: "bridge" }
  write api_key to amail_bridge.toml [pull] api_key field

bridge config.rs:
  PullConfig: rename admin_key -> api_key (or add api_key alongside)

bridge pull.rs:
  header: X-Api-Key: state.config.pull.api_key

gateway: no changes (pending/ack already accept bridge scope)

## 3. Pull Performance: Remove Email Filter

### 3.1 Current

POST /api/v1/admin/pending {"limit": 50, "emails": [1000 addresses]}
Problem: 30KB JSON per poll, SQLite 999 param limit.

### 3.2 Target

POST /api/v1/admin/pending {"limit": 50}
Bridge pulls all pending for system_id, filters locally with router.lookup().
Unmatched deliveries stay pending, cleaned by TTL.

### 3.3 Changes

bridge pull.rs fetch_pending:
  remove emails array from request body

bridge pull.rs process_batch:
  after fetch, filter each delivery by router.lookup(email)
  only forward/ACK matched deliveries

gateway http.rs list_pending_deliveries:
  accept request without emails field (already works -- emails is Optional)

## 4. Implementation Order

Phase 1: Pull performance (remove email filter)
  - bridge: 5 lines
  - gateway: 0 lines (already Optional)

Phase 2: Quota fix + category="agent"
  - gateway activation: set category="agent"
  - advanced quota: filter category='agent'
  - amail_tools.py: add category param
  - test: SystemAdmin list_api_keys now returns keys

Phase 3: Bridge independent keys
  - integrate.sh: create bridge-scope key
  - bridge config: api_key field
  - integration test
