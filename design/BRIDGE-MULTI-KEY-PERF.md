# Bridge Security and Performance Plan

## 1. Multi-Bridge Independent API Keys

Current: all bridges share admin_key with system scope.
Risk: one key leak affects all bridges.

Solution: each bridge gets its own bridge-scope API key.

Before:
  bridge-A admin_key = SYSTEM_ADMIN_KEY (system scope)
  bridge-B admin_key = SYSTEM_ADMIN_KEY (same)

After:
  bridge-A api_key = key_001 (bridge scope)
  bridge-B api_key = key_002 (bridge scope)

Changes needed:
  integrate.sh Step: call POST /api/v1/api-keys { scopes: ["bridge"] }
  write bridge api_key to amail_bridge.toml [pull] api_key field
  gateway: pending/ack endpoints already accept bridge scope

Quota: each bridge key consumes one max_addresses slot.
Mitigation: add per-system max_bridge_keys config or exclude bridge from count.

## 2. Large Email List in Pull Query

Current: bridge sends all known emails in POST /api/v1/admin/pending body.
Problem: 1000 addresses = 30KB JSON per poll, SQLite 999 param limit.

Option A: Domain filter
  bridge extracts unique domains from routes: dom1.com, dom2.com
  sends domains list instead of emails
  gateway: WHERE domain_addr LIKE '%@dom1.com' OR domain_addr LIKE '%@dom2.com'
  pro: short param list, scales to any route count
  con: LIKE queries are slower than IN, needs index

Option B: Remove filter entirely
  bridge pulls all pending for system_id, filters locally by router.lookup()
  unmatched deliveries stay pending, cleaned by TTL
  pro: minimal gateway changes, no SQL limit
  con: repeated wasted polls for unmatched deliveries

Option C: Cursor-based pagination
  bridge stores last_poll_id, gateway returns pending WHERE id > last_poll_id
  bridge ACKs only matched deliveries
  pro: no filter params at all
  con: requires tracking cursor state per bridge

Recommendation: Option A for scale; Option B as simpler first pass.

## 3. Implementation Order

Phase 1: Option B (remove email filter)
  gateway: accept pending request without emails param
  bridge: remove emails from fetch_pending body
  router: filter pending deliveries locally before forwarding
  cleanup: TTL handles stale pending deliveries

Phase 2: Independent bridge keys
  integrate.sh: create bridge-scope key during Step (merged Step 4)
  gateway: bridge scope quota exemption or separate quota
  bridge: api_key in config instead of admin_key

Phase 3: Option A domain filter (if needed after Phase 1 testing)
  bridge: extract domains from route table
  gateway: domain filter SQL
