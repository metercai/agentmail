# AgentMail Integration Guide — 对接规范(目标 / 方法 / 手段 / 结果)

> 状态:定稿(2026-08-18,经完整审计 + 三平台生产实证固化)
> 用途:后续任何 agent 系统对接 AgentMail 的第一参照文档。
> 权威代码:`tools/`(共享核心 + 平台适配)、`bin/`(运行时)、`scripts/`(CLI 层)、`skills/`(安装源)。
> 配套文档:`AGENTMAIL-JSON-REFERENCE.md`(配置文件字段权威参考)。
> docs/ 目录为本地草稿区(gitignore),不入库。

---

## 1. 目标

AgentMail 与任意 agent 系统(LLM 运行时)对接,使 agent 获得完整的邮件能力:

| 目标 | 达成形态 |
|------|----------|
| 入站 | 邮件经 gateway→bridge→agent 接收端点全链路可达;验签 → 共享预处理 → 投递 agent |
| 出站 | agent 经 send_mail 工具回信,服务端强制 sender==key.email 身份隔离 |
| 身份 | 1 agent = 1 amail 地址;每 agent 独立 api_key;配置单一事实源 |
| 工具 | 6 邮件工具 + board 工具全暴露(进程内 registry 或共享 MCP server) |
| 生命周期 | agent 创建/删除自动注册/注销(事件钩子或 CLI 包装),安装时全量补充注册 |
| 验收 | `agentmail ping`(三阶段日志闭环)+ `agentmail welcome`(含 LLM 双向)双测均过 |

---

## 2. 方法(总体架构与分层)

```
                        云端 amail-gateway
   ┌─────────────────────────────────────────────┐
   │ SMTP 收信 → 清洗/富化 → 入站队列(pending)     │
   │ HTTP API (send/contacts/...) / A2A Board    │
   └──────────┬──────────────────────────▲────────┘
              │ pending 轮询              │ HTTP API
   ┌──────────▼──────────┐   ┌───────────┴──────────┐
   │ amail-bridge (本机)  │──►│ agent 接收端点 (本机)  │
   │ 单进程多系统拉取      │   │ 验签 → 共享预处理       │
   │ 按路由表全 URL 转发   │   │ → 投递 agent           │
   └─────────────────────┘   └───────────▲──────────┘
                                         │ send_mail 出站
                                         ▼
                                云端 HTTP API → SMTP 投递
```

**分层职责**:

| 层 | 位置 | 职责 |
|----|------|------|
| 共享核心 | `tools/agentmail_base.py`、`agentmail_tools.py`、`agentmail_board.py` | 入站预处理链、ping/pong、地址派生、注册/注销链、邮件工具实现、board 工具 |
| 平台适配 | `tools/{platform}/` | 配置源、persona 开关、身份注入、工具注册、接收端点 |
| 运行时 | `bin/register_agent.py`、`deregister_agent.py` | agent 生命周期 |
| CLI 层 | `scripts/agentmail`(10 子命令)+ `scripts/gateway_api.py` | 安装/检查/测试/卸载/运维 |
| 安装源 | `skills/SKILL.md` + `DESCRIPTION.md` | 通用邮件技能(逐字拷贝,零改写) |

**铁律**:
- 共享代码只进 `tools/` 顶层,平台适配不得跨平台 import(适配层只做三件事:平台实现、注入点赋值、注册)。
- 配置单一事实源:系统身份 = 指针文件;地址级事实 = `agentmail.json`;系统级事实 = `agentmail_gateway.json`。禁 env 覆盖、禁目录扫描、禁跨系统借用。
- 所有平台、所有入站路径调用同一个 `process_inbound_mail(payload, headers)`(验签后)。

---

## 3. 手段(具体实现)

### 3.1 配置规范(字段权威参考见 AGENTMAIL-JSON-REFERENCE.md)

**agentmail.json(地址级,agentmail 唯一信任源)** — 通用 9 字段:
`email` / `gateway_url` / `domain` / `system_id` / `system_name` / `manager_address` / `api_key` / `webhook_url` / `webhook_secret`。

- `webhook_url` = 本地接收端点全 URL(含协议/端口/路径),与 `webhook_secret`(HMAC 验签密钥)**成对**,全平台落盘。
- 平台特有:`agent_id`(OpenClaw/DeerFlow)、`assistant_id`(DeerFlow)。
- 已移除:`mx_domain`(从未传给 gateway)、`deerflow_url`(统一为 webhook_url)。

**agentmail_gateway.json(系统级)** — `gateway_url` / `admin_key` / `system_id` / `system_name` / `save_raw_snapshots` / `domain` / `manager_address` / `webhook_host` / `system_home` / `default_agent_name`(OpenClaw)。

- `webhook_host` **三态语义**(安装时设置,决定地址注册参数):
  ① 有合法 IP:port → 有 bridge,push 模式 → 注册参数 = webhook_host(bridge 公网入口);
  ② 显式空 "" → 有 bridge,pull 模式 → 注册参数 = 空(云端不回调,bridge 拉取);
  ③ 配置项不存在 → 无 bridge → 注册参数 = agentmail.json 的 webhook_url(本地端点)。
- 已移除:`mode`(push/pull 由 webhook_host 表达;bridge 自身模式在 amail_bridge.toml)、`bridge_port`(接收端点端口已在 webhook_url)。

### 3.2 入站链路

```
云端收信 → gateway 入站队列 → bridge pull(2s 轮询 /pending)
  → 查路由表 amail_routes.toml(email → 接收端点全 URL)
  → 透明转发(逐字节 body + 头白名单 X-Amail-Email / X-Webhook-Signature / X-Mailrelay-Timestamp)
  → 接收端点:HMAC 验签(webhook_secret)→ process_inbound_mail(身份→富化→附件→存储)
  → ping/pong 拦截(三阶段日志)→ 未拦截投递 agent
```

- bridge 路由表维护三入口:**注册链**(新 agent 注册后必调 `register_bridge_route`)、CLI `agentmail bridge`(全量重刷)、安装同步(Hermes gateway.sh 路由段)。
- 接收端点(webhook_url):Hermes = `http://127.0.0.1:{port}/webhooks/agentmail-inbound`(进程内预处理);OpenClaw = `http://127.0.0.1:8799/hook`(外部预处理进程);DeerFlow = `http://127.0.0.1:8001/agentmail/inbound`(进程内预处理)。
- ping/pong:`__agentmail_ping__:` / `__amail_pong__:` 前缀(gateway send.rs P0 精确匹配);三阶段事件 `ping_intercepted → pong_sent → pong_returned` 落 `~/.agentmail/logs/agentmail.{cleaned_addr}.log`。

### 3.3 注册链(公共,幂等)

```
register_agent_email(client, system_id, email, webhook_url, webhook_secret,
                     manager_address) -> {"api_key", "activation_code"}
```

- 注册参数 webhook_url 由 `resolve_register_webhook_url(gw, local_webhook_url)` 按 webhook_host 三态解析(见 3.1);agentmail.json 落盘一律 = 本地端点。
- 注册后**必调** `register_bridge_route(system_id, email, gw, local_webhook_url)`(POST bridge /api/v1/routes,幂等 upsert)——否则 bridge 拉取后无路由,入站断链。
- manager 白名单 + domain_addr_meta 由 gateway register_address 自动创建,Python 侧不补。

### 3.4 身份、工具与地址派生

- **身份**:`_AGENT_IDENTITY_OVERRIDE = "platform/ver"`(出站头 X-Agentmail-Agent);1 agent = 1 地址 = 1 api_key。
- **注入点**(适配层 import 共享核心后赋值):

| 注入点 | 含义 |
|--------|------|
| `_CONFIG_LOADER` | agent 配置加载 `() -> Optional[dict]` |
| `_PROFILE_DIR_RESOLVER` | agent 目录 `() -> Optional[str]` |
| `_PERSONAS_PROVIDER` | personas 配置(无 persona 能力的平台设 `PERSONA_SUPPORTED=False`) |
| `_BOARD_GATEWAY_SINK` | board 网关注册回调 |
| `PERSONA_SUPPORTED` | 能力开关(False → 归一基础地址) |
| `_AGENT_IDENTITY_OVERRIDE`(tools) | 出站身份 header |

- **工具暴露**:进程内 registry(Hermes)或共享 `tools/amail_mcp_server.py`(MCP stdio server,newline-delimited JSON 帧协议,`amail__*` 前缀,平台无关——按共享布局落 agentmail.json 即可复用)。
- **地址派生**:`email_for_agent(agent_id, domain, system_name, default_aliases)` — 默认名归一(各平台默认名 → `agent`);非法字符 `→ _`;共享域 `{base}.{system_name}@{domain}`,独立域 `{base}@{domain}`。

### 3.5 生命周期与安装

- **事件总线平台**(Hermes):挂 `profile_created/deleted` 钩子,自动注册/注销。
- **无事件总线平台**(OpenClaw/DeerFlow):CLI 包装注册/注销链;DeerFlow 另以 reconcile 对账兜底。
- **安装补充注册**(确保安装后所有已有 agent 地址可用):

| 平台 | 补充注册 | 路由同步 | 其他 |
|------|----------|----------|------|
| Hermes | register_profiles.py(全量) | gateway.sh 路由段 | install-tools + configure |
| OpenClaw | register_agent.py --all | 注册链内 | install-skill |
| DeerFlow | register_agent.py --all | 注册链内 | install-inbound.sh(入站补丁)+ skill/mcp |

- **补丁安装**:DeerFlow 入站为进程内预处理,需在 deer-flow 仓实施代码补丁(`backend/app/gateway/routers/agentmail_inbound.py` + app.py import/include_router 两锚点)——`scripts/deer-flow/install-inbound.sh` 幂等安装(cmp 跳过拷贝 + 双锚点 patch + py_compile 校验),安装后重启 8001 生效。

---

## 4. 结果(实例示范,三平台生产运行)

### 4.1 Hermes

| 组件 | 位置 |
|------|------|
| 适配层 | `tools/hermes/agentmail_hermes.py`(注入点赋值 + 注册块) |
| 工具注册 | 6 邮件 + 5 board 工具 → `registry.register`(import 期执行) |
| 入站 | webhook preprocessor:`register_preprocessor("agentmail_gateway", core.process_inbound_mail)`(进程内) |
| 生命周期 | `profile_created/deleted` 钩子(事件总线) |
| 部署 | copy-deploy:install-tools.sh 拷贝 4 文件 → $HERMES_DIR/tools/,SKILL → profiles/{p}/skills/agentmail/ |
| 关键坑 | 每 profile 独立 webhook 端口,单入单出;webhook 会话需 `platform_toolsets.webhook` 含 agentmail(否则无 send_mail) |

### 4.2 OpenClaw

| 组件 | 位置 |
|------|------|
| 适配层 | `tools/openclaw/amail_base.py`(`PERSONA_SUPPORTED=False` + 身份注入 + 转发共享函数) |
| 工具 | `tools/amail_mcp_server.py` 共享 MCP stdio server(`amail__*`,newline-JSON 帧协议) |
| 入站接收端 | `tools/openclaw/amail_openclaw_bridge.py` — HTTP `/hook`:验签 → set_agent_context → process_inbound_mail → dispatch_to_hooks(POST 127.0.0.1:18789/hooks/agent,agentId/sessionKey 区分多 agent) |
| 生命周期 | CLI 包装:`bin/register_agent.py`(agents list 发现 → 注册链 → bridge 路由注册) |
| 部署 | repo-direct(改立即生效);skill 经 install-skill.sh 拷贝 |
| 关键坑 | 接收端必须先 set_agent_context 再调 process_inbound_mail;set_agent_context 需 export AMAIL_AGENT_EMAIL(否则日志落 default.log) |

### 4.3 DeerFlow

| 组件 | 位置 |
|------|------|
| 适配层 | `tools/deer-flow/amail_base.py`(`PERSONA_SUPPORTED=False` + 身份注入 `deerflow/{ver}`) |
| 工具 | `tools/amail_mcp_server.py` 共享 MCP stdio server |
| 入站 | **进程内预处理**:deer-flow `backend/app/gateway/routers/agentmail_inbound.py` — `POST /agentmail/inbound`:验签 → process_inbound_mail → ping/pong 拦截 → `start_run` 投递(thread=uuid5("amail", email),assistant_id 读 agentmail.json) |
| 生命周期 | `scripts/deer-flow/reconcile.py`(对账)+ register_agent.py(即时注册) |
| 部署 | 共享布局(~/.agentmail/systems/{sid}/{cleaned_addr}/agentmail.json);入站补丁经 install-inbound.sh 幂等安装(上游仓保持干净) |
| 关键坑 | 8001 进程内 import amail_base 需 sys.path 注入(router 模块级);Pyright 误报(运行时路径已插入) |

### 4.4 对比(新系统选型参考)

| 维度 | Hermes | OpenClaw | DeerFlow |
|------|--------|----------|----------|
| 入站模型 | 单入单出(每 profile 独立端口,进程内预处理) | 单入多出(一个 hooks 端点路由多 agent,外部预处理进程) | 进程内预处理(8001 router,start_run 投递) |
| 工具暴露 | 进程内 registry | MCP stdio server(amail__ 前缀) | MCP stdio server(amail__ 前缀) |
| 部署 | copy-deploy(改后重跑 install) | repo-direct(改立即生效) | 适配层 repo-direct;预处理在 deer-flow 仓(补丁安装 + 重启) |
| 生命周期 | 事件总线(profile_created/deleted) | CLI 包装 | reconcile 对账 |
| persona | 全能力(PERSONA_SUPPORTED=True) | 无(False) | 无(False) |

---

## 5. 新 agent 系统对接清单(8 步)

1. **建共享层引用**:import `tools/agentmail_base` / `agentmail_tools` / `agentmail_board`(sys.path 插入 tools/);不复制、不改共享代码。
2. **写适配层** `tools/<system>/<adapter>.py`:平台三件事(配置源 / personas 或 `PERSONA_SUPPORTED=False` / 身份注入 `_AGENT_IDENTITY_OVERRIDE = "platform/ver"`)+ 赋值注入点(§3.4)。
3. **暴露工具**:进程内 registry(照 Hermes)或直接复用共享 `tools/amail_mcp_server.py`(平台无关,按共享布局落 agentmail.json 即可)。
4. **接入站**:接收端点先注入 agent 配置(set_agent_context 等价物)→ 验签 → `process_inbound_mail` → 未拦截投递原始 body;入站拉取复用 amail-bridge,不写新 poller。
5. **接生命周期**:有事件总线 → 挂钩子;无 → 包装 agents add/delete CLI 调共享注册/注销链。
6. **装 skill**:逐字拷贝 `skills/SKILL.md`(+ DESCRIPTION.md),零改写。
7. **注册到 CLI**:check_status.py `PLATFORMS` 注册表加 adapter(detect/list_agents/check_config/check_hook 四函数);install/uninstall 平台适配段加分支(含安装补充注册)。
8. **验收(双测铁律)**:`agentmail check` 全绿 → `agentmail ping` 三阶段闭环 → `agentmail welcome` 管理员收到 Re: 回复(带头 `X-Agentmail-Agent: {platform}/{version}`)。

---

## 6. 安全模型

- **最小权限 key**:每 agent 独立 api_key;SMTP auth.local 认证只接受 agent 自己的 key(无 admin_key 回退);ping_test 的 pending 轮询用 system scope admin_key。
- **指针唯一来源**:系统身份 = 指针文件;禁扫描、禁 env 覆盖、禁跨系统借用。
- **安全论证铁律**:分析攻击面与杠杆;只增复杂度不减少攻击面的缓解是伪优化。
- **出站自定义头白名单**:X-Agentmail-Agent / X-Board-Members / X-AMRelay-AutoReply 外发透传;X-Board-ID/Role 仅内转;_persona.* 内部专用。

---

## 7. 对接排障速查

| 症状 | 根因 |
|------|------|
| ping 永不回 pong | 前缀不一致(PONG_PREFIX 必须 `__amail_pong__:`);或接收端没走 process_inbound_mail 最后一步 |
| 入站断链(新 agent) | 注册后未调 register_bridge_route(路由表无条目) |
| webhook 会话收得到回不出 | profile `platform_toolsets.webhook` 缺 agentmail;或路由 skills 为空 |
| 日志落 agentmail.default.log | 独立进程没 set_agent_context / 没 export AMAIL_AGENT_EMAIL |
| bridge 转发 401 无限重试 | webhook_secret 与接收端配置不一致(注册时落盘值) |
| 入站富化跳过 | 接收端未先注入 agent 配置就调 process_inbound_mail |
| check 报系统缺失 | 指针文件缺 system_id;或读错了 home(profile 布局须 --agent-home) |
| MCP 连接挂起 | 帧协议不对:MCP SDK 用 newline JSON,不是 Content-Length |
| agent 回复带错平台身份 | 适配层未注入 _AGENT_IDENTITY_OVERRIDE(目录检测误判) |

---

## 8. 已退役/勿用

- **amail-poll.py**:已删除。入站 pull 统一走 amail-bridge(单进程多系统)。
- **amail_deerflow_bridge.py**(8798):已退役。DeerFlow 入站为 8001 进程内预处理。
- **integrate.sh / uninstall.sh / bridge-ctl.sh**:已被 `agentmail install/uninstall/bridge` 取代。
- **amail_gateway.json 旧名**:统一 `agentmail_gateway.json`,无兼容别名。
- **--agent-type 参数**:平台事实推断,禁止手动指定。
- **mode / bridge_port 配置项**:webhook_host 三态表达 push/pull;接收端点端口在 webhook_url。
- docs/ 目录:本地草稿区,不版本化;正式文档落仓库根(本文件 + README/MAINTENANCE)。
