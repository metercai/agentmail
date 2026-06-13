# amail 项目 — 任务状态总览

## 项目概述

amail 邮件网关生态，含 4 个仓库：
- **amail-gateway** — base 版（开源）
- **amail-advanced** — 高级版（闭源，依赖 gateway 库）
- **amail-bridge** — pull 模式桥接（闭源）
- **agentmail** — 集成脚本 + 设计文档

## 一、已完成任务

### 1.1 Webhook 配置链重构（Phase 1-5）

**目的**：消除 delivery_mode 冗余字段，统一 push/pull 判定

**涉及仓库**：gateway + advanced + bridge + agentmail

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1a | bridge hostname/TLS 提升，auto-discovery 删除 | ✅ |
| 1b | delivery_mode 从 7 文件删除 | ✅ |
| 2 | amail_tools.py 删除 delivery_mode/bridge_url | ✅ |
| 3 | integrate.sh 删除 BRIDGE_DEPLOY 等 | ✅ |
| 4 | 文档更新 | ✅ |
| 5 | 全栈验证（85/85 测试通过） | ✅ |

### 1.2 Bridge 代码审计修复

**目的**：修复竞态条件、协议判断、双端口

| 问题 | 修复 |
|------|------|
| create_route webhook_url 协议 | IP→http，域名→https |
| update/remove route 竞态 | write_current_routes() 直接写文件 |
| is_dual_port IP 守卫 | 仅 domain hostname 启用 dual-port |
| 二次审计 | 无新增问题 |

### 1.3 Pending TTL + Pull 性能优化

**目的**：自动清理过期 pending，优化 bridge 拉取性能

| 改动 | 说明 |
|------|------|
| WebhookConfig.pending_ttl_hours | 默认 72h，可配置 |
| cleanup_deliveries(ttl_hours) | 清理 pending+delivered |
| tokio::spawn 定时任务 | 每 ttl/2 小时执行 |
| Pull filter 预处理 | 域名→正则→精确地址三层吸收 |
| Bridge 域名上传 | 从 route 提取唯一域名 |

### 1.4 category/domain_addr 契约

**目的**：区分 platform/system/agent/bridge 四种 API key

| 契约 | domain_addr | 配额 |
|------|-------------|------|
| platform | "" | 否 |
| system | 裸域 | 否 |
| agent | 邮箱 | 是 |
| bridge | bridge.{uuid} | 否 |

### 1.5 Config 结构体拆分（base vs advanced）

**目的**：base 版（开源）不包含 advanced-only 配置项

**从 base 移除**：

| 移除项 | 原因 |
|--------|------|
| [acme] 整段 | 仅 advanced 有 ACME 自动证书 |
| [rate_limit] 整段 | base RateLimitChecker 是 no-op |
| dns.mx_override | base MxResolver 返回错误 |
| database.encryption | base 硬编码 true |
| relay.dkim_selector | base 不签名 |
| relay.dkim_private_key_path | base 不签名 |
| DnsHints 结构体 | only advanced edition populates |
| spf_policy | base SPF no-op |
| ptr_policy | base PTR no-op |

**AdvancedConfig 新建**：

```rust
pub struct AdvancedConfig {
    pub acme: AcmeConfig,
    pub rate_limit: RateLimitConfig,
    pub dns: DnsAdvancedConfig,
    pub relay: RelayAdvancedConfig,
    pub database: DatabaseAdvancedConfig,
}
```

**create_router 接口变更**：

```rust
// base edition (None = use default handler)
create_router(state, router_hook, None)

// advanced edition (Some = custom handler with DNS hints)
create_router(state, router_hook, Some(advanced_handler))
```

### 1.6 integrate.sh 模块化

**目的**：将 1100+ 行单文件分解为主脚本 + 子模块，删除 AUTO_MODE

| 文件 | 行数 |
|------|------|
| integrate.sh | 393（主流程） |
| lib/i18n.sh | 197（中英文字符串） |
| lib/helpers.sh | 42（step/info 函数） |
| lib/deploy-bridge.sh | 121（桥接部署） |
| lib/install-tools.sh | 63（工具安装） |
| lib/patch-webhook.sh | 24（webhook） |
| lib/patch-profiles.sh | 91（profile hooks） |
| lib/diagnostics.sh | 42（诊断） |
| lib/send-test.sh | 103（收发测试） |

### 1.7 deploy.sh 部署脚本

**位置**：`amail-gateway/deploy.sh`

**功能**：upload / start / stop / restart / status / logs / health / setup-systemd

**依赖**：`.env` + `.env.example` 配置

### 1.8 生产环境部署

**云主机**：46.17.41.218

| 组件 | 状态 |
|------|------|
| amail-advanced | systemd 运行中 |
| 端口 | 80(→443) + 443(HTTPS) + 25(SMTP) |
| ACME 证书 | amail.token.tm (Let's Encrypt) |
| DKIM | ✅ amail.token.tm |
| 附件存储 | /var/amail/attachments |
| 日志 | /var/log/amail-gateway.log |

## 二、进行中 / 待办任务

### 2.1 高级版 DNS 提示功能（P0）

**目的**：域名创建 API 响应返回 DNS 配置提示（MX/DKIM/DMARC/SPF记录）

**现状**：基础设施已就绪
- `create_router()` 接受 `domain_handler` 参数 ✅
- `create_system_domain` 改为 `pub` ✅
- AdvancedConfig 有 `relay.dkim_selector` 等字段 ✅

**待实现**：
- 创建 `advanced_create_system_domain` handler，调用 base handler 后 enrich 响应
- 从 AdvancedConfig 读取 relay hostname、DKIM selector 等
- 构造 DNS 提示 JSON
- 通过 `create_router(http_state, router_hook, Some(handler))` 传入

**涉及文件**：`amail-advanced/src/server.rs` + 新建 handler

### 2.2 域管理员权限收窄 + 域级 admin key（P1）

**目的**：域管理员不能创建其他域的 key；integrate.sh 使用域级 key 而非系统级 key

**设计文档**：`agentmail/design/DOMAIN-ADMIN-LOCKDOWN.md`

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 | create_api_key 加 require_domain_match | ✅ |
| 2 | Step 3 product_code 删除 step_fail | ✅ |
| 3 | bridge 部署迁至 Step 5a | ✅ |
| 4 | Step 5a 创建域级 key + 替换配置 | ✅ |
| 5 | verification | ✅ |

### 2.3 integrate.sh 桥接部署 + 域级 key（P2）

**目的**：integrate.sh Step 5a 创建域级 admin key 后写入 amail_gateway.json

**当前状态**：Step 5a 已添加但未完全验证

### 2.4 环境变量改名（P2）

**现状**：`AMAILRELAY_*` → `AMAILGW_*` ✅

**已精简**：从 24 个精简到 7 个核心资源 env var

## 三、仓库提交记录

### amail-gateway（最新 commit: ec64009）

```
ec64009 -> refactor: make create_system_domain pub for advanced reuse
e67099b -> cleanup: remove SPF + PTR verification blocks
edc0fc6 -> cleanup: remove DnsHints, spf_policy, ptr_policy
6c8450d -> refactor: create_router accepts optional domain_handler
81a38b4 -> fix: remove with_dns_hints from base http.rs
```

### amail-advanced（最新 commit: 1374eca）

```
1374eca -> refactor: pass None for domain_handler (DNS hints TBD)
b8d1093 -> step 8: wire AdvancedConfig into server
7c9ecf1 -> step 1: AdvancedConfig — empty shell structs
```

### amail-bridge（最新 commit: 4bb4f54）

```
4bb4f54 -> feat: PullConfig effective_key()
```

### agentmail（最新 commit: fee771b）

```
fee771b -> doc: base cleanup plan
c27f6d8 -> doc: Config struct split plan
```

## 四、设计文档

```
agentmail/design/
├── MASTER-PLAN.md                  — 全部阶段总览
├── REVISION-WEBHOOK-CHAIN.md       — webhook 链方案
├── INTEGRATED-VIEW.md              — 集成后全局视图
├── BRIDGE-CODE-REVIEW.md           — bridge 审计
├── SECOND-AUDIT.md                 — 二次审计
├── GATEWAY-BASE-AUDIT.md           — gateway 审计
├── BRIDGE-MULTI-KEY-PERF.md        — bridge 多 key + pull 性能
├── NEXT-PHASE.md                   — 待实施（已完成）
├── DOMAIN-ADMIN-LOCKDOWN.md        — 域管理员权限方案
├── CONFIG-SPLIT.md                 — Config 拆分方案
├── BASE-CLEANUP.md                 — base 清理方案
├── INTEGRATE-MODULAR.md            — 脚本模块化方案
├── INTEGRATE-SH-REVIEW.md          — integrate.sh 审计
├── DEPLOY-LAYOUT.md                — 部署目录结构
└── PHASE-{1A,1B,2,3,4-5}.md       — 分阶段实施指南
```

## 五、环境变量一览

```bash
AMAILGW_HTTP_ADDR           # HTTP 监听地址
AMAILGW_SMTP_ADDR           # SMTP 监听地址
AMAILGW_STORAGE_PATH        # 数据库路径
AMAILGW_RELAY_SMTP_SERVER   # 上游 SMTP
AMAILGW_RELAY_USERNAME      # SMTP 认证
AMAILGW_RELAY_PASSWORD      # SMTP 密码
AMAILGW_LOGGING_LEVEL       # 日志级别
```

## 六、关键架构决策

1. **Config 双解析**：base + advanced 从同一份 config.toml 解析，serde 各自忽略未知字段
2. **策略模式**：DkimSigner / InboundSecurity / MxResolver 等 trait 在 base 定义，base 提供 no-op impl，advanced 提供真实实现
3. **RouterHook**：用于添加额外路由，但不能 shadow 已有路由（axum 0.7 merge 限制）
4. **domain_handler**：用于替换 create_system_domain 路由处理函数，base 传 None，advanced 传自定义 handler
5. **env 优先级**：struct defaults → TOML → AMAILGW_* 环境变量
