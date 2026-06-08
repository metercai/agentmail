---
title: amail — 集成接口与流程总览 (Base Edition)
updated: 2026-05-29
---

## 一、所有接口一览

### 公共端点（无需认证）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/activate-address` | 用激活码兑换 API key |

### Agent 端点（scope: `agent` / `send`）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/send` | 发送邮件 |
| POST | `/api/v1/upload` | 上传附件 |
| GET | `/api/v1/attachments/:id` | 下载附件 |
| GET | `/api/v1/whoami` | 验证身份 |

### Admin 端点（scope: `platform` / `system`，admin_key）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/api-keys` | 创建 API key |
| GET | `/api/v1/api-keys` | 列出 API keys |
| GET | `/api/v1/api-keys/:id` | 查看指定 key |
| PUT | `/api/v1/api-keys/:id` | 轮换 key |
| DELETE | `/api/v1/api-keys/:id` | 删除 key |
| POST | `/api/v1/admin/systems/admin/domains` | 注册邮件域名/地址路由 |
| GET | `/api/v1/admin/systems/admin/domains` | 列出域名 |
| PUT | `/api/v1/admin/system-domains/:id` | 更新域名配置 |
| DELETE | `/api/v1/admin/system-domains/:id` | 删除域名 |
| PUT | `/api/v1/admin/agent-meta/:email` | 更新 agent 元数据 |
| POST | `/api/v1/admin/activation-codes/batch` | 批量生成激活码 |

### Admin 端点（scope: `agent`，agent 自己管理自己）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/admin/whitelists` | 添加联系人 |
| GET | `/api/v1/admin/whitelists` | 列出联系人 |
| GET | `/api/v1/admin/whitelists/check` | 检查是否在白名单 |
| PUT | `/api/v1/admin/whitelists/:id` | 修改联系人 |
| DELETE | `/api/v1/admin/whitelists/:id` | 删除联系人 |
| DELETE | `/api/v1/admin/whitelists` | 按参数删除联系人 |

### 语义化端点（scope: `agent`，联系人 + 线程摘要）

| 方法 | 路径 | 用途 |
|------|------|------|
| PUT | `/api/v1/admin/contacts/:address` | 原子写入联系人（含 name 索引、JSON merge） |
| GET | `/api/v1/admin/contacts/:address` | 按地址读联系人 |
| GET | `/api/v1/admin/contacts?name=...` | 按姓名搜索联系人 |
| PUT | `/api/v1/admin/thread-summary/:message_id` | 写入线程摘要（自动解析 thread_id） |
| GET | `/api/v1/admin/thread-summary/:message_id` | 读取线程摘要（自动解析 thread_id） |

### 内部存储端点（agent_state，不直接暴露给 agent）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/admin/agent-state/:key` | 读取 KV |
| PUT | `/api/v1/admin/agent-state/:key` | 写入 KV |
| DELETE | `/api/v1/admin/agent-state/:key` | 删除 KV |

> agent_state 是底层存储引擎。联系人/摘要操作应走语义化端点。agent_state 仅用于消息元数据 `msg:{mid}`（由 `store_inbound_message` 和 `send_mail` 内部使用）。

---

## 二、接入流程

### 2.1 前置条件

1. 启动 amail-relay 服务
2. 从启动日志获取 `admin_key`（双重身份：platform + system）

### 2.2 一键接入

```python
from amail_tools import setup

setup(
    relay_url="http://localhost:38080",
    admin_key="sk-...",
)
```

`setup()` 自动完成：
1. 保存 relay 连接配置到 `~/.hermes/config.yaml`
2. 启用 webhook 平台
3. 生成 HMAC secret
4. 创建 `amail-inbound` webhook 路由
5. 注册 `preprocess_mail_payload` 预处理器

### 2.3 Agent 地址注册

```
POST /api/v1/admin/systems/admin/domains
{
  "domain_addr": "alice@agent.example.com",
  "webhook_url": "http://gateway:8644/webhooks/amail-inbound",
  "webhook_secret": "<HMAC_SECRET>"
}
```

### 2.4 为 Agent 创建凭据

```
# 方式 1: 激活码（推荐 — admin 不接触 raw key）
POST /api/v1/admin/activation-codes/batch
{ "count": 1, "domain_addr": "alice@agent.example.com" }
→ 返回 { "raw_codes": ["addr-xxxx-xxxx-..."] }

# agent 侧：用激活码兑换 API key
POST /api/v1/activate-address
{ "code": "addr-xxxx-xxxx-..." }
→ 返回 { "api_key_id": 3, "email_address": "alice@agent.example.com", "raw_key": "sk-..." }

# 方式 2: 直接创建 API key（admin 能看到 raw key）
POST /api/v1/api-keys
{
  "system_id": "admin",
  "email_address": "alice@agent.example.com",
  "scopes": ["agent"],
  "category": "agent"
}
→ 返回 { "id": 3, "raw_key": "sk-..." }
```

### 2.5 Agent 配置

每个 agent profile 下自动创建 `amail.json`：

```json
{
  "relay_url": "http://localhost:38080",
  "api_key": "sk-...",
  "email": "alice@agent.example.com"
}
```

---

## 三、入站邮件处理全流程

```
外部发件人
    │ SMTP
    ▼
amail-relay (Rust)
    │ 1. 查询 system_domains WHERE domain_addr = 收件地址
    │ 2. 回退: 查 bare domain
    │ 3. 匹配 webhook_url + webhook_secret
    │ 4. HMAC-SHA256 签名 → X-Webhook-Signature
    │ 5. POST /webhooks/amail-inbound
    ▼
Hermes Gateway (webhook 平台)
    │ 1. HMAC 验签
    │ 2. preprocess_mail_payload():
    │    ├─ 解析 persona（persona.profile@domain → my_role）
    │    ├─ 提取 MIME display names
    │    ├─ 注入 direct_message / mentioned
    │    ├─ 下载附件到本地缓存
    │    └─ 剥离后端字段
    │ 3. store_inbound_message():
    │    ├─ 写入 msg:{mid} 元数据到 relay agent_state
    │    ├─ references → 构建 thread_id
    │    └─ save_raw_snapshots=true → 保存原始邮件快照
    │ 4. /personality {persona}（切换 SOUL）
    │ 5. 加载 amail skill
    ▼
Agent 处理
    │ Round 1: Understand（读 sender_profile、thread_summary、附件）
    │ Round 2: Contextualize（查联系人、搜索历史）
    │ Round 3: Execute（如有任务，delegate_task）
    │ Round 4: Decide（回复 or 忽略）
    │ Round 5: Reply（send_mail）
    │ Round 6: Remember（set_email_summary + set_contact_profile）
    ▼
回复通过 send_mail → relay POST /api/v1/send → SMTP 发出
```

### 入站 JSON 结构

```json
{
  "message_id": "<abc123@mx>",
  "subject": "Q3 Report",
  "body": "Hi, can you...",
  "sender": "John Doe <john@corp.com>",
  "sender_profile": "{\"name\":\"John\",\"title\":\"CEO\"}",
  "recipients": {
    "to": ["alice@agent.example.com"],
    "cc": ["bob@corp.com"]
  },
  "recipients_profile": {
    "bob@corp.com": "{\"name\":\"Bob\",\"title\":\"CTO\"}"
  },
  "my_amail_addr": "alice@agent.example.com",
  "my_profile": "{\"name\":\"Alice\",\"role\":\"support\"}",
  "direct_message": true,
  "mentioned": false,
  "thread_summary": "1. Budget approved. 2. Timeline: Q4.",
  "attachments": ["/tmp/amail_cache/report.docx.md", "/tmp/amail_cache/report.docx"]
}
```

---

## 四、发信流程

### 4.1 send_mail 调用

```python
send_mail(
    to="john@corp.com",
    subject="Re: Q3 Report",
    body="Hi John, here's the analysis...",
    message_id="<abc123@mx>",      # 回复时传入，工具自动处理 threading
    cc=["bob@corp.com"],
    attachments=["/path/to/file.pdf"],
    sender_name="Alice from Support"  # 可选，覆盖发件人显示名
)
```

### 4.2 内部执行流程

```
Agent 调用 send_mail
    │
    ├─ 1. 如果传了 message_id:
    │      load_message_metadata(mid)
    │      → relay.agent_state_get("msg:{mid}")
    │      → 获取 references + thread_id
    │      → 构建 In-Reply-To + References headers
    │
    ├─ 2. 联系人检查:
    │      manage_contacts(action="check", ...)
    │      → relay GET /admin/whitelists/check
    │      → 确认 to/cc 在白名单
    │
    ├─ 3. 附件上传:
    │      relay POST /api/v1/upload
    │      → 获得 attachment_id
    │
    ├─ 4. 发送:
    │      relay POST /api/v1/send
    │      {
    │        "to": [...],
    │        "cc": [...],
    │        "subject": "...",
    │        "body": "...",
    │        "in_reply_to": "<abc123@mx>",
    │        "references": "...",
    │        "attachments": [...]
    │      }
    │      → relay 通过 SMTP 发出
    │      → 返回 { "message_id": "<outbound-xyz@mx>" }
    │
    ├─ 5. 存储出站元数据:
    │      relay.agent_state_put("msg:{out-mid}", ...)
    │      → 后续回复可追踪
    │
    └─ 6. (可选) 保存快照:
           save_raw_snapshots=true
           → raw_email/{agent}/{yyyymm}/out-{mid}.json
```

### 4.3 SMTP 发送路径

```
send_mail → relay POST /api/v1/send
    │ auth: X-Api-Key (scope: agent/send)
    │ whitelist check: to/cc 是否在白名单
    │ persona stripping: persona.profile@domain → profile@domain
    ▼
relay SMTP client → 外部 SMTP 服务器
    │ Message-ID 由 relay 生成
    │ From: 使用 agent 的 email_address
    ▼
外部收件人
```

---

## 五、权限模型

| 凭据 | 持有者 | 权限 |
|------|--------|------|
| `admin_key` | relay 管理员 | platform + system: 管理域名、创建 key、生成激活码 |
| 激活码 | profile 配置 | 一次性：兑换为 agent API key |
| agent API key | agent profile | agent: 收发邮件、管理联系人、读写联系人/摘要 |
| HMAC secret | gateway + relay | 系统间信任，验签 webhook 请求 |

**安全原则：**
- 激活码创建者看不到 raw API key（激活码兑换时由 agent 自己拿到）
- 每个 agent 独立 API key，scope 最小化（`agent`）
- 激活码一次性使用

---

## 六、存储模型

| 存储位置 | 内容 | 访问方式 |
|----------|------|----------|
| relay `agent_state` | `profile:{addr}` — 联系人 JSON | 语义端点 PUT/GET `/contacts/:addr` |
| relay `agent_state` | `name:{name}` — 姓名索引 | 语义端点内部维护 |
| relay `agent_state` | `thread:{tid}` — 线程摘要 | 语义端点 PUT/GET `/thread-summary/:mid` |
| relay `agent_state` | `msg:{mid}` — 消息元数据 | 内部，自动写入 |
| relay `api_keys` | API key hash + scope | `/api-keys` CRUD |
| relay `system_domains` | 域名/地址路由 + webhook | `/admin/systems/.../domains` |
| relay `whitelists` | 联系人白名单 | `/admin/whitelists` CRUD |
| 本地 `raw_email/` | 原始邮件快照（可选） | `save_raw_snapshots: true` 时写入 |
