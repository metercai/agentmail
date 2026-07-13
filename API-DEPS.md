# API Dependencies Index

All API calls from integration scripts and agentmail_tools.py to amail-gateway / amail-bridge.

**Legend:** GET / POST/PUT/DELETE

---

## amail-gateway

### GET /api/v1/whoami
Verify API key identity and permission scopes.

| Caller | Purpose |
|--------|---------|
| `scripts/deploy_bridge.py` | Verify admin key before creating bridge key |
| `scripts/check_status.py` | Level 1 pipeline check |
| `integrate.sh` | Reuse/verify admin key (Step 1) |

### GET /api/v1/health
Health check.

| Caller | Purpose |
|--------|---------|
| `integrate.sh` | Detect and verify gateway connectivity (Step 1) |
| `scripts/check_status.py` | Level 1.1 health check |
| `scripts/hermes_gateway.sh` | Poll Hermes gateway readiness |

### POST /api/v1/activate-system
Product code activation (no auth required).

| Caller | Purpose |
|--------|---------|
| `scripts/activate_system.py` | Interactive system activation (Step 2 product code path) |
| `tools/agentmail_tools.py` | `_GatewayClient.activate_system()` |

### POST /api/v1/activate-address
Address activation code to API key exchange (no auth required).

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `activate_address()` — auto-activate profiles |

### POST /api/v1/api-keys
Create API key.

| Caller | Purpose |
|--------|---------|
| `scripts/deploy_bridge.py` | Create agent key for bridge |

### GET /api/v1/api-keys
List API keys.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `list_api_keys()` — find key ID by email |

### DELETE /api/v1/api-keys/{id}
Delete API key.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `delete_api_key()` — clean up key on profile deletion |

### GET /api/v1/admin/systems/{sid}/domains
List system domains.

| Caller | Purpose |
|--------|---------|
| `scripts/list_domains.py` | Domain selection menu (Step 2) |
| `integrate.sh` | Query existing domains |
| `scripts/send_welcome.py` | Find default agent email |
| `tools/agentmail_tools.py` | `list_system_domains()` — find domain ID by email |

### POST /api/v1/admin/systems/{sid}/domains
Create domain record.

| Caller | Purpose |
|--------|---------|
| `integrate.sh` | Ensure domain created (Step 2) |

### POST /api/v1/admin/systems/{sid}/addresses
Register agent email address.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `register_email()` — register agent inbox address |

### PUT /api/v1/admin/system-domains/{id}
Update domain settings.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `update_system_domain()` — update webhook config |

### GET /api/v1/admin/domains/check?domain=...
Check global domain uniqueness.

| Caller | Purpose |
|--------|---------|
| `scripts/helpers.sh` | `domain_exists_globally()` |

### GET /api/v1/admin/whitelists/check?domain_addr=...&value=...&direction=...
Exact whitelist lookup (no information leak).

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `check_whitelist_value()` — `manage_contacts("check")` |

### POST /api/v1/admin/whitelists
Create whitelist entry.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `add_whitelist()` — auto-whitelist manager on agent registration |

### PUT /api/v1/admin/whitelists?domain_addr=...&value=...
Update whitelist direction by composite key.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `update_whitelist_by_value()` — `manage_contacts("update")` |

### DELETE /api/v1/admin/whitelists?domain_addr=...&value=...
Delete whitelist by composite key.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `delete_whitelist_by_value()` — `manage_contacts("remove")` |

### POST /api/v1/send
Send email.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `send_mail()` — core outbound method |

### POST /api/v1/upload
Upload attachment.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `upload_attachment()` |

### GET /api/v1/stats/agent/me?email=...
Agent self statistics.

| Caller | Purpose |
|--------|---------|
| `scripts/send_welcome.py` | Poll welcome email delivery status |

### POST /api/v1/admin/pending
Bridge pulls pending emails.

| Caller | Purpose |
|--------|---------|
| `scripts/check_status.py` | Verify bridge-to-gateway pull path |

### GET /api/v1/admin/agent-state/{key}
Read agent KV storage.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `agent_state_get()` |

### PUT /api/v1/admin/agent-state/{key}
Write agent KV storage.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `agent_state_put()` — public_whoami, msg metadata |

### PUT /api/v1/admin/contacts/{address}
Write contact profile.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `put_contact()` |

### GET /api/v1/admin/contacts/{address}
Read contact profile.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `get_contact()` |

### GET /api/v1/admin/contacts?name=...
Search contacts by name.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `get_contacts_by_name()` |

### PUT /api/v1/admin/thread-summary/{message_id}
Update email thread summary.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `put_thread_summary()` |

### GET /api/v1/admin/thread-summary/{message_id}
Read email thread summary.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_tools.py` | `get_thread_summary()` |

### A2A Board APIs

Authenticated via `Authorization: Bearer bdt_...` (board token from `notify_invite`).
First call to `heartbeat` transitions task Ready→Running.

### GET /api/v1/board/:id/tasks
List board tasks.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_board.py` | `board_task_list()` |

### GET /api/v1/board/:id/task/:tid
Get task details.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_board.py` | `board_task_show()` |

### GET /api/v1/board/:id/members
List board members.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_board.py` | `board_members()` |

### GET /api/v1/board/:id/roles
List role permissions.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_board.py` | `board_roles()` |

### GET /api/v1/board/:id/status
Board pipeline overview with dependencies.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_board.py` | `board_status()` |

### POST /api/v1/board/:id/task/:tid/heartbeat
Update task heartbeat.

| Caller | Purpose |
|--------|---------|
| `tools/agentmail_board.py` | `board_heartbeat()` |

---

## amail-bridge

### POST /api/v1/routes
Register agent profile inbound route.

| Caller | Purpose |
|--------|---------|
| `scripts/hermes_gateway.sh` | Register each profile route on bridge at gateway startup |

---

## Summary

| Target | Endpoints | Callers |
|--------|-----------|---------|
| amail-gateway | 26 + 6 board | ~65 sites |
| amail-bridge | 1 | 1 site |
| Max client | `tools/agentmail_tools.py` | All via `_GatewayClient` wrapper |

All API calls go through `_GatewayClient` named wrapper methods, using `_request()` (auto-adds `X-Api-Key` and `Content-Type` headers).
