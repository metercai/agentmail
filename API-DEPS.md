# API 依赖索引

集成脚本及 `agentmail_tools.py` 对 amail-gateway / amail-bridge 的所有接口调用。

**图例：** 🟢 GET · 🔵 POST/PUT/DELETE

---

## amail-gateway

### 🟢 `GET /api/v1/whoami`
验证 API key 的身份和权限范围。

| 调用方 | 用途 |
|--------|------|
| `lib/deploy_bridge.py` | 创建 bridge key 前验证 admin key |
| `lib/check_status.py` | Level 1 管道检查 |
| `integrate.sh` | 复用/验证 admin key（Step 1） |

### 🟢 `GET /api/v1/health`
健康检查。

| 调用方 | 用途 |
|--------|------|
| `integrate.sh` | 检测并验证网关连通性（Step 1） |
| `lib/check_status.py` | Level 1.1 健康检查 |
| `lib/hermes_gateway.sh` | 轮询 Hermes 网关就绪 |

### 🔵 `POST /api/v1/activate-system`
产品码激活系统（无需认证）。

| 调用方 | 用途 |
|--------|------|
| `lib/activate_system.py` | 交互式系统激活（Step 2 product code 路径） |
| `tools/agentmail_tools.py` | `_GatewayClient.activate_system()` |

### 🔵 `POST /api/v1/activate-address`
地址激活码兑换 API key（无需认证）。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `activate_address()` — profile 自动激活 |

### 🔵 `POST /api/v1/api-keys`
创建 API key。

| 调用方 | 用途 |
|--------|------|
| `lib/deploy_bridge.py` | 创建 bridge 用的 agent key |

### 🟢 `GET /api/v1/api-keys`
列出 API key。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `list_api_keys()` — 按 email 查找 key ID |

### 🔵 `DELETE /api/v1/api-keys/{id}`
删除 API key。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `delete_api_key()` — profile 删除时清理 key |

### 🟢 `GET /api/v1/admin/systems/{sid}/domains`
列出系统的域名。

| 调用方 | 用途 |
|--------|------|
| `lib/list_domains.py` | 域名选择菜单（Step 2） |
| `integrate.sh` | 查询已有域名 |
| `lib/send_welcome.py` | 查找默认 agent email |
| `tools/agentmail_tools.py` | `list_system_domains()` — 按 email 找 domain ID |

### 🔵 `POST /api/v1/admin/systems/{sid}/domains`
创建域名记录。

| 调用方 | 用途 |
|--------|------|
| `integrate.sh` | 确保域名已创建（Step 2） |

### 🔵 `POST /api/v1/admin/systems/{sid}/addresses`
注册 agent 邮件地址。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `register_email()` — 注册 agent 收件地址 |

### 🔵 `PUT /api/v1/admin/system-domains/{id}`
更新域名设置。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `update_system_domain()` — 更新 webhook 配置 |

### 🟢 `GET /api/v1/admin/domains/check?domain=...`
检查域名全局唯一性。

| 调用方 | 用途 |
|--------|------|
| `lib/helpers.sh` | `domain_exists_globally()` |

### 🟢 `GET /api/v1/admin/whitelists/check?domain_addr=...&value=...&direction=...`
精确查询单条白名单（无信息泄漏）。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `check_whitelist_value()` — `manage_contacts("check")` |

### 🔵 `POST /api/v1/admin/whitelists`
创建白名单条目。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `add_whitelist()` — 注册 agent 时自动白名单 manager |

### 🔵 `PUT /api/v1/admin/whitelists?domain_addr=...&value=...`
按组合键更新白名单 direction。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `update_whitelist_by_value()` — `manage_contacts("update")` |

### 🔵 `DELETE /api/v1/admin/whitelists?domain_addr=...&value=...`
按组合键删除白名单。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `delete_whitelist_by_value()` — `manage_contacts("remove")` |

### 🔵 `POST /api/v1/send`
发送邮件。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `send_mail()` — 核心发件方法 |

### 🔵 `POST /api/v1/upload`
上传附件。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `upload_attachment()` |

### 🟢 `GET /api/v1/stats/agent/me?email=...`
Agent 自身统计数据。

| 调用方 | 用途 |
|--------|------|
| `lib/send_welcome.py` | 轮询检测欢迎邮件投递状态 |

### 🔵 `POST /api/v1/admin/pending`
Bridge 拉取待投递邮件。

| 调用方 | 用途 |
|--------|------|
| `lib/check_status.py` | 验证 bridge ↔ gateway 拉取通路 |

### 🟢 `GET /api/v1/admin/agent-state/{key}`
读取 agent KV 存储。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `agent_state_get()` |

### 🔵 `PUT /api/v1/admin/agent-state/{key}`
写入 agent KV 存储。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `agent_state_put()` |

### 🔵 `PUT /api/v1/admin/contacts/{address}`
写入联系人资料。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `put_contact()` |

### 🟢 `GET /api/v1/admin/contacts/{address}`
查询联系人资料。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `get_contact()` |

### 🟢 `GET /api/v1/admin/contacts?name=...`
按姓名搜索联系人。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `get_contacts_by_name()` |

### 🔵 `PUT /api/v1/admin/thread-summary/{message_id}`
更新邮件线程摘要。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `put_thread_summary()` |

### 🟢 `GET /api/v1/admin/thread-summary/{message_id}`
读取邮件线程摘要。

| 调用方 | 用途 |
|--------|------|
| `tools/agentmail_tools.py` | `get_thread_summary()` |

---

## amail-bridge

### 🔵 `POST /api/v1/routes`
注册 agent profile 的入站路由。

| 调用方 | 用途 |
|--------|------|
| `lib/hermes_gateway.sh` | 启动网关时向 bridge 注册每个 profile 的路由 |

---

## 汇总

| 目标 | 接口数 | 调用点 |
|------|--------|--------|
| amail-gateway | 26 个 | ~60 处 |
| amail-bridge | 1 个 | 1 处 |
| 最大客户端 | `tools/agentmail_tools.py` | 全部走 `_GatewayClient` 封装 |

所有 API 调用均通过 `_GatewayClient` 命名包装方法，统一使用 `_request()`（自动添加 `X-Api-Key` 和 `Content-Type` 头）。
