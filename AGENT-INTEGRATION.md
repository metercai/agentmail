# AgentMail Integration Guide — 对接架构与实例示范

> 状态:定稿(2026-08-18,经 agentmail 深度审计固化)
> 用途:后续任何 agent 系统对接 AgentMail 的第一参照文档。
> 权威代码:`tools/`(共享核心 + 平台适配)、`bin/`(运行时)、`scripts/`(CLI 层)、`skills/`(安装源)。
> 本文件随仓库版本化;`docs/` 目录为本地草稿区(gitignore),不入库。

---

## 1. 总体架构

AgentMail = 云端 **amail-gateway**(Rust 邮件网关)+ 本机 **amail-bridge**(Rust 拉取器)+ 各 agent 系统的**适配层**(Python)。

```
                        云端 (46.17.41.218 / 或自建)
   ┌─────────────────────────────────────────────┐
   │ amail-gateway  SMTP 收信 → 清洗/富化 → 入站队列 │
   │                HTTP API (send/contacts/...)  │
   │                A2A Board 引擎                │
   └──────────┬──────────────────────────▲────────┘
              │ pending 轮询              │ HTTP API
   ┌──────────▼──────────┐   ┌───────────┴──────────┐
   │ amail-bridge (本机)  │──►│ agent 适配层 (本机)    │
   │ 单进程多系统拉取      │   │ 共享核心 + 平台注入     │
   │ 2s 轮询 /pending     │   │ process_inbound_mail  │
   │ 按路由表全 URL 转发   │   │ → 调用 agent 处理邮件   │
   └─────────────────────┘   └───────────▲──────────┘
                                         │ send_mail 出站
                                         ▼
                                云端 HTTP API → SMTP 投递
```

**分层职责(铁律,用户定调)**:

| 层 | 位置 | 职责 | 修改影响 |
|----|------|------|----------|
| 共享核心(业务逻辑) | `tools/agentmail_base.py`、`agentmail_tools.py`、`agentmail_board.py` | 入站预处理链、ping/pong、地址派生、注册/注销链、6 邮件工具实现、board 工具 | 一次修改 → 所有 agent 系统 |
| 平台适配(独立) | `tools/hermes/`、`tools/openclaw/` | 配置源、persona 开关、身份注入、工具注册、入站接收端 | 只影响本平台 |
| 运行时 | `bin/register_agent.py`、`deregister_agent.py` | agent 生命周期(注册/注销) | 平台相关 |
| CLI 层 | `scripts/agentmail`(10 子命令)+ `scripts/gateway_api.py`(共享客户端) | 安装/检查/测试/卸载/运维 | 通用 |
| 安装源 | `skills/SKILL.md` + `DESCRIPTION.md` | 通用邮件处理技能(逐字拷贝到各平台) | 通用 |

**共享代码只进 `tools/` 顶层,禁止跨平台引用**:新系统不得 import 另一个系统的目录
(`tools/openclaw/` 曾 import `tools/hermes/` 被拒,已提升为共享)。平台适配只做三件事:
① 平台实现(配置源/persona/身份)② 赋值注入点 ③ 注册(工具/预处理/生命周期钩子)。

---

## 2. 共享核心(对接必读)

### 2.1 注入点(agentmail_base / agentmail_tools 模块级变量)

适配层 import 共享核心后**赋值这些变量**,共享代码即用平台实现:

| 注入点 | 含义 | Hermes 实现 | OpenClaw 实现 |
|--------|------|-------------|---------------|
| `_CONFIG_LOADER` | agent 配置加载 `() -> Optional[dict]` | `_load_profile_config()` | `_openclaw_profile_config()`(经 set_agent_context) |
| `_PROFILE_DIR_RESOLVER` | profile/agent 目录 `() -> Optional[str]` | `_resolve_profile_dir()` | `_openclaw_profile_dir()` |
| `_PERSONAS_PROVIDER` | personas 配置 `() -> dict` | `_list_personas()` | 无(persona 关闭) |
| `_SOUL_PROVIDER` / `_SKILLS_PROVIDER` | board 上下文 SOUL/skills | `_read_soul_md()` / `_read_skills()` | 无 |
| `_BOARD_GATEWAY_SINK` | board 网关注册回调 | `_register_board_gateway()` | `_register_board_gateway()` |
| `PERSONA_SUPPORTED` | 能力开关(默认 True) | `True` | `False`(归一基础地址) |
| `_AGENT_IDENTITY_OVERRIDE`(tools) | 出站身份 header `X-Agentmail-Agent` | 不设(目录检测) | `f"openclaw/{ver}"`(避免目录误判) |
| `_PERSONA_NAME_PROVIDER`(tools) | 当前 persona 名 | `_hermes_persona_name()` | 不设 |

**跨模块名已自解析**(2026-08-14 后):`agentmail_base` 在函数级
`from agentmail_tools import _GatewayClient / store_inbound_message / _log_amail`,
适配层**不再注入跨模块名**。board 凭据存储 `_store_board_credential` 是共享默认实现。

### 2.2 入站单一入口(中间链铁律)

**所有平台、所有入站路径(push 直推 / bridge pull 转发)调用同一个函数**:

```
process_inbound_mail(payload, headers)
  1. preprocess_mail_payload()   # 身份 → persona → 富化 → 附件落盘 → 存储
  2. 最后一步 handle_ping_pong() # ping/pong 拦截(全链走完才回 pong)
     → 拦截返回 None → 接收端 200 吞掉,不触发 agent
```

- ping/pong 拦截必须在**调用 agent 前的最后一刻**(用户纠正两次):pong 只在全链路
  正常时回复,最大化 E2E 验证。
- 未拦截 → 接收端把**原始 body**(非富化产物)投递给 agent 运行时。
- 共享实现细节:`send_pong` 经 `_CONFIG_LOADER` 解析配置走 `send_mail`;
  日志统一 `~/.agentmail/logs/agentmail.{cleaned_addr}.log`。

### 2.3 地址派生(全系统统一)

```
email_for_agent(agent_id, domain, system_name, default_aliases)
```

- 默认名归一:**各系统自己的默认名** → `agent`(Hermes 传 `("default",)`,
  OpenClaw 传 `("main",)`;互不替换)。
- 非法字符清洗:`.` 及其余非 atext-no-dot → `_`(无条件,gateway 点规则是唯一事实标准);
  空结果 → `agent`。
- 共享域:`{base}.{system_name}@{domain}`;非共享域:`{base}@{domain}`。

### 2.4 注册/注销链(公共,幂等)

```
register_agent_email(client, system_id, email, webhook_url, webhook_secret,
                     manager_address) -> {"api_key", "activation_code"}
deregister_agent_email(client, system_id, email, manager_address) -> {api_key, domain, whitelist}
```

- client 必须是 `agentmail_tools._GatewayClient`(全方法集);`scripts/gateway_api.GatewayClient`
  太薄,仅 CLI 安装链用。
- manager 白名单 + domain_addr_meta 由**网关 register_address 自动创建**——Python 侧不得手动补。
- 业务语义只改一处(共享链),平台脚本是薄调用者。

### 2.5 身份模型

- **1 agent = 1 amail 地址**;每个 agent 独立 api_key(gateway send.rs 强制
  sender == key.email_address,身份隔离服务端强制)。
- **系统身份 = 指针文件唯一来源**:Hermes `profiles/{name}/.agentmail`,
  OpenClaw `~/.openclaw/.agentmail`(JSON: system_id + email)。
  禁 env 覆盖、禁目录扫描、禁跨系统借用。
- 配置文件名唯一:`agentmail_gateway.json`(读写两侧统一,无兼容别名)。

---

## 3. CLI 契约(scripts/agentmail)

**命令名冲突警告**:`~/.local/bin/agentmail` 是 Hermes 启动器,repo 的 CLI 只能经
仓库根 `./agentmail` 运行,不得把 scripts/ 加进全局 PATH。

子命令(字母序,10 个):

| 子命令 | 职责 |
|--------|------|
| `bridge` | 本机 bridge 维护:无参=状态;`--system-id` 重刷路由;`--restart` 单实例重启 |
| `check` | 全链路状态检查(L1 gateway/L2 bridge/L3 agent 配置/L4 hook/L5 ping-pong) |
| `domain` | 查看/创建系统域名(list 默认 / `--add DOMAIN`) |
| `install` | 非交互安装(激活→domain 预置→bridge 部署→平台适配) |
| `mailname` | 默认主 agent 名映射查看/修改(hermes default→agent;openclaw main→agent) |
| `ping` | ping-pong 闭环测试(只信 agent 侧三阶段日志事件) |
| `reset` | 重置配置(admin-key 路径,业务字段零变化) |
| `stats` | 本机对接状态(系统/agent/邮件统计,只读) |
| `uninstall` | 卸载(网关注销 + 平台清理 + 本地数据) |
| `welcome` | welcome 端到端测试(含 LLM,唯一验收) |

**平台推断(无 --agent-type)**:`--home` 目录特征(hermes-agent/profiles = hermes;
openclaw.json = openclaw)→ 配置 system_home 反查 → 自动探测指针。用户禁止手动指定平台。

**.env 自动加载**:CLI 参数 > shell env > .env > 内置默认。.env 键:AMAIL_URL /
AMAIL_ADMIN_KEY / AMAIL_PRODUCT_CODE / AMAIL_MANAGER_ADDRESS / AMAIL_SYSTEM_NAME /
AMAIL_DOMAIN / AMAIL_SAVE_SNAPSHOTS / AMAIL_WEBHOOK_HOST。
install 全非交互:新系统激活 → 从 setup_system JSON stdout 取 server 分配的 system_id →
domain 预置/创建 → deploy_bridge → 平台适配。

**验收标准(双测铁律)**:对接成功 = `agentmail ping` + `agentmail welcome` 双测均过。
ping 验证链路不含 LLM(三阶段日志事件 ping_intercepted→pong_sent→pong_returned);
welcome 是唯一含真实 LLM 的端到端验证(管理员收到 agent 的 Re: 回复)。

---

## 4. 实例示范

### 4.1 Hermes(参考实现,生产运行中)

| 组件 | 位置 |
|------|------|
| 适配层 | `tools/hermes/agentmail_hermes.py`(1079 行,注入点赋值 + 注册块) |
| 工具注册 | 6 邮件工具(send_mail/manage_contacts/contact_profile/set_contact_profile/email_summary/set_email_summary)+ 5 board 工具(a2a_*)→ `registry.register`(import 期执行) |
| 入站 | webhook preprocessor:`register_preprocessor("agentmail_gateway", core.process_inbound_mail)`(gateway 进程 import 适配层即注册) |
| 生命周期 | `register_profile_hook("profile_created", _auto_register_email)` / `("profile_deleted", _auto_deregister_email)`(Hermes 事件总线) |
| 部署 | copy-deploy:install-tools.sh 拷贝 4 文件(tools 3 共享 + 适配层)→ `$HERMES_DIR/tools/`,SKILL → profiles/{p}/skills/agentmail/ |
| 关键坑 | 每 profile 独立 webhook 端口(8644+)单入单出;webhook 会话需 profile config `platform_toolsets.webhook` 含 agentmail(否则回退默认工具集无 send_mail);真实入站走 bridge pull → 本地 8646 接收 |

### 4.2 OpenClaw(第二实例,生产运行中)

| 组件 | 位置 |
|------|------|
| 适配层 | `tools/openclaw/amail_base.py`(394 行,`_ab.PERSONA_SUPPORTED = False`、注入身份、转发共享函数) |
| 工具 | `tools/amail_mcp_server.py` — 共享 MCP stdio server(兜底,2026-08-18 从 openclaw 提升),6 邮件工具 + board 工具暴露为 `amail__*`;**newline-delimited JSON 帧协议(非 Content-Length)**;直接依赖共享核心,任何 agent 系统按共享布局落 agentmail.json 即可复用 |
| 入站接收端 | `tools/openclaw/amail_openclaw_bridge.py` — HTTP 接收 `/hook` 与 `/webhooks/amail-inbound`:HMAC 验签 → set_agent_context → process_inbound_mail → dispatch_to_hooks |
| 生命周期 | CLI 包装(openclaw 无 agent 事件总线):`bin/register_agent.py`(openclaw agents list 发现 → 注册链 → bridge 路由注册) |
| 部署 | repo-direct:tools/openclaw/*.py 直接运行,改立即生效;skill 经 install-skill.sh 拷贝 |
| 关键坑 | 接收端必须**先 set_agent_context 再调 process_inbound_mail**(否则富化跳过);set_agent_context 需 export AMAIL_AGENT_EMAIL(否则日志落 default.log) |

### 4.3 DeerFlow(第三实例,生产运行中;2026-08-18 重构:预处理并入本地 gateway)

| 组件 | 位置 |
|------|------|
| 适配层 | `tools/deer-flow/amail_base.py`(注入点赋值 + `PERSONA_SUPPORTED = False` + 身份注入 `deerflow/{ver}` + 转发共享函数) |
| 工具 | `tools/amail_mcp_server.py`(共享 MCP stdio server,`amail__*` 前缀;MCP server 提升为共享兜底后,DeerFlow 同 OpenClaw 复用) |
| 入站 | **进程内预处理(仿 Hermes,2026-08-18 重构)**:deer-flow `backend/app/gateway/routers/agentmail_inbound.py` — `POST /agentmail/inbound`:HMAC 验签(per-address webhook_secret)→ 共享 `process_inbound_mail`(import amail_base 适配层注入)→ ping/pong 拦截 → 未拦截 `start_run` 内部投递(thread=uuid5("amail", email),assistant_id 读 agentmail.json) |
| 生命周期 | `scripts/deer-flow/reconcile.py`(对账为主)+ register_agent.py(即时注册);webhook_url = 本地 gateway 接收端点(`http://127.0.0.1:8001/agentmail/inbound`) |
| 部署 | 依赖 agentmail 仓库共享布局(~/.agentmail/systems/{sid}/{cleaned_addr}/agentmail.json,env `AMAIL_REPO` 可指仓库路径);旧独立接收进程 `amail_deerflow_bridge.py`(8798)已退役删除 |
| 关键坑 | 8001 进程内 import amail_base 需 sys.path 注入(router 模块级);Pyright 报 import 无法解析是误报(运行时路径已插入) |

### 4.4 对比(新系统选型参考)

| 维度 | Hermes | OpenClaw | DeerFlow |
|------|--------|----------|----------|
| 入站模型 | 单入单出(每 profile 独立端口) | 单入多出(一个 hooks 端点路由多 agent) | **进程内预处理**(gateway 内 /agentmail/inbound,start_run 投递;仿 Hermes) |
| 工具暴露 | 进程内 registry 注册 | MCP stdio server(amail__ 前缀) | MCP stdio server(amail__ 前缀) |
| 部署 | copy-deploy(改后须重跑 install) | repo-direct(改立即生效) | 适配层 repo-direct;预处理在 deer-flow 仓(改后重启 8001) |
| 生命周期事件 | 有事件总线(profile_created/deleted) | 无 → CLI 包装 | 无 → reconcile 对账 |
| persona | 全能力(PERSONA_SUPPORTED=True) | 无(False,归一基础地址) | 无(False,归一基础地址) |

---

## 5. 新 agent 系统对接清单(8 步)

1. **建共享层引用**:import `tools/agentmail_base` / `agentmail_tools` /
   `agentmail_board`(sys.path 插入 tools/);不复制、不改共享代码。
2. **写适配层** `tools/<system>/<adapter>.py`:
   - 实现平台三件事:配置源 / personas(或设 `PERSONA_SUPPORTED=False`)/
     身份注入(`_AGENT_IDENTITY_OVERRIDE = "platform/ver"`)
   - 赋值注入点(见 §2.1);确认适配层转发所有消费方用到的共享函数名
     (漏转发 = 运行时 AttributeError,verify 必须**实际调用**消费者函数而非 grep)。
3. **暴露工具**:进程内 registry(照 Hermes)或 **MCP server(直接复用共享 `tools/amail_mcp_server.py`**——兜底服务,平台无关,按共享布局落 agentmail.json 即可,`AMAIL_AGENT_ID` env 指定 agent);工具名保持 Hermes 名(send_mail 等),MCP 可加平台前缀。
4. **接入站**:接收端(HTTP 端点或 webhook preprocessor)先注入 agent 配置
   (set_agent_context 等价物)→ 调 `process_inbound_mail` → 未拦截则投递原始 body。
   入站拉取**默认复用 amail-bridge**(`[pull].systems` 数组加系统条目),
   **不要写新 poller**(amail-poll.py 已退役删除)。
5. **接生命周期**:有事件总线 → 挂 profile_created/deleted 钩子;
   无 → 包装 agents add/delete CLI 调共享注册/注销链。
6. **装 skill**:逐字拷贝 `skills/SKILL.md`(+ DESCRIPTION.md)到平台 skills 目录,
   **零改写**;SKILL 是通用规范,不是平台专属。
7. **注册到 CLI**:check_status.py `PLATFORMS` 注册表加 adapter
   (detect/list_agents/check_config/check_hook 四函数)→ L1/L2/L5 通用检查零改动;
   需要时给 CLI 加平台分支(install/uninstall 的平台适配段)。
8. **验收(双测铁律)**:`agentmail check` 全绿 →
   `agentmail ping` 三阶段日志闭环 → `agentmail welcome` 管理员收到 Re: 回复
   (带头 `X-Agentmail-Agent: {platform}/{version}`)。

---

## 6. 安全模型(对接时必须遵守)

- **最小权限 key**:每个 agent 独立 api_key;SMTP auth.local 认证只接受
  **agent 自己的 key**(无 admin_key 回退);ping_test 的 pending 轮询用 system
  scope admin_key(API 权限域分离,一个 key 不干两类事)。
- **指针唯一来源**:系统身份 = 指针文件;禁扫描、禁 env 覆盖、禁跨系统借用。
- **安全论证铁律**:"权限高≠无风险"——必须分析攻击面与杠杆;只增复杂度不减少
  攻击面的缓解是伪优化(会被拒)。
- **出站自定义头白名单**:X-Agentmail-Agent / X-Board-Members / X-AMRelay-AutoReply
  外发透传;X-Board-ID/Role 仅内转;_persona.* 内部专用。

---

## 7. 对接排障速查

| 症状 | 根因 |
|------|------|
| ping 永不回 pong | 前缀不一致(PONG_PREFIX 必须 `__amail_pong__:`);或接收端没走 process_inbound_mail 最后一步 |
| webhook 会话收得到回不出 | profile `platform_toolsets.webhook` 缺 agentmail(回退默认工具集无 send_mail);或路由 skills 为空 |
| 日志落 agentmail.default.log | 独立进程没 set_agent_context / 没 export AMAIL_AGENT_EMAIL |
| bridge 转发 401 无限重试 | webhook_secret 与接收端配置不一致(注册时落盘值) |
| 入站富化跳过("preprocessing skipped") | 接收端未先注入 agent 配置就调 process_inbound_mail |
| check 报系统缺失 | 指针文件缺 system_id;或读错了 home(profile 布局须 --agent-home) |
| MCP 连接挂起 | 帧协议不对:MCP SDK 用 newline JSON,不是 Content-Length |
| agent 回复带错平台身份 | 适配层未注入 _AGENT_IDENTITY_OVERRIDE(目录检测误判) |

---

## 8. 已退役/勿用(2026-08-18 定稿)

- **amail-poll.py**:已删除。入站 pull 统一走 amail-bridge(单进程多系统)。
- **integrate.sh / uninstall.sh / bridge-ctl.sh**:已被 `agentmail install/uninstall/bridge` 取代。
- **amail_gateway.json 旧名**:统一 `agentmail_gateway.json`,无兼容别名。
- **--agent-type 参数**:平台事实推断,禁止手动指定。
- docs/ 目录:本地草稿区,不版本化;正式文档落仓库根(本文件 + README/MAINTENANCE)。
