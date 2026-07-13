# API Dependencies Index

## Open

| Endpoint | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/health` | GET | Health check | `integrate.sh`, `scripts/check_status.py`, `scripts/hermes_gateway.sh` |
| `/api/v1/activate-system` | POST | Product code activation | `scripts/activate_system.py`, `tools/agentmail_tools.py` |
| `/api/v1/activate-address` | POST | Activation code → API key | `tools/agentmail_tools.py` |

## Shared

| Endpoint | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/whoami` | GET | Verify API key identity & scopes | `scripts/deploy_bridge.py`, `scripts/check_status.py`, `integrate.sh` |
| `/api/v1/key/rotate` | POST | Rotate own key | `tools/agentmail_tools.py` |

## Agent

Identity from key, scoped to self.

| Endpoint | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/send` | POST | Send email | `tools/agentmail_tools.py` |
| `/api/v1/upload` | POST | Upload attachment | `tools/agentmail_tools.py` |
| `/api/v1/attachments/:id` | GET | Download attachment | `tools/agentmail_tools.py` |
| `/api/v1/pending` | GET | Pull own pending emails | `tools/agentmail_tools.py` (planned) |
| `/api/v1/stats/agent/me` | GET | Self statistics | `scripts/send_welcome.py` (planned) |
| `/api/v1/agent-state/:key` | GET/PUT | Agent KV storage | `tools/agentmail_tools.py` |
| `/api/v1/contacts/:address` | GET/PUT | Contact profile CRUD | `tools/agentmail_tools.py` |
| `/api/v1/contacts?name=` | GET | Search contacts by name | `tools/agentmail_tools.py` |
| `/api/v1/thread-summary/:message_id` | GET/PUT | Email thread summary | `tools/agentmail_tools.py` |
| `/api/v1/whitelists` | GET/POST | List/create whitelist | `tools/agentmail_tools.py` |
| `/api/v1/whitelists/check?...` | GET | Whitelist lookup | `tools/agentmail_tools.py` |
| `/api/v1/whitelists/:id` | PUT/DELETE | Update/delete whitelist (agent: own only; admin: any) | `tools/agentmail_tools.py` |

## Admin

Pass target email when operating on others. Scope checked via `require_domain_match`.

| Endpoint | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/whitelists` | GET/POST | Manage whitelist (agent_admin scope, with email param) | `tools/agentmail_tools.py` |
| `/api/v1/admin/api-keys?email=` | GET | Lookup API key by email | `tools/agentmail_tools.py` |
| `/api/v1/admin/api-keys` | POST | Create API key | `scripts/deploy_bridge.py` |
| `/api/v1/admin/api-keys/:id` | DELETE | Delete any key | `tools/agentmail_tools.py` |
| `/api/v1/admin/systems/:sid/domains` | GET/POST | System domain CRUD | `scripts/list_domains.py`, `integrate.sh`, `tools/agentmail_tools.py` |
| `/api/v1/admin/systems/:sid/addresses` | POST | Register agent email address | `tools/agentmail_tools.py` |
| `/api/v1/admin/system-domains/:id` | PUT | Update domain settings | `tools/agentmail_tools.py` |
| `/api/v1/admin/domains/check?domain=` | GET | Check domain uniqueness | `scripts/helpers.sh` |
| `/api/v1/admin/agent-meta/:email` | PUT | Update agent metadata | Gateway admin |
| `/api/v1/admin/pending` | POST | Bridge push pending emails | `scripts/check_status.py` |
| `/api/v1/admin/probe-webhook` | POST | Probe webhook reachability | `integrate.sh` |

## Bridge

| Endpoint | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/routes` | POST | Register agent inbound route | `scripts/hermes_gateway.sh` |

## Board

Auth: `Authorization: Bearer <board_token>`（来自 `notify_invite`).

| Endpoint | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/board/:id/tasks` | GET | List board tasks | `tools/agentmail_board.py` |
| `/api/v1/board/:id/task/:tid` | GET | Get task details | `tools/agentmail_board.py` |
| `/api/v1/board/:id/members` | GET | List board members | `tools/agentmail_board.py` |
| `/api/v1/board/:id/roles` | GET | List role permissions | `tools/agentmail_board.py` |
| `/api/v1/board/:id/status` | GET | Board pipeline + dependencies | `tools/agentmail_board.py` |
| `/api/v1/board/:id/task/:tid/heartbeat` | POST | Task heartbeat (Ready→Running) | `tools/agentmail_board.py` |
