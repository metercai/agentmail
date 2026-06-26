# API 依赖索引

集成脚本及 `amail_tools.py` 对 amail-gateway / amail-bridge 的所有接口调用。

**图例：** 🟢 GET · 🔵 POST/PUT/DELETE

---

## amail-gateway

### 🟢 `GET /api/v1/whoami`
验证 API key 的身份和权限范围。

| 调用方 | 用途 |
|--------|------|
| `lib/deploy_bridge.py:16` | 创建 bridge key 前验证 admin key |
| `lib/check_status.py:254` | Level 1 管道检查 |
| `integrate.sh:110` | 复用已存储的 key（Step 1） |
| `integrate.sh:173` | 验证新输入的 admin key（Step 1） |

### 🟢 `GET /api/v1/health`
健康检查。

| 调用方 | 用途 |
|--------|------|
| `integrate.sh:68,83,85` | 检测并验证网关连通性（Step 1） |
| `lib/check_status.py:224` | Level 1.1 健康检查 |
| `lib/hermes_gateway.sh:35,78` | 轮询 Hermes 网关就绪 |

### 🔵 `POST /api/v1/activate-system`
产品码激活系统（无需认证）。

| 调用方 | 用途 |
|--------|------|
| `lib/activate_system.py:32` | 交互式系统激活（Step 2 product code 路径） |
| `tools/amail_tools.py:368` | `_GatewayClient.activate_system()` |

### 🔵 `POST /api/v1/activate-address`
地址激活码兑换 API key（无需认证）。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:395` | `activate_address()` — profile 自动激活 |

### 🔵 `POST /api/v1/api-keys`
创建 API key。

| 调用方 | 用途 |
|--------|------|
| `lib/deploy_bridge.py:30` | 创建 bridge 用的 agent key |

### 🟢 `GET /api/v1/api-keys`
列出 API key。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:1883` | 按 email 查找 key ID 以便删除 |

### 🔵 `DELETE /api/v1/api-keys/{id}`
删除 API key。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:1890` | profile 删除时清理 key |

### 🟢 `GET /api/v1/admin/systems/{sid}/domains`
列出系统的域名。

| 调用方 | 用途 |
|--------|------|
| `lib/list_domains.py:10` | 域名选择菜单（Step 2） |
| `integrate.sh:208,213` | 查询已有域名 |
| `lib/send_welcome.py:73` | 查找默认 agent email |
| `tools/amail_tools.py:1562` | 按 email 查找 domain ID 更新 webhook |

### 🔵 `POST /api/v1/admin/systems/{sid}/domains`
创建域名记录。

| 调用方 | 用途 |
|--------|------|
| `integrate.sh:260` | 确保域名已创建（Step 2） |

### 🔵 `POST /api/v1/admin/systems/{sid}/addresses`
注册 agent 邮件地址。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:286` | `register_email()` — 注册 agent 收件地址 |

### 🔵 `PUT /api/v1/admin/system-domains/{id}`
更新域名设置。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:1574` | 重新注册时更新 webhook 配置 |

### 🟢 `GET /api/v1/admin/domains/check?domain=...`
检查域名全局唯一性。

| 调用方 | 用途 |
|--------|------|
| `lib/helpers.sh:62` | `domain_exists_globally()` |

### 🟢 `GET /api/v1/admin/whitelists?domain_addr=...`
列出/检查白名单。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:196` | `check_whitelist()` |
| `tools/amail_tools.py:1011,1068` | `manage_contacts()` — 查找 entry_id |

### 🔵 `POST /api/v1/admin/whitelists`
创建白名单条目。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:205` | `add_whitelist()` — 注册 agent 时自动白名单 manager |

### 🔵 `DELETE /api/v1/admin/whitelists/{id}`
按 ID 删除白名单。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:219` | `delete_whitelist()` |

### 🔵 `PUT /api/v1/admin/whitelists/{id}`
更新白名单条目。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:1077` | 更新 direction |

### 🔵 `DELETE /api/v1/admin/whitelists?domain_addr=...&value=...`
按组合键删除白名单。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:1051` | `manage_contacts("remove")` |

### 🟢 `GET /api/v1/admin/activation-codes?...`
（仅测试使用，已删除）

### 🔵 `POST /api/v1/admin/activation-codes/batch`
批量生成激活码。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:344` | `generate_address_codes()` |

### 🔵 `POST /api/v1/send`
发送邮件。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:147` | `send_mail()` — 核心发件方法 |

### 🔵 `POST /api/v1/upload`
上传附件。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:164` | `upload_attachment()` |

### 🟢 `GET /api/v1/stats/agent/me?email=...`
Agent 自身统计数据。

| 调用方 | 用途 |
|--------|------|
| `lib/send_welcome.py:182,202` | 轮询检测欢迎邮件投递状态 |

### 🔵 `POST /api/v1/admin/pending`
Bridge 拉取待投递邮件。

| 调用方 | 用途 |
|--------|------|
| `lib/check_status.py:418` | 验证 bridge ↔ gateway 拉取通路 |

### 🟢 `GET /api/v1/admin/agent-state/{key}`
读取 agent KV 存储。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:225` | `agent_state_get()` |

### 🔵 `PUT /api/v1/admin/agent-state/{key}`
写入 agent KV 存储。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:232` | `agent_state_put()` |

### 🔵 `DELETE /api/v1/admin/agent-state/{key}`
删除 agent KV 存储。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:236` | `agent_state_delete()` |

### 🔵 `PUT /api/v1/admin/contacts/{address}`
写入联系人资料。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:242` | `put_contact()` |

### 🟢 `GET /api/v1/admin/contacts/{address}`
查询联系人资料。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:247` | `get_contact()` |

### 🟢 `GET /api/v1/admin/contacts?name=...`
按姓名搜索联系人。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:254` | `get_contacts_by_name()` |

### 🔵 `PUT /api/v1/admin/thread-summary/{message_id}`
更新邮件线程摘要。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:260` | `put_thread_summary()` |

### 🟢 `GET /api/v1/admin/thread-summary/{message_id}`
读取邮件线程摘要。

| 调用方 | 用途 |
|--------|------|
| `tools/amail_tools.py:266` | `get_thread_summary()` |

---

## amail-bridge

### 🔵 `POST /api/v1/routes`
注册 agent profile 的入站路由。

| 调用方 | 用途 |
|--------|------|
| `lib/hermes_gateway.sh:168` | 启动网关时向 bridge 注册每个 profile 的路由 |

---

## 汇总

| 目标 | 接口数 | 调用点 |
|------|--------|--------|
| amail-gateway | 32 个 | ~70 处 |
| amail-bridge | 1 个 | 1 处 |
| 最大客户端 | `tools/amail_tools.py` | 15+ 个端点封装 |

所有 `_GatewayClient` 调用统一通过 `_request()` 方法（`amail_tools.py:61`），自动添加 `X-Api-Key` 和 `Content-Type` 头。
