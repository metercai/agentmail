# agentmail.json 字段参考(地址级配置)

> 状态:备案(2026-08-18)。通用字段 = 现状实锤(三平台磁盘实例 + 代码读取点核实);
> dsh 扩展字段 = 方案已定,待 dsh 对接实施时落地。
> 位置:`~/.agentmail/systems/{system_id}/{cleaned_addr}/agentmail.json`
> (cleaned_addr = email 清洗名,如 `agent.weiwei_amail.token.tm`;目录按 agent 隔离)

## 1. 定位与边界

| 项 | 说明 |
|----|------|
| 本质 | **per-address(agent 级)配置**,一个文件 = 一个邮件地址的全部运行配置 |
| 对比 | 系统级配置 = `agentmail_gateway.json`(`systems/{sid}/` 根,唯一文件名,无兼容别名);agentmail.json 在地址子目录,多 agent 系统每 agent 一份 |
| 共享布局 | 与 `board_creds.json` 同层;`~/.agentmail/` 权限 700,配置文件 600 |
| 读取方 | 平台无关共享核心:`agentmail_base.load_agent_config` / `_scan_systems_for_agent`(按 `agent_id` 匹配)、`set_agent_context`;`agentmail_tools`(send_mail 等 12 工具经 `_GatewayClient(config["gateway_url"], config["api_key"])`) |
| 写入方 | 各平台注册脚本(薄调用共享注册链 register_agent_email 后落盘):Hermes 注册链 / OpenClaw `bin/register_agent.py` / DeerFlow `scripts/deer-flow/register_agent.py`;dsh 由 `scripts/dsh/bind_agent.py` 落盘 |
| 解析 | dict 加载(`json.loads`),**未知字段无害**(无严格 schema 拒绝)——平台特有字段可自由并入 |
| 原子写 | 改任何字段 = 整文件 tmp+replace,禁止局部覆盖(防并发写坏) |

### 1.1 webhook_url 与入站链路(2026-08-18 修正,用户纠正)

**`webhook_url` + `webhook_secret` 成对出现,是 agent 侧接收端点的注册声明**:

- 注册链 `register_agent_email(client, system_id, email, webhook_url, webhook_secret, ...)` 把两者随 `register_email` 发给 gateway(云端 system_domains 记录)——`webhook_url` = agent 侧接收端点地址,`webhook_secret` = 配套验签密钥(HMAC 校验 `X-Webhook-Signature`)。
- **bridge 是透明代理**:同内网环境下(自建 gateway),gateway 直接 webhook 到 agent 接收端点,**不经过 bridge**;跨网/NAT 环境才由 amail-bridge(pull,2s 轮询 /pending → 路由表全 URL 转发)承担,转发到**同一接收端点**。两条路径共用同一字段,路由表在 `bridge/amail_routes.toml`,不在 agentmail.json。
- **平台特有投递端点字段(如 deerflow_url)与 webhook_url 性质一致,应合并**:都是"agent 侧接收端点地址"。DeerFlow 的 `deerflow_url`(`http://127.0.0.1:8001`)= DeerFlow 接收端点 = 其 webhook_url;落盘统一用 `webhook_url` 字段,不另立名(2026-08-18 定调,方案执行时合并)。
- 本地接收端点(如 OpenClaw `/hook`、dsh mail-inbound 端点)同理 = 注册的 webhook_url 值。

入站完整链路:云端 SMTP 收信 → gateway 清洗/富化 → 入站队列 → **两条路径**:同内网 = gateway 直接 webhook 到接收端点;跨网 = amail-bridge 轮询转发 → 接收端点 → **验签(webhook_secret)** → 预处理 → 投递 agent。

## 2. 字段总表

### 2.1 通用字段(全部平台,4 平台共享)

| 字段 | 类型 | 必填 | 作用 |
|------|------|------|------|
| `email` | string | ✅ | agent 的 amail 地址。出站 sender(服务端强制 sender==key.email 身份隔离);入站路由目标;persona 归一基准;日志文件名(`agentmail.{cleaned_addr}.log`)的构成源 |
| `api_key` | string(64 hex) | ✅ | agent 级 API 密钥(最小权限,1:1)。全部 gateway HTTP 调用鉴权(send/contacts/附件下载/pong);SMTP auth.local 认证唯一凭证(**无 admin_key 回退**) |
| `gateway_url` | string | ✅ | 云端 gateway 基址(如 `https://amail.token.tm`)。所有 HTTP API 调用目标 |
| `system_id` | string | ✅ | 系统标识(`shared-token-{hash}` / `system-{code}`)。目录键;gateway 侧系统归属;指针文件的值来源 |
| `domain` | string | ✅ | 邮件域(如 `amail.token.tm`)。**唯一作用 = agent 地址拼接**(`{base}[.{system_name}]@{domain}`);传给 `email_for_agent` 与 `register_email`(gateway 侧从 email 自行提取域,不另收 domain 参数) |
| `system_name` | string | 共享域必填 | 系统名。**共享域下参与地址拼接**:`{base}.{system_name}@{domain}`(如 `agent.weiwei@amail.token.tm`);独立域下为空 → `{base}@{domain}`。两种全地址拼接方式由 `system_id` 前缀判定(shared-* → 共享域,其余独立域) |
| `manager_address` | string | ✅ | 管理员邮箱。入站白名单判定;welcome 验收的收件人(管理员收到 Re: 回复) |
| `mx_domain` | string | 冗余 | **历史遗留冗余字段**(2026-08-18 代码验证):注册脚本统一写 `mx_domain = domain`;client.register_email 的 mx_domain 形参**并未传给 gateway**(请求体仅 id/email/webhook_url/webhook_secret/manager_address,gateway 从 email 提取域);agentmail_base:122-123 仅作默认值构造(未配 domain 时用 `amail.token.tm` 派生)。**与 domain 同一事物,无功能意义,新平台不再写入,存量保留兼容** |

### 2.2 平台特有字段(按平台,互不冲突)

| 字段 | 类型 | 平台 | 作用 |
|------|------|------|------|
| `agent_id` | string | OpenClaw / DeerFlow / (Hermes 可选) | 平台内 agent 标识(`main` / `default` / profile 名)。`_scan_systems_for_agent(agent_id)` 的匹配键;Hermes 按 profile 名注册、文件内可缺省 |
| `webhook_secret` | string | OpenClaw / DeerFlow | 入站 webhook HMAC 验签密钥(校验 bridge 转发的 `X-Webhook-Signature`)。Hermes 不落此字段(secret 在 profile config 的 platforms.webhook) |
| `deerflow_url` | string | DeerFlow | **已删除**(2026-08-18 重构执行):预处理并入 DeerFlow 本地 gateway(8001)进程后,接收端点统一为 `webhook_url`(`http://127.0.0.1:8001/agentmail/inbound`);旧独立接收进程 amail_deerflow_bridge(8798)退役。存量文件含此字段时忽略 |
| `assistant_id` | string | DeerFlow | DeerFlow 平台内**助理定义标识**(如 `lead_agent`,预设角色)。**不进地址**:地址 base 来自 `agent_id`(default→agent);assistant_id 是投递目标(amail_deerflow_bridge 调 DeerFlow gateway 时指定哪个 assistant 处理)与 Hermes **profile 同级**(定义/角色层)。**assistant 有 name 字段**(代码实锤:AssistantResponse = assistant_id/graph_id/name,默认三者同名 "lead_agent";自定义 agent 时 name = 配置名,graph 统一 lead_agent)——未来多 assistant 各自收信时,地址 base 直接取 assistant 的 name 即可,无需另设命名体系;当前仅 lead_agent |

### 2.3 dsh 扩展字段(方案已定,待实施)

| 字段 | 类型 | 必填 | 作用 |
|------|------|------|------|
| `session_id` | string | dsh 必填 | **dsh 会话实例标识**。入站:收件地址 → 查此字段得 session_id → `ctx.agents.resume()/get()` → `followup`;出站:工具调用 `exec.agent.id`(= session_id)→ 反查此字段得 email/system_id → 读 api_key 调 gateway。dsh 身份 = 匿名 SessionId,此字段是其与 amail 地址的唯一绑定 |
| `preset` | string | dsh 必填 | dsh preset 名(如 `mail`)。agent 定义层归属记录(工具/SKILL 层),供 bind/unbind 与巡检使用 |

> 设计要点:api_key 不重复存(session_id/preset 之外无新秘密)——凭据唯一权威仍是
> 本文件的 `api_key` 字段,避免双份秘密。合并自原独立 `binding.json` 概念
> (2026-08-18 用户定调:per-address 文件独立成表是冗余,字段并入 agentmail.json)。

### 2.4 身份层级对照(2026-08-18 调研,防概念混淆)

四个平台"定义级 / 实例级 / 会话级"三层对照:

| 平台 | 定义级(角色/预设) | 实例级(身份,进地址) | 会话级(一次对话) |
|------|------------------|---------------------|------------------|
| Hermes | **profile**(命名,持久,如 agentmail;default→agent 归一) | = profile(定义实例合一,无独立实例层) | session(sessions.json / state.db;webhook 会话按 sessionKey 聚合) |
| OpenClaw | agentId(main→agent 归一) | = agentId | hook 会话(sessionKey `agent:{id}:hook:amail`) |
| DeerFlow | **assistant_id**(lead_agent,预设角色,投递目标) | agent_id(default→agent,地址 base 来源;assistant_id 不进地址) | DeerFlow 侧会话(bridge 调用时上下文) |
| dsh | **preset**(mail,工具/SKILL 层) | **session_id**(匿名 UUID,1 地址 = 1 会话,唯一实例标识) | = 实例(无独立会话层;preset/uuid 解耦) |

结论与用户判断一致:**deerflow assistant_id ≈ Hermes profile 同级**(都是定义/角色层)。
差异:Hermes/OpenClaw 定义=实例(身份合一,profile/agentId 直接进地址);DeerFlow 定义(assistant_id)与地址分离(地址用 agent_id);dsh 定义(preset)与地址完全解耦(地址绑 session_id)。"默认主 agent 名"约定:Hermes default→agent、OpenClaw main→agent、DeerFlow default→agent(共享域 `agent.{system_name}@{domain}`);**dsh 无内置默认名**——bind 脚本显式绑定,主 agent 约定绑 `agent` 地址。

## 3. 实例(修订后形态,2026-08-18;存量文件字段超集,兼容读取)

```json
// Hermes(shared-token-40b34a66,共享域 weiwei)——通用字段全集(无 webhook_url/
// webhook_secret:Hermes 的接收端点与验签密钥在 profile config 的 platforms.webhook)
{
  "email": "agent.weiwei@amail.token.tm",
  "gateway_url": "https://amail.token.tm",
  "domain": "amail.token.tm",
  "system_id": "shared-token-40b34a66",
  "system_name": "weiwei",
  "manager_address": "925457@qq.com",
  "api_key": "<64hex>"
}
```

```json
// OpenClaw(shared-token-9479c607,共享域 xianlin)——通用 + 平台特有(webhook_url 成对)
{
  "email": "agent.xianlin@amail.token.tm",
  "gateway_url": "https://amail.token.tm",
  "domain": "amail.token.tm",
  "system_id": "shared-token-9479c607",
  "system_name": "xianlin",
  "manager_address": "925457@qq.com",
  "api_key": "<64hex>",
  "agent_id": "main",
  "webhook_url": "http://127.0.0.1:8799/hook",
  "webhook_secret": "<hex>"
}
```

```json
// DeerFlow(shared-token-66b33608,共享域 deerflow)——通用 + 平台特有(webhook_url =
// 本地 gateway 接收端点,预处理并入 8001 进程;2026-08-18 重构)
{
  "email": "agent.deerflow@amail.token.tm",
  "gateway_url": "https://amail.token.tm",
  "domain": "amail.token.tm",
  "system_id": "shared-token-66b33608",
  "system_name": "deerflow",
  "manager_address": "925457@qq.com",
  "api_key": "<64hex>",
  "agent_id": "default",
  "webhook_url": "http://127.0.0.1:8001/agentmail/inbound",
  "webhook_secret": "<hex>",
  "assistant_id": "lead_agent"
}
```

```json
// dsh(方案态,共享域 dsh)——通用 + dsh 扩展(session_id/preset;webhook_url =
// mail-inbound 接收端点,待实施)
{
  "email": "agent.dsh@amail.token.tm",
  "gateway_url": "https://amail.token.tm",
  "domain": "amail.token.tm",
  "system_id": "shared-token-xxxxxxxx",
  "system_name": "dsh",
  "manager_address": "925457@qq.com",
  "api_key": "<64hex>",
  "webhook_url": "http://127.0.0.1:<port>/agentmail/deliver",
  "webhook_secret": "<hex>",
  "session_id": "<dsh-session-uuid>",
  "preset": "mail"
}
```

## 4. 相关约束(铁律)

- 配置文件权限 600、`~/.agentmail/` 700;凭据最小化(agent 文件只存 agent key,无 admin_key)。
- 系统身份 = 指针文件唯一来源(Hermes `profiles/{name}/.agentmail`、OpenClaw `~/.openclaw/.agentmail`),agentmail.json 的 system_id 与指针一致;禁 env 覆盖、禁目录扫描、禁跨系统借用。
- 读取方不做兼容别名(`amail.json` 不存在);文件名唯一 `agentmail.json`。
- 新增字段 = 各平台注册脚本写(注册链薄壳落盘),业务语义仍在共享链一处。
