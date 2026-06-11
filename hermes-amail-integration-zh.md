---
id: hermes-amail-integration-zh
title: amail — Agent 邮件集成指南
status: final
created: 2026-05-22
updated: 2026-06-01
---

> 🇬🇧 [English](./hermes-amail-integration.md)

## 概述

Amail 为你的 Hermes agent 提供一个专属邮箱地址。入站邮件成为对话消息，附件被预处理，多人群聊变为群组会话。agent 通过**六个工具**完成发信、回复、联系人管理和线程状态追踪。

**一行命令完成对接。** `bash integrate.sh` 自动检测 gateway、验证凭证、保存配置并运行诊断——一步到位。

---

## 架构

```
┌─────────────┐     SMTP      ┌──────────────┐    POST /webhooks/amail-inbound    ┌────────────────┐
│  外部发件人   │ ────────────→ │  amail-gateway │ ─────────────────────────────────→ │ Hermes Gateway │
│  (email)     │               │  (Rust)      │   X-Webhook-Signature (HMAC)       │ (webhook 平台)  │
└─────────────┘               └──────────────┘                                    └──────┬─────────┘
                                                                                         │
                                                                    ┌────────────────────┤
                                                                    │ preprocessor       │
                                                                    │ → sender 显示名    │
                                                                    │ → persona 解析     │
                                                                    │ → direct_message   │
                                                                    │ → 附件下载         │
                                                                    ├────────────────────┤
                                                                    │ store_inbound_msg  │
                                                                    │ → agent_state(msg) │
                                                                    │ → raw_email 快照   │
                                                                    ├────────────────────┤
                                                                    │ /amail skill 加载  │
                                                                    │ → agent 处理邮件   │
                                                                    └────────────────────┘
```

**核心设计决策：**
- Webhook secret 由 **Hermes 网关管理**（Hermes 创建，gateway 接收）
- 所有 agent 地址共享一个路由：`amail-inbound`
- Persona 编码在邮件地址中：`persona.profile@domain`

---

## 快速集成（脚本）

```bash
# 在 integrations/hermes 目录下
bash integrate.sh

# 10 步向导：
#   [1/10] gateway 连接      — 自动检测 localhost:38080
#   [2/10] 认证方式        — 输入 admin_key 或产品激活码
#   [3/10] domain          — 选择或输入 agent 邮件域 (仅 admin_key 路径)
#   [4/10] 基本配置        — 是否保存快照？+ 默认管理员邮箱
#   [5/10] 保存配置        — 写入 ~/.hermes/amail_gateway.json（或激活系统）
#   [6/10] 安装工具        — 复制 amail_tools.py + 注册到 toolsets.py
#   [7/10] patch webhook   — 注入预处理器支持
#   [8/10] patch profiles  — 注入 profile 生命周期 hooks
#   [9/10] 综合诊断        — verify_integration() 检查
#   [10/10] 收发测试        — 创建测试 key、发送邮件、清理

# 选择语言：英文（默认）或中文
# 非交互模式 (CI/脚本):
AMAIL_GATEWAY_URL=http://gateway:38080 \
AMAIL_ADMIN_KEY=sk-... \
AMAIL_DOMAIN=admin.local \
AMAIL_SAVE_SNAPSHOTS=false \
AMAIL_MANAGER_ADDRESS=admin@admin.local \
  bash integrate.sh --auto

# 产品激活码路径（新系统）：
AMAIL_GATEWAY_URL=http://gateway:38080 \
AMAIL_PRODUCT_CODE=prod-xxxx-xxxx-xxxx \
AMAIL_MANAGER_ADDRESS=admin@example.com \
  bash integrate.sh --auto

# Docker / 自定义网络：手动指定 webhook 回调地址
AMAIL_WEBHOOK_HOST=192.168.1.100 bash integrate.sh --auto
```

**两种认证路径：**
| 路径 | 需要什么 | 结果 |
|---|---|---|
| admin_key | 已有的系统管理员 API key | 直接保存配置 |
| product_code | 预先生成的产品激活码 | 激活系统，返回 admin_key |

product_code 路径自动跳过 Step 3（domain 由服务器生成）。

**环境变量：**

| 变量 | 必填 | 默认值 | 用途 |
|---|---|---|---|
| `AMAIL_GATEWAY_URL` | 是（auto） | — | Gateway 服务器 URL |
| `AMAIL_ADMIN_KEY` | admin_key 路径 | — | 已有的系统管理员 API key |
| `AMAIL_PRODUCT_CODE` | product_code 路径 | — | 一次性产品激活码 |
| `AMAIL_DOMAIN` | 否 | 空 | Agent 邮件域名 |
| `AMAIL_SAVE_SNAPSHOTS` | 否 | false | 是否本地保存原始邮件快照 |
| `AMAIL_MANAGER_ADDRESS` | 否 | 空 | Agent 的默认管理员邮箱 |
| `AMAIL_LANG` | 否 | en | 语言选择 (`en` 或 `zh`) |
| `AMAIL_WEBHOOK_HOST` | 否 | 自动探测 | 手动指定 webhook 回调地址（Docker、自定义网络） |
| `AMAIL_BRIDGE_URL` | 否 | 空 | Push 模式 bridge 完整 URL（如 `https://bridge.example.com/webhooks/amail-inbound`） |

脚本自动处理配置、工具安装、源码补丁、诊断和收发测试——一站式完成 amail 与 Hermes 的对接。

---

## Agent Profile 生命周期

### 1. Profile 创建

创建 Hermes profile 时，**profile hook** 自动触发：

1. 在 gateway 上注册 `{profile_name}@{domain}` 为 webhook 路由
2. 在 domain 元数据中设置**管理员地址**
3. 自动白名单管理员，使 agent 可以发送联系人申请
4. 在网关上创建 `amail-inbound` webhook 路由（幂等）
5. 生成**地址激活码**并保存到 profile 配置

```json
// {profile_dir}/amail.json — 自动写入
{
  "email": "alice@admin.local",
  "activation_code": "addr-xxxx-xxxx-xxxx-xxxx-xxxx-xxxx",
  "gateway_url": "http://localhost:38080",
  "domain": "admin.local",
  "system_id": "admin",
  "manager_address": "admin@admin.local",
  "save_raw_snapshots": false,
  "webhook_host": "127.0.0.1"
}
```

> **安全原则**：profile 配置存的是 `activation_code`，不是原始 `api_key`。
> 管理员无法看到 agent 的 API key。

### 2. Agent 启动

Agent 启动时，`agent_startup_activate()` 检测到 `activation_code`，通过
`POST /api/v1/activate-address` 兑换为真实 `api_key`，写入 `amail.json`
并移除 `activation_code`。

### 3. Profile 删除

删除 profile 时，agent 的 API key 从 gateway 移除，`amail.json` 删除。
Domain 注册和 webhook 路由保留以便未来重新激活。

---

## Persona 切换

Amail 通过邮件地址格式 `persona.profile@domain` 实现动态 persona 切换。
每个 profile 可以在自己的 `config.yaml` 中定义多个 persona：

```yaml
# {profile_dir}/config.yaml
agent:
  personalities:
    support: "你是一个耐心的客服助手，用温和的语气帮助用户解决问题。"
    sales:   "你是一个有说服力的销售顾问，专注于传递产品价值。"
```

**工作原理：**

1. 有人发送邮件到 `support.alice@admin.local`
2. 预处理器剥离 persona 前缀，对照当前 profile 的 `agent.personalities` 配置进行校验
3. 校验通过 → agent 收到 `my_amail_addr = "support.alice@admin.local"`，以 support 身份运行
4. 校验失败（未配置该 persona）→ 回退到 `alice@admin.local`（记录 warning）

Persona 是 **per-profile** 的——每个 profile 只校验自己的配置，不会跨 profile 泄露。
Persona 配置由 Hermes 用户自行管理，非集成脚本职责。

---

## 入站消息模型

每封入站邮件以 JSON 消息的形式到达。预处理器产出以下字段；其余字段由网关管道注入。

| 字段 | 来源 | 含义 |
|------|------|------|
| `message_id` | gateway SMTP | 唯一标识符，用于线程追踪 |
| `subject` | gateway SMTP | 邮件主题 |
| `body` | gateway SMTP | 纯文本正文 |
| `sender` | 预处理器 | `Name <email>` 格式 — 正在和你对话的人 |
| `sender_profile` | 网关 | 发件人联系人画像（自动填充） |
| `recipients` | 预处理器 | `{to: [...], cc: [...]}` — 线程中的所有参与者 |
| `recipients_profile` | 网关 | 除你之外所有收件人的联系人画像 |
| `my_amail_addr` | 预处理器 | 你的 persona 感知地址（如 `support.alice@domain`） |
| `my_profile` | 网关 | 你自己的联系人画像 |
| `direct_message` | 预处理器 | `true` = 你是唯一的 `to` 收件人（无 CC） |
| `mentioned` | 预处理器 | 正文中有人写了 `@your-name` |
| `thread_summary` | 网关 | 上次 `set_email_summary` 保存的线程状态 |
| `attachments` | 预处理器 | 本地文件路径（DOCX/XLSX/PDF 附带 `.md` 提取文件） |

---

## 入站处理管道

```
SMTP → gateway
  → 解析 system_domains（精确匹配 → 裸域回退）
  → HMAC-SHA256 签名 → X-Webhook-Signature
  → POST /webhooks/amail-inbound
    ├─ HMAC 验证（网关）
    ├─ preprocess_mail_payload(payload, headers)
    │   ├─ 从 MIME headers 提取显示名 → sender 字段
    │   ├─ 从 'to' 地址解析 persona (persona.profile@domain)
    │   ├─ 设置 recipients: {to: [...], cc: [...]}
    │   ├─ 设置 my_amail_addr: persona 感知的 agent 地址
    │   ├─ 计算 direct_message: 单个 to 收件人 + 无 CC
    │   ├─ 计算 mentioned: 正文中的 @name
    │   └─ 下载附件 → 本地缓存（文档类型生成 .md 提取文件）
    ├─ store_inbound_message()
    │   ├─ msg:{mid} 元数据 → gateway agent_state
    │   └─ save_raw_snapshots=true → raw_email/{agent}/{yyyymm}/in-{mid}.json
    ├─ 注入 sender_profile / recipients_profile / my_profile / thread_summary
    ├─ /personality {persona}（如果路由配置了 persona 字段）
    ├─ /amail skill 调用
    └─ Agent 处理邮件 → 使用 send_mail 工具回复
```

---

## Agent 工具（6 个工具，toolset: `amail`）

| 工具 | 用途 |
|------|------|
| `send_mail(to, subject, body, message_id?, cc?, attachments?)` | 发送或回复邮件。传 `message_id` 维持线程。 |
| `contact_profile(address?, name?)` | 按地址或姓名查询联系人 |
| `set_contact_profile(address, description)` | 存储/更新联系人画像（JSON merge，自动 name-index） |
| `manage_contacts(action, address, direction?)` | 检查/添加/删除白名单联系人 |
| `email_summary(message_id)` | 获取已存储的线程摘要 |
| `set_email_summary(message_id, summary)` | 回复后保存更新后的线程状态 |

---

## 集成函数

| 函数 | 用途 |
|------|------|
| `setup(gateway_url, system_id, admin_key?, product_code?, domain?, save_raw_snapshots?, manager_address?)` | 保存 gateway 配置到 `~/.hermes/config.yaml` |
| `verify_integration(gateway_url?, admin_key?)` | 运行诊断检查，返回逐项通过/失败 |
| `agent_startup_activate()` | 启动时将 activation_code 兑换为 api_key |
| `preprocess_mail_payload(payload, headers)` | 网关预处理器（由 webhook adapter 调用） |
| `store_inbound_message(message_id, references, my_amail_addr, preprocessed_payload)` | 存储消息元数据 + 可选快照 |
| `parse_amail_persona(email)` | 从 `persona.profile@domain` 提取 (persona, profile) |

---

## API 端点

### Agent 工具

| 方法 | 路径 | 认证 | 用途 |
|------|------|------|------|
| POST | `/api/v1/send` | X-Api-Key (agent) | 发送邮件 |
| POST | `/api/v1/upload` | X-Api-Key (agent) | 上传附件 |
| GET | `/api/v1/attachments/:id` | X-Api-Key (agent) | 下载附件 |
| GET/POST/DELETE | `/api/v1/admin/whitelists` | X-Api-Key | 管理联系人（检查/添加/删除） |
| GET | `/api/v1/admin/whitelists/check` | X-Api-Key | 检查白名单 |
| GET | `/api/v1/whoami` | X-Api-Key | 验证身份、scope 和管理员信息 |

### 语义化端点（联系人 + 线程状态）

| 方法 | 路径 | 用途 |
|------|------|------|
| PUT | `/api/v1/admin/contacts/:address` | 原子写入画像 + name 索引 + JSON merge |
| GET | `/api/v1/admin/contacts/:address` | 按地址读取联系人 |
| GET | `/api/v1/admin/contacts?name=...` | 按姓名搜索联系人（服务端） |
| PUT | `/api/v1/admin/thread-summary/:message_id` | 写入摘要（自动解析 thread_id） |
| GET | `/api/v1/admin/thread-summary/:message_id` | 读取摘要（自动解析 thread_id） |

### 管理员端点

| 方法 | 路径 | 认证 | 用途 |
|------|------|------|------|
| POST | `/api/v1/api-keys` | admin_key | 创建 agent API key |
| GET/PUT/DELETE | `/api/v1/api-keys/:id` | admin_key | 管理 API keys |
| POST | `/api/v1/admin/systems/{sid}/domains` | admin_key | 注册 agent 邮箱 + 管理员 + webhook |
| POST | `/api/v1/admin/activation-codes/batch` | admin_key | 生成地址激活码 |
| POST | `/api/v1/activate-address` | 无 | 激活码兑换 api_key |
| PUT | `/api/v1/admin/agent-meta/:email` | admin_key/AA | 更新 agent 签名/角色/管理员 |
| GET | `/api/v1/admin/pending?system_id=X` | admin_key | **Pull 模式**：获取未投递消息 |
| POST | `/api/v1/admin/pending/ack` | admin_key | **Pull 模式**：标记消息已投递 |

---

## 安全模型

| 凭证 | 持有者 | 用途 |
|------|--------|------|
| Admin key (`system` scope) | Gateway 运维者、`integrate.sh` | 管理域、生成激活码、配置白名单 |
| 地址激活码 | Profile 配置（磁盘） | 一次性：agent 自激活 → 返回原始 api_key |
| Agent API key (`agent` scope) | Profile 配置（磁盘） | 收发邮件、管理联系人、写入线程摘要 |
| Webhook HMAC secret | Gateway | 系统级信任：gateway 与 Hermes 网关之间的签名验证 |

**核心原则：**
- 激活码创建者永远看不到生成的原始 API key
- 每个 agent 拥有独立的 API key，最小权限
- 激活码一次性使用
- 管理员 ↔ Agent 白名单在 profile 创建时自动建立

---

## 配置参考

### Gateway 配置 (`~/.hermes/amail_gateway.json`)

独立文件，不污染 `config.yaml`：

```json
{
  "gateway_url": "http://localhost:38080",
  "admin_key": "sk-...",
  "system_id": "admin",
  "domain": "admin.local",
  "save_raw_snapshots": false,
  "manager_address": "admin@admin.local",
  "webhook_host": "127.0.0.1"
}
```

`webhook_host` 字段在集成过程中**自动探测**：通过比较 `gateway_url` 与本地网卡地址，
自动确定 gateway 回调 Hermes gateway 的地址：

| gateway 位置 | 探测结果 |
|---|---|
| 同机 | `127.0.0.1` |
| 同局域网 | 本机 LAN IP |
| 公网 | 外网 IP（或 LAN fallback） |
| Docker（手动） | 设置 `AMAIL_WEBHOOK_HOST` 环境变量 |

可通过 `AMAIL_WEBHOOK_HOST` 环境变量覆盖，或直接编辑 `amail_gateway.json`。

**可选 `bridge_url` — amail-bridge push 模式：**

使用 [amail-bridge](../docs/amail-bridge-design.md) push 模式时，添加
`bridge_url` 将所有 webhook 回调路由到 bridge：

```json
{
  "bridge_url": "https://bridge.example.com/webhooks/amail-inbound"
}
```

存在 `bridge_url` 时，`webhook_host` 会被忽略。bridge 负责 TLS 终结和
到各 profile gateway 端口的内部路由。

**可选 `delivery_mode` — amail-bridge pull 模式：**

使用 bridge pull 模式（无公网 IP）时，在 gateway 上通过
`POST /api/v1/admin/systems/{sid}/domains` 设置 `delivery_mode: "pull"`。
SMTP 邮件存入 gateway 待投递队列，不主动 POST webhook。

### Profile 配置 (`{profile_dir}/amail.json`)

```json
{
  "gateway_url": "http://localhost:38080",
  "api_key": "sk-...",
  "email": "alice@admin.local",
  "system_id": "admin",
  "domain": "admin.local",
  "manager_address": "admin@admin.local",
  "save_raw_snapshots": false,
  "webhook_host": "127.0.0.1"
}
```

### Webhook 路由 (`~/.hermes/webhook_subscriptions.json`)

```json
{
  "amail-inbound": {
    "description": "amail 入站邮件路由 (amail-inbound)",
    "events": [],
    "secret": "<WEBHOOK_SECRET>",
    "preprocess": "amail_gateway",
    "prompt": "",
    "skills": ["amail"],
    "deliver": "log",
    "persona": "",
    "created_at": "2026-06-01T...Z"
  }
}
```

---

## 存储

| 位置 | Key | 内容 |
|------|-----|------|
| gateway `agent_state` | `profile:{address}` | 联系人画像 JSON |
| gateway `agent_state` | `name:{name}` | `{"addresses": [...]}` 索引 |
| gateway `agent_state` | `thread:{thread_id}` | 线程摘要文本 |
| gateway `agent_state` | `msg:{message_id}` | `{"references": [...], "thread_id": "..."}` |
| 本地（可选） | `raw_email/{agent}/{yyyymm}/in-{mid}.json` | agent 可见的入站快照 |
| 本地（可选） | `raw_email/{agent}/{yyyymm}/out-{mid}.json` | agent 发出的出站快照 |

> **快照**：当 profile 配置中 `save_raw_snapshots: true` 时，入站和出站消息的
> agent 可见 JSON（预处理后）都会被保存。这些是 agent 实际处理的精确载荷——
> 用于调试和回放。

---

## HMAC 兼容性

Gateway 使用 `X-Webhook-Signature: {HMAC-SHA256(body, secret)}` 签名 webhook 载荷。
这是 Hermes webhook adapter 的通用格式。

Secret 在 Hermes 网关（生成方）和 gateway（接收方，在 domain 注册时获取）之间共享。

---

## 参考文档

- [API 参考 — 全部端点 & 流程](./INTEGRATION-REFERENCE.md)
- [安装指南](./INSTALL-TOOLS.md)
- [SKILL.md — agent 行为定义](./skill/SKILL.md)
- [端到端测试](../../tests/)
