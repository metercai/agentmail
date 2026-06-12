# Webhook 配置链路修订方案 — 代码审计报告

## 审计日期

2026-06-12

## 审计范围

对照 `/home/ubuntu/agentmail/design/REVISION-WEBHOOK-CHAIN.md` 与当前代码实现，逐项验证文档描述与实际代码的一致性。

---

## 审计结论

**文档设计方向正确，但低估了 `delivery_mode` 的改动范围，存在 3 处未覆盖的代码路径和 1 处错误描述。**

---

## 逐项审计

### 1.1 `delivery_mode` 冗余 — 改动范围严重不足

**文档描述**：5 个文件（webhook.rs、types.rs、http.rs、storage.rs DDL、可用性测试）

**实际影响范围**：34 处引用，涉及 **8 个文件**：

| 文件 | 影响点 | 文档覆盖 |
|------|--------|---------|
| `storage.rs:255` | DDL CREATE TABLE 含 `delivery_mode` 列 | ✅ |
| `storage.rs:346-350` | **ALTER TABLE ADD COLUMN migration（未覆盖）** | ❌ |
| `storage.rs:439` | `system_domain_row()` row mapper 第 8 列 | ❌ |
| `storage.rs:467` | 同上，`r.get(8)` | ❌ |
| `storage.rs:549-552` | `insert_system_domain()` 参数 + 默认值 | ❌ |
| `storage.rs:556` | INSERT SQL 含 `delivery_mode` 列 | ❌ |
| `storage.rs:562` | INSERT 后 `delivery_mode: dm` 赋值 | ❌ |
| `storage.rs:572` | SELECT SQL 含 `delivery_mode` 列 | ❌ |
| `storage.rs:584` | SELECT SQL 含 `delivery_mode` 列 | ❌ |
| `storage.rs:596` | SELECT SQL 含 `delivery_mode` 列 | ❌ |
| `storage.rs:605-611` | `update_system_domain()` 参数 + 默认值 | ❌ |
| `storage.rs:616` | UPDATE SQL 含 `delivery_mode = ?4` | ❌ |
| `factory.rs:74` | `create_domain()` 传 `delivery_mode` | ❌ |
| `factory.rs:112` | `update_domain()` 传 `delivery_mode` | ❌ |
| `types.rs:196,210,228` | 3 个 struct 含 `delivery_mode: Option<String>` | ✅ |
| `webhook.rs:210` | 判定 `d.delivery_mode == "pull"` | ✅ |
| `http.rs` | `register_address`/`create_system_domain` 传参 | ✅ |

**整改**：文档 3.1 节需重写，按功能模块（DDL、存储层、类型层、HTTP 层）分组说明，并补充 ALTER TABLE migration 的删除方法。

### 1.2 `bridge_url` — 已基本清理，遗留 1 处

**文档描述**：`bridge_url` 与 `webhook_host` 语义重叠

**实际状态**：`integrate.sh` 已无 `bridge_url` 写入。`amail_tools.py` 仅剩 2 行 legacy 迁移代码（`_load_gateway_config()` 中 `cfg["bridge_url"] → cfg["webhook_host"]`），代码注释写明"Legacy migration"。**无需额外改动。**

**建议**：在 Phase 2 做 `_auto_register_email` 重写时一并清理。

### 1.3 Step 4 与 Step 5.5 分离 — 确认存在

**文档描述**：两者强相关却分两步

**实际状态**：当前 Step 4 是 "basic configuration (snapshot + manager_address) + webhook 3 选项"，Step 5.5 是 "Bridge deployment"。Step 4 已做选择，Step 5.5 做部署和探测。文档主张合并，**代码尚未合并**。

**关键差异**：

| 变量 | 当前存在 | 文档要求 |
|------|---------|---------|
| `BRIDGE_DEPLOY` | ✅ | 删除 |
| `BRIDGE_MODE` | ✅ | 删除 |
| `BRIDGE_NEEDED` | ✅ | 删除 |
| Step 5.5 section | ✅ | 删除，合并到 Step 4 |
| `probe-webhook` 调用 | ✅（line 797） | 删除（bridge 模式固定 pull，不需探测） |

**整改**：文档 3.4 节描述正确，按文档实施即可。

### 1.4 Bridge 无路由注册反馈 — 确认存在

**文档描述**：`POST /api/v1/routes` 只返回 `"ok"`

**实际状态**：

- `create_route` handler（admin.rs:135）目前仅做 `state.router.update_route()` + 返回 `"ok"`
- `AdminState` 没有 `config` 字段，无法读取 `mode` 和 `addr`
- 需要的改动：`AdminState` 加 `config: BridgeConfig`，`create_route` 读 `state.config.mode` 和 `state.config.addr` 构造响应

**整改**：文档 3.2 节描述正确，按文档实施即可。

### 1.5 `probe-webhook` API 设计缺陷 — 确认存在

**文档描述**：探测不准确，应在部署阶段验证

**实际状态**：当前 probe-webhook 在 Step 5.5 的 bridge 模式下被调用（integrate.sh:797），用于探测 bridge 是否可达。文档设计为用 `GET /health` 替代（无副作用、本地可验），probe-webhook 端点保留但不再在集成流程中使用。

**可用性测试**：`availability_test.sh` 的 8.10a-d 仍然测试 probe-webhook（已改为 loopback rejection 测试）。文档 3.5 说"改为测试 bridge health 或删除"，**保留即可**——gateway 的 probe-webhook API 作为独立功能存在，不在集成流程中使用，但测试仍可覆盖它。

---

## 未覆盖的额外问题

### A. GATEWAY_URL is_local 判断缺失

**文档 3.3 设计**：`_auto_register_email` 中新增 `_is_local_url()` 函数，判断 gateway 是否本机

**当前代码状态**：**不存在此函数。** `integrate.sh` 中已有的 GATEWAY_URL localhost 判断（原 Step 5.5 的 `grep -qE "127.0.0.1|localhost|::1"`）在上轮改写中被移除。`_auto_register_email` 当前没有任何 GATEWAY_URL 本机判断。

**影响**：Phase 2 实施 `_auto_register_email` 重写时，需要同时实现 `_is_local_url()`。Phase 3 实施 `integrate.sh` 合并时，需要基于同一逻辑做 Step 4 的入口分叉。

### B. amail_bridge.toml 模板简化

**当前 Step 5.5 写入的 bridge.toml**（行 819-826）：

```toml
addr = "${BRIDGE_ADDR}"
mode = "push"
```

或 pull 模式加 `[pull]` section。

**合并后**：只保留 `addr` + `mode`（direct 模式 push，bridge 模式 pull），删除 `[push]` section。`internal` 模式不生成 bridge.toml（远端已有）。**文档未明确说明此变化。**

### C. `create_system_domain` handler 的 `delivery_mode` 参数

`create_system_domain`（http.rs）调 `factory.create_domain(..., delivery_mode)`，此参数来自请求体。文档只提到 `register_address`，但 `create_system_domain` 也要改。**文档 3.1 节表述不够精确。**

---

## 修正后的依赖关系（细化）

```
Phase 1（可并行）
  ├── 1a: amail-bridge admin.rs
  │        AdminState 加 config 字段
  │        create_route 响应改为 {"webhook_url":"..."}
  │        检测: cargo build + curl 验证
  │
  └── 1b: amail-gateway
           storage.rs: DDL 删 delivery_mode 列
                      删 ALTER TABLE ADD COLUMN migration
                      修改 system_domain_row（删第 8 列，调整列索引）
                      修改 3 个 SELECT SQL（删 delivery_mode 列）
                      修改 INSERT SQL（删 delivery_mode 列 + ?N 参数重编号）
                      修改 UPDATE SQL（删 delivery_mode = ?4）
                      修改 insert_system_domain() 签名（删 delivery_mode 参数）
                      修改 update_system_domain() 签名（删 delivery_mode 参数）
           factory.rs: create_domain() 签名删 delivery_mode 参数
                       update_domain() 签名删 delivery_mode 参数
           types.rs: 3 个 struct 删 delivery_mode 字段
           http.rs: register_address 删 delivery_mode 传参
                    create_system_domain 删 delivery_mode 传参
           webhook.rs: d.delivery_mode == "pull" → d.webhook_url.trim().is_empty()
           检测: cargo build --lib + 可用性测试 85/85

Phase 2（依赖 Phase 1）
  └── 2a: amail_tools.py
           _is_local_url() 新增
           _auto_register_email 重写（GATEWAY_URL 本机分支 + bridge API 分支）
           删除 delivery_mode 引用
           清理 bridge_url legacy 迁移代码
           检测: import OK + 集成脚本诊断

Phase 3（依赖 Phase 2）
  ├── 3a: integrate.sh Step 4 合并 + 简化
  │        GATEWAY_URL is_local 入口分叉
  │        3 选项流程（direct/internal/bridge）
  │        验证用 GET /health（非 probe-webhook）
  │        删除 BRIDGE_DEPLOY/BRIDGE_MODE/BRIDGE_NEEDED
  │        删除 probe-webhook 调用
  │        删除 delivery_mode 写入
  │        删除 bridge.toml [push] section
  │        检测: bash -n + 三种模式各跑一遍
  └── 3b: 可用性测试更新（可选，当前 probe-webhook 测试保留即可）

Phase 4
  └── 4a: 文档更新

Phase 5（验证）
  └── 5a: 全部编译 + 可用性测试 85/85 + 集成脚本全流程
```

---

## 文档 3.1 节重写建议

当前 3.1 节只说"DDL 中删除 delivery_mode 列"，需要细化为：

### 3.1.1 存储层 changes（`storage.rs`）

- DDL CREATE TABLE：删 `delivery_mode  TEXT NOT NULL DEFAULT 'webhook'`
- ALTER TABLE ADD COLUMN migration：删整个 migration（行 346-350）
- `system_domain_row` row mapper：删 `r.get(8)`，调整后续列索引（如有）
- `insert_system_domain()` 签名：删 `delivery_mode: Option<&str>` 参数
- `insert_system_domain()` 实现：删 `let dm = ...`，INSERT SQL 删 `delivery_mode` 列和 `?6` 参数
- `update_system_domain()` 签名：删 `delivery_mode: Option<&str>` 参数
- `update_system_domain()` 实现：删 `let dm = ...`，UPDATE SQL 删 `delivery_mode = ?4`
- 3 个 SELECT SQL：删 `delivery_mode` 列名
- `SystemDomainRecord` struct：删 `delivery_mode: String` 字段

### 3.1.2 工厂层 changes（`factory.rs`）

- `create_domain()` 签名：删 `delivery_mode: Option<&str>` 参数
- `update_domain()` 签名：删 `delivery_mode: Option<&str>` 参数

### 3.1.3 类型层 changes（`types.rs`）

- `RegisterAddressRequest`：删 `delivery_mode: Option<String>`
- `CreateSystemDomainRequest`：删 `delivery_mode: Option<String>`
- `UpdateSystemDomainRequest`：删 `delivery_mode: Option<String>`

### 3.1.4 HTTP 层 changes（`http.rs`）

- `register_address()`：删 `req.delivery_mode.as_deref()` 传参
- `create_system_domain()`：删 `req.delivery_mode.as_deref()` 传参

### 3.1.5 判决层 changes（`webhook.rs`）

- `d.delivery_mode == "pull"` → `d.webhook_url.as_deref().map_or(true, |u| u.trim().is_empty())`

### 3.1.6 检测方法

- `cargo build --lib` 编译通过
- 可用性测试 85/85 通过
