# Webhook 配置链后续改进方案

## 1. 配额修复：引入 category="agent"

### 1.1 现状

所有通过 API 创建的 key 默认 `category="system"`。agent、域管理员、bridge 无法区分。
配额统计 `COUNT(*) WHERE system_id=?1` 全部计入。

### 1.2 目标

| category | domain_addr | 角色 | 占配额 |
|----------|-------------|------|--------|
| `"platform"` | `""` | 平台管理员 | 否 |
| `"system"` | 裸域 `"dom1.com"` | 域级管理员 | 否 |
| `"agent"` | 邮箱 `"a@dom1.com"` | agent | 是 |
| `"bridge"` | `"bridge.{uuid}"` | bridge 实例 | 否 |

### 1.3 创建时校验

`POST /api/v1/api-keys` 入口新增：

```rust
match req.category.as_str() {
    "platform" => { if !req.domain_addr.is_empty() { return 400; } }
    "system"   => { if req.domain_addr.contains('@')  { return 400; } }
    "agent"    => { if !req.domain_addr.contains('@')  { return 400; } }
    "bridge"   => { /* 任意，建议 "bridge.{uuid}" */ }
    _          => return 400 "invalid category"
}
```

### 1.4 配额 SQL

```sql
SELECT COUNT(*) FROM api_keys WHERE system_id = ?1 AND category = 'agent'
```

### 1.5 agent key 创建时传 category

| 文件 | 改动 |
|------|------|
| `_auto_register_email` | `register_email` 调用时加 `category="agent"` |
| `activate_address_handler` | 激活码兑换时硬编码 `category="agent"` |

### 1.6 附带修复

`list_api_keys` 中 SystemAdmin 过滤 `category="agent"`，当前无 key 匹配（都是 `"system"`），返回空列表。引入 `"agent"` 后正常。

---

## 2. 多 bridge 独立 API key

### 2.1 现状

所有 bridge 共享 admin_key（system scope），泄露则全部失陷。

### 2.2 目标

每个 bridge 创建独立 `scope:bridge, category:bridge` 的 API key。

```
system_id = base-xxx
  bridge-A: api_key_001 (scope:bridge, category:bridge, domain_addr:bridge.a1b2)
  bridge-B: api_key_002 (scope:bridge, category:bridge, domain_addr:bridge.c3d4)
```

### 2.3 改动

| 文件 | 改动 |
|------|------|
| `integrate.sh` | bridge 部署后调 `POST /api/v1/api-keys {...}`，写入 `amail_bridge.toml` |
| `bridge config.rs` | `PullConfig` 新增 `api_key` 字段 |
| `bridge pull.rs` | `X-Api-Key: state.config.pull.api_key` |

---

## 3. Pull 大 email 列表性能优化

### 3.1 现状

```json
POST /api/v1/admin/pending {"limit":50, "emails":["a1@x.com",...,"a999@x.com"]}
```

1000 地址 → 30KB/次，SQLite 999 参数上限。

### 3.2 方案

bridge 支持三种过滤模式，根据路由表结构自动选择最优策略：

| 模式 | 请求体 | 适用场景 | gateway SQL |
|------|--------|---------|------------|
| exact | `{"emails":["a@x.com",...]}` | 纯精确地址路由 | `WHERE email IN (...)` |
| domain | `{"domains":["x.com","y.com"]}` | 含正则域名路由 | `WHERE domain_addr LIKE '%@x.com' OR ...` |
| all | `{}` | 路由表为空或 mixed | `无过滤` |

bridge 判定逻辑：

```
if 路由表全为精确地址:
    mode = exact  (传 emails)
elif 路由表有正则域名:
    mode = domain (提取唯一域名，传 domains)
else:
    mode = all    (什么都不传)
```

### 3.3 改动

| 文件 | 改动 |
|------|------|
| gateway `http.rs` | `list_pending_deliveries` 新增 `domains` 参数（Optional） |
| gateway `storage.rs` | `list_pending_deliveries` 支持 `domains: Option<&[String]>`，生成 `LIKE '%@domain'` 条件 |
| bridge `pull.rs` | `fetch_pending` 根据路由表选择 exact/domain/all 模式 |
| bridge `pull.rs` | `process_batch` 逐条 `router.lookup(email)` 过滤（兜底） |

### 3.4 示例

```
路由表:                                        模式:
  "a@x.com" = "127.0.0.1:8645"               → exact
  "b@x.com" = "127.0.0.1:8646"                   POST {"emails":["a@x.com","b@x.com"]}

  ".*@x.com" = "10.0.0.1:8645"               → domain
  ".*@y.com" = "10.0.0.2:8645"                   POST {"domains":["x.com","y.com"]}

  "a@x.com" = "127.0.0.1:8645"               → exact
  ".*@y.com" = "10.0.0.1:8645"               (按 domain 模式，因含 regex)
                                                    POST {"domains":["y.com"]}
```

---

## 4. require_domain_match 扩展

新增裸域匹配层：

```rust
if !key.email_address.contains('@') {
    let target_domain = target_email.rsplit('@').next().unwrap_or("");
    if key.email_address == target_domain {
        return Ok(());
    }
}
```

匹配优先级：`admin system_id` > `email_address=""` > 裸域匹配 > 精确邮箱匹配。

---

## 5. 实施顺序

| 阶段 | 内容 | 改动量 |
|------|------|--------|
| 1 | Pull 性能优化 | bridge 5 行 |
| 2 | category 契约 + 配额修复 + 创建校验 | ~30 行 |
| 3 | 域级管理员裸域匹配 | auth.rs 8 行 |
| 4 | bridge 独立 API key | integrate.sh + bridge 3 文件 |
