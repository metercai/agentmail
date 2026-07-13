# API 权限矩阵

## Open

| 端点 | Method |
|------|--------|
| `/api/v1/health` | GET |
| `/api/v1/activate-system` | POST |
| `/api/v1/activate-address` | POST |

## Shared

| 端点 | Method |
|------|--------|
| `/api/v1/whoami` | GET |

## Agent（含 agent_admin）

身份从 key 的 `email_address` 自动获取，无需传参。

| 端点 | Method |
|------|--------|
| `/api/v1/send` | POST |
| `/api/v1/upload` | POST |
| `/api/v1/attachments/:id` | GET |
| `/api/v1/pending` | GET |
| `/api/v1/stats/agent/me` | GET |
| `/api/v1/agent-state/:key` | GET/PUT |
| `/api/v1/contacts/:address` | GET/PUT |
| `/api/v1/contacts?name=` | GET |
| `/api/v1/thread-summary/:message_id` | GET/PUT |
| `/api/v1/whitelists` | GET/POST |
| `/api/v1/whitelists/check?...` | GET |
| `/api/v1/whitelists/:id` | PUT/DELETE |

## Admin（system / platform）

| 端点 | Method |
|------|--------|
| `/api/v1/api-keys?email=` | GET |
| `/api/v1/api-keys` | POST |
| `/api/v1/api-keys/:id` | PUT/DELETE |
| `/api/v1/admin/systems/:sid/domains` | GET/POST |
| `/api/v1/admin/systems/:sid/addresses` | POST |
| `/api/v1/admin/system-domains/:id` | PUT |
| `/api/v1/admin/domains/check?domain=` | GET |
| `/api/v1/admin/agent-meta/:email` | PUT |
| `/api/v1/admin/pending` | POST |
| `/api/v1/admin/probe-webhook` | POST |

## Bridge

| 端点 | Method |
|------|--------|
| `/api/v1/routes` | POST |

## Board

Auth: `Authorization: Bearer <board...n
| 端点 | Method |
|------|--------|
| `/api/v1/board/:id/tasks` | GET |
| `/api/v1/board/:id/task/:tid` | GET |
| `/api/v1/board/:id/members` | GET |
| `/api/v1/board/:id/roles` | GET |
| `/api/v1/board/:id/status` | GET |
| `/api/v1/board/:id/task/:tid/heartbeat` | POST |
