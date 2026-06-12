# 二次审计报告 — 全模块

## 审计范围

本次会话所有修改的模块：

| 仓库 | 文件 | 改动类型 |
|------|------|---------|
| amail-bridge | config.rs, admin.rs, router.rs, main.rs, push.rs | Phase 1a + code review fixes |
| amail-gateway | storage.rs, factory.rs, types.rs, http.rs, webhook.rs | Phase 1b |
| amail-advanced | activation.rs, server.rs | Phase 1b |
| agentmail | amail_tools.py, integrate.sh, docs/*.md | Phase 2-4 |

---

## 审计结果：全模块通过

### amail-bridge

| 文件 | 审计项 | 状态 |
|------|--------|------|
| config.rs | `hostname`/`tls_*` 提升到顶层，`is_ip_address` 正确 | ✅ |
| config.rs | `has_tls()` 过滤 IP | ✅ |
| config.rs | `is_dual_port()` 过滤 IP | ✅ (已修复) |
| config.rs | `validate()` 引用 `self.hostname`/`self.tls_*` | ✅ |
| config.rs | `load()` env override: `cfg.hostname` 非 `cfg.push.hostname` | ✅ |
| config.rs | TOML 向后兼容：`[push]` section 下无 `hostname` 等字段 | ✅ |
| admin.rs | `AdminState` 含 `config: BridgeConfig` | ✅ |
| admin.rs | `create_route` 返回 `{"status":"ok","webhook_url":"..."}` | ✅ |
| admin.rs | 协议判断：IP→http, domain→https | ✅ (已修复) |
| admin.rs | IP whitelist middleware | ✅ |
| router.rs | `ProfileRouter::new` 仅取 `routes_file` | ✅ |
| router.rs | `load_from_file()` 两遍扫描逻辑 | ✅ |
| router.rs | `update_route`/`remove_route` 无读-改-写竞争 | ✅ (已修复) |
| router.rs | `write_current_routes()` 直接从内存写 | ✅ |
| router.rs | `start_routes_watcher` 仅监听 routes file | ✅ |
| main.rs | `ProfileRouter::new(routes_file)` 1 个参数 | ✅ |
| main.rs | `load_from_file()` 启动时载入 | ✅ |
| main.rs | `start_routes_watcher` | ✅ |
| push.rs | 无 `push.hostname`/`push.tls_*` 残留引用 | ✅ |
| tests | 85/85 pass | ✅ |

### amail-gateway

| 文件 | 审计项 | 状态 |
|------|--------|------|
| storage.rs | DDL 无 `delivery_mode` 列 | ✅ |
| storage.rs | ALTER TABLE migration 块已删除 | ✅ |
| storage.rs | `system_domain_row` 无 `r.get(8)` | ✅ |
| storage.rs | `SystemDomainRecord` 无 `delivery_mode` 字段 | ✅ |
| storage.rs | `insert_system_domain` 签名+SQL+params 已修正 | ✅ |
| storage.rs | `update_system_domain` 签名+SQL+params 已修正 | ✅ |
| storage.rs | 3 条 SELECT SQL 无 `delivery_mode` | ✅ |
| factory.rs | `create_domain`/`update_domain` 签名无 `delivery_mode` | ✅ |
| types.rs | 3 个 request struct 无 `delivery_mode` 字段 | ✅ |
| http.rs | 3 个 handler 调用无 `req.delivery_mode` 传参 | ✅ |
| webhook.rs | `d.delivery_mode == "pull"` → `webhook_url.is_empty()` | ✅ |
| app 测试 | 85/85 pass | ✅ |

### amail-advanced

| 文件 | 审计项 | 状态 |
|------|--------|------|
| activation.rs | `create_domain()` 调用少 1 个参数 | ✅ |
| server.rs | `create_domain()` 调用少 1 个参数 | ✅ |
| build | `cargo build` clean | ✅ |

### agentmail

| 文件 | 审计项 | 状态 |
|------|--------|------|
| amail_tools.py | `_auto_register_email`: `webhook_host=""` → local, 非空 → bridge API | ✅ |
| amail_tools.py | bridge API 调用用 `urllib.request`（无新增依赖） | ✅ |
| amail_tools.py | `_auto_activate_profile`: 端口变更检测 + bridge 路由更新 | ✅ |
| amail_tools.py | `_inject_profile_config`: 含 `_wh_port` | ✅ |
| amail_tools.py | `_GatewayClient.register_email`: 无 `delivery_mode` 参数 | ✅ |
| amail_tools.py | `_load_gateway_config`: 无 `bridge_url` legacy migration | ✅ |
| amail_tools.py | parse + import OK | ✅ |
| integrate.sh | Step 5.5 整段删除 | ✅ |
| integrate.sh | `_is_local_gateway` 入口判断 | ✅ |
| integrate.sh | 无 `delivery_mode`/`bridge_url` 写入 | ✅ |
| integrate.sh | 无 `BRIDGE_DEPLOY`/`BRIDGE_MODE`/`BRIDGE_NEEDED` | ✅ |
| integrate.sh | bash -n syntax OK | ✅ |
| docs | 无 `delivery_mode`/`bridge_url` 残留 | ✅ |

---

## 跨模块一致性检查

| 检查项 | 结果 |
|--------|------|
| `webhook_url` 空串判 pull | gateway `webhook.rs:210` ✅ 与 bridge `create_route` 返回 `""` ✅ 对齐 |
| `webhook_url` 传值 | `_auto_register_email` → gateway `register_email` 透传 ✅ |
| bridge API 协议 | config `is_ip_address` → admin.rs 协议判断 ✅ |
| `_wh_port` 持久化 | `_auto_register_email` 写入 → `_auto_activate_profile` 读取 ✅ |
| `webhook_host` 语义 | integrate.sh `_is_local_gateway` 判断 `""` ←→ `_auto_register_email` 读取 `""` 直连 ✅ |
| TOML 配置格式 | `addr`/`hostname`/`mode` 顶层字段，`[push]` 仅剩 `allowed_ips`/`blacklist_ips`/`rate_limit`/`body_limit_mb`/`sites` ✅ |

## 结论

所有模块通过审计，无新增问题。4 个仓库均已编译通过并通过测试。
