# API Dependencies Index

## 1. Open — no auth

| Endpoint | Method | Purpose | Callers |
|----------|--------|---------|---------|
| `/api/v1/health` | GET | Health check | `integrate.sh`, `scripts/check_status.py`, `scripts/hermes_gateway.sh` |
| `/api/v1/activate-system` | POST | Product code activation | `scripts/activate_system.py`, `tools/agentmail_tools.py` |
| `/api/v1/activate-address` | POST | Activation code → API key | `tools/agentmail_tools.py` |

## 2. Shared — any API key

| Endpoint | Method | Purpose | Callers |
|----------|--------|---------|---------|
| `/api/v1/whoami` | GET | Verify API key identity & scopes | `scripts/deploy_bridge.py`, `scripts/check_status.py`, `integrate.sh` |

## 3. Agent — agent scope（部分允许 admin 管理）

| Endpoint | Method | Purpose | Callers |
|----------|--------|---------|---------|
| `/api/v1/send` | POST | Send email | `tools/agentmail_tools.py` |
| `/api/v1/upload` | POST | Upload attachment | `tools/agentmail_tools.py` |
| `/api/v1/attachments/:id` | GET | Download attachment | `tools/agentmail_tools.py` |
| `/api/v1/admin/agent-state/{key}` | GET/PUT | Read/write agent KV storage | `tools/agentmail_tools.py` |
| `/api/v1/admin/contacts/{address}` | GET/PUT | Read/write contact profile | `tools/agentmail_tools.py` |
| `/api/v1/admin/contacts?name=` | GET | Search contacts by name | `tools/agentmail_tools.py` |
| `/api/v1/admin/thread-summary/{message_id}` | GET/PUT | Read/update thread summary | `tools/agentmail_tools.py` |
| `/api/v1/admin/whitelists` | GET/POST | List/create whitelist | `tools/agentmail_tools.py` |
| `/api/v1/admin/whitelists/check?...` | GET | Whitelist lookup | `tools/agentmail_tools.py` |
| `/api/v1/admin/whitelists?...` | PUT/DELETE | Update/delete whitelist | `tools/agentmail_tools.py` |

## 4. Admin — system / platform scope

| Endpoint | Method | Purpose | Callers |
|----------|--------|---------|---------|
| `/api/v1/api-keys?email=` | GET | Lookup API key by email | `tools/agentmail_tools.py` |
| `/api/v1/api-keys` | POST | Create API key | `scripts/deploy_bridge.py` |
| `/api/v1/api-keys/{id}` | DELETE | Delete API key | `tools/agentmail_tools.py` |
| `/api/v1/stats/agent/me?email=` | GET | Agent self statistics | `scripts/send_welcome.py` |
| `/api/v1/admin/pending` | POST | Bridge pulls pending emails | `scripts/check_status.py` |
| `/api/v1/admin/systems/{sid}/domains` | GET/POST | List/create system domains | `scripts/list_domains.py`, `integrate.sh`, `tools/agentmail_tools.py` |
| `/api/v1/admin/systems/{sid}/addresses` | POST | Register agent email address | `tools/agentmail_tools.py` |
| `/api/v1/admin/system-domains/{id}` | PUT | Update domain settings | `tools/agentmail_tools.py` |
| `/api/v1/admin/domains/check?domain=` | GET | Check domain uniqueness | `scripts/helpers.sh` |

## 5. Board Token

Auth: `Authorization: Bearer *** (from `notify_invite`).
First `POST heartbeat` transitions task Ready→Running.

| Endpoint | Method | Purpose | Callers |
|----------|--------|---------|---------|
| `/api/v1/board/:id/tasks` | GET | List board tasks | `tools/agentmail_board.py` |
| `/api/v1/board/:id/task/:tid` | GET | Get task details | `tools/agentmail_board.py` |
| `/api/v1/board/:id/members` | GET | List board members | `tools/agentmail_board.py` |
| `/api/v1/board/:id/roles` | GET | List role permissions | `tools/agentmail_board.py` |
| `/api/v1/board/:id/status` | GET | Board pipeline + dependencies | `tools/agentmail_board.py` |
| `/api/v1/board/:id/task/:tid/heartbeat` | POST | Update task heartbeat | `tools/agentmail_board.py` |

## 6. Bridge

| Endpoint | Method | Purpose | Callers |
|----------|--------|---------|---------|
| `/api/v1/routes` | POST | Register agent profile inbound route | `scripts/hermes_gateway.sh` |
