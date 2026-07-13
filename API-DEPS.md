# API Dependencies Index

## Open

| 端点 | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/health` | GET | Health check | `integrate.sh`, `scripts/check_status.py`, `scripts/hermes_gateway.sh` |
| `/api/v1/activate-system` | POST | Product code activation | `scripts/activate_system.py`, `tools/agentmail_tools.py` |
| `/api/v1/activate-address` | POST | Activation code → API key | `tools/agentmail_tools.py` |

## Shared

| 端点 | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/whoami` | GET | Verify API key identity & scopes | `scripts/deploy_bridge.py`, `scripts/check_status.py`, `integrate.sh` |

## Agent（agent scope）

身份从 key 的 `email_address` 自动获取，只能操作自己。

| 端点 | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/send` | POST | Send email | `tools/agentmail_tools.py` |
| `/api/v1/upload` | POST | Upload attachment | `tools/agentmail_tools.py` |
| `/api/v1/attachments/:id` | GET | Download attachment | `tools/agentmail_tools.py` |
| `/api/v1/pending` | GET | Pull own pending emails | `tools/agentmail_tools.py`（待实现） |
| `/api/v1/stats/agent/me` | GET | Self statistics | `scripts/send_welcome.py`（待实现） |
| `/api/v1/agent-state/:key` | GET/PUT | Agent KV storage | `tools/agentmail_tools.py` |
| `/api/v1/contacts/:address` | GET/PUT | Contact profile CRUD | `tools/agentmail_tools.py` |
| `/api/v1/contacts?name=` | GET | Search contacts by name | `tools/agentmail_tools.py` |
| `/api/v1/thread-summary/:message_id` | GET/PUT | Email thread summary | `tools/agentmail_tools.py` |
| `/api/v1/whitelists` | GET/POST | List/create whitelist | `tools/agentmail_tools.py` |
| `/api/v1/whitelists/check?...` | GET | Whitelist lookup | `tools/agentmail_tools.py` |
| `/api/v1/whitelists/:id` | PUT/DELETE | Update/delete whitelist | `tools/agentmail_tools.py` |

## Admin（agent_admin / system / platform）

操作对象非自身时需传 email，由 `require_domain_match` / `require_agent_match` 校验管理范围。

| 端点 | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/admin/whitelists` | GET/POST | 管理 whitelist（按域/系统范围） | `tools/agentmail_tools.py` |
| `/api/v1/admin/whitelists/check?...` | GET | 管理 whitelist 检查 | `tools/agentmail_tools.py` |
| `/api/v1/admin/whitelists/:id` | PUT/DELETE | 管理 whitelist 更新/删除 | `tools/agentmail_tools.py` |
| `/api/v1/api-keys?email=` | GET | Lookup API key by email | `tools/agentmail_tools.py` |
| `/api/v1/api-keys` | POST | Create API key | `scripts/deploy_bridge.py` |
| `/api/v1/api-keys/:id` | PUT/DELETE | Update/rotate/delete API key | `tools/agentmail_tools.py` |
| `/api/v1/admin/systems/:sid/domains` | GET/POST | System domain CRUD | `scripts/list_domains.py`, `integrate.sh`, `tools/agentmail_tools.py` |
| `/api/v1/admin/systems/:sid/addresses` | POST | Register agent email address | `tools/agentmail_tools.py` |
| `/api/v1/admin/system-domains/:id` | PUT | Update domain settings | `tools/agentmail_tools.py` |
| `/api/v1/admin/domains/check?domain=` | GET | Check domain uniqueness | `scripts/helpers.sh` |
| `/api/v1/admin/agent-meta/:email` | PUT | Update agent metadata | Gateway admin |
| `/api/v1/admin/pending` | POST | Bridge push pending emails | `scripts/check_status.py` |
| `/api/v1/admin/probe-webhook` | POST | Probe webhook reachability | `integrate.sh` |

## Bridge

| 端点 | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/routes` | POST | Register agent inbound route | `scripts/hermes_gateway.sh` |

## Board

Auth: `Authorization: Bearer *** 端点 | Method | Purpose | Callers |
|------|--------|---------|---------|
| `/api/v1/board/:id/tasks` | GET | List board tasks | `tools/agentmail_board.py` |
| `/api/v1/board/:id/task/:tid` | GET | Get task details | `tools/agentmail_board.py` |
| `/api/v1/board/:id/members` | GET | List board members | `tools/agentmail_board.py` |
| `/api/v1/board/:id/roles` | GET | List role permissions | `tools/agentmail_board.py` |
| `/api/v1/board/:id/status` | GET | Board pipeline + dependencies | `tools/agentmail_board.py` |
| `/api/v1/board/:id/task/:tid/heartbeat` | POST | Task heartbeat（Ready→Running） | `tools/agentmail_board.py` |
