# API 权限矩阵

## Auth 维度

| 维度 | 控制什么 | 使用位置 |
|------|---------|---------|
| **Scope** | API 操作权限——能不能调这个端点 | 每个端点 `require_scope()` / `require_scope_any()` |
| **Category** | 数据可见性——创建限制 + 列表过滤 + 身份标签 | `create_api_key` 校验，`list_whitelists` 过滤，`whoami` 暴露 |

Scope 取值（5 级）：`platform` > `system` > `agent_admin` > `agent` > `bridge`

Category 取值（6 种）：`platform` / `system` / `domain` / `agent` / `agent_admin` / `bridge`

## 端点 × Scope 矩阵

### Open（无认证）

| 端点 | Method |
|------|--------|
| `/api/v1/health` | GET |
| `/api/v1/activate-system` | POST |
| `/api/v1/activate-address` | POST |

### Shared（任意 Scope）

| 端点 | Method |
|------|--------|
| `/api/v1/whoami` | GET |

### Agent（`agent` scope）

身份从 key 的 `email_address` 自动获取，无需传参。

| 端点 | Method | 说明 |
|------|--------|------|
| `/api/v1/send` | POST | 发邮件 |
| `/api/v1/upload` | POST | 上传附件 |
| `/api/v1/attachments/:id` | GET | 下载附件 |
| `/api/v1/pending` | GET | Agent 拉自己的待收邮件（新增，`?email=` 无需传） |
| `/api/v1/stats/agent/me` | GET | Agent 查自己的统计（新增，无需 `?email=`） |

### Agent + Agent Admin（`agent`, `agent_admin` scope）

Agent 自己的数据，agent_admin 可管理其管辖范围内的 Agent 数据。

| 端点 | Method | 说明 |
|------|--------|------|
| `/api/v1/agent-state/:key` | GET/PUT | Agent KV 状态 |
| `/api/v1/contacts/:address` | GET/PUT | 联系人 |
| `/api/v1/contacts?name=` | GET | 按名搜联系人 |
| `/api/v1/thread-summary/:message_id` | GET/PUT | 邮件线程摘要 |
| `/api/v1/whitelists` | GET/POST | 白名单列表/创建 |
| `/api/v1/whitelists/check?...` | GET | 白名单检查 |
| `/api/v1/whitelists/:id` | PUT/DELETE | 白名单更新/删除 |

### Admin（`system`, `platform` scope）

系统管理操作。

| 端点 | Method | 说明 |
|------|--------|------|
| `/api/v1/api-keys?email=` | GET | 按 email 查 API key |
| `/api/v1/api-keys` | POST | 创建 API key |
| `/api/v1/api-keys/:id` | DELETE | 删除 API key |
| `/api/v1/api-keys/:id` | PUT | 更新/旋转 API key |
| `/api/v1/admin/systems/:sid/domains` | GET/POST | 系统域管理 |
| `/api/v1/admin/systems/:sid/addresses` | POST | 注册 Agent 地址 |
| `/api/v1/admin/system-domains/:id` | PUT | 更新域设置 |
| `/api/v1/admin/domains/check?domain=` | GET | 域唯一性检查 |
| `/api/v1/admin/agent-meta/:email` | PUT | 更新 Agent 元数据 |
| `/api/v1/admin/pending` | POST | Bridge/System 推送待收邮件（body 含邮件数据） |
| `/api/v1/admin/probe-webhook` | POST | 探测 webhook 可达性 |

### Bridge（`bridge` scope）

| 端点 | Method | 说明 |
|------|--------|------|
| `/api/v1/routes` | POST | 注册 Agent 入站路由 |

### Board（`Authorization: Bearer <board_token>`）

| 端点 | Method | 说明 |
|------|--------|------|
| `/api/v1/board/:id/tasks` | GET | 任务列表 |
| `/api/v1/board/:id/task/:tid` | GET | 任务详情 |
| `/api/v1/board/:id/members` | GET | 成员列表 |
| `/api/v1/board/:id/roles` | GET | 角色权限 |
| `/api/v1/board/:id/status` | GET | 看板状态+管线 |
| `/api/v1/board/:id/task/:tid/heartbeat` | POST | 心跳（首次 Ready→Running） |

## 关键差异表

| 端点 | 现 scope | 目标 scope |
|------|---------|-----------|
| agent-state, contacts, thread-summary, whitelists | `agent, agent_admin, system, platform` | `agent, agent_admin` |
| `POST /api/v1/admin/pending` | 无检查 | `system, platform` |
| `GET /api/v1/pending` | 不存在 | `agent`（新增） |
| `GET /api/v1/stats/agent/me` | 不存在 | `agent`（新增） |
