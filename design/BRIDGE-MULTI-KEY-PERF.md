# Bridge 安全管理 & 性能优化方案（终稿）

## 0. 已完成：pending TTL 配置化

`pending_ttl_hours`（默认 72h）已加入 `WebhookConfig`，scheduler 定时清理超时 pending。

---

## 1. category / domain_addr 契约层

### 1.1 最终模型

| category | domain_addr | 角色 | 配额 | require_domain_match |
|----------|-------------|------|------|---------------------|
| `"platform"` | `""` | 平台管理员 | 否 | system_id="admin" bypass |
| `"system"` | 裸域 `"dom1.com"` | 域级管理员 | 否 | target 裸域匹配 |
| `"agent"` | 邮箱 `"a@dom1.com"` | agent | 是 | exact email 匹配 |
| `"bridge"` | `"bridge.{uuid}"` | bridge 实例 | 否 | 不经过此函数 |

### 1.2 创建时校验

`POST /api/v1/api-keys` handler 入口加校验：

```rust
match req.category.as_str() {
    "platform" => { /* domain_addr 必须为空 */ }
    "system"   => { /* domain_addr 必须不含 '@'（裸域） */ }
    "agent"    => { /* domain_addr 必须含 '@'（邮箱） */ }
    "bridge"   => { /* domain_addr 任意，建议 "bridge.{uuid}" */ }
    _          => return 400 "invalid category"
}
```

### 1.3 配额统计

```sql
SELECT COUNT(*) FROM api_keys WHERE system_id = ?1 AND category = 'agent'
```

仅 agent 占 `max_addresses`。platform/system/bridge 全豁免。

### 1.4 附带修复

`list_api_keys` 中 SystemAdmin 过滤 `category="agent"`——当前无 key 匹配（都是 `"system"`），返回空列表。引入 `"agent"` category 后正常工作。

---

## 2. 多 bridge 独立 API key

### 2.1 目标

```
system_id = base-xxx
  ├─ bridge-A: api_key_001 (scope: bridge, category: bridge, domain_addr: bridge.a1b2)
  ├─ bridge-B: api_key_002 (scope: bridge, category: bridge, domain_addr: bridge.c3d4)
  └─ agent-alice: api_key_xxx (scope: agent, category: agent, domain_addr: alice@dom.com)
```

### 2.2 改动

| 文件 | 改动 |
|------|------|
| `integrate.sh` | bridge 部署后调 `POST /api/v1/api-keys {scopes:["bridge"], category:"bridge", domain_addr:"bridge.{uuid}"}` → 写入 `amail_bridge.toml` |
| `bridge config.rs` | `PullConfig` 新增 `api_key` 字段 |
| `bridge pull.rs` | `X-Api-Key: state.config.pull.api_key` |
| gateway | 无改动（pending/ack 已接受 bridge scope） |

### 2.3 安全收益

- 单把 key 泄露 → 只影响一个 bridge，可单独吊销
- bridge 无法访问其他 API（只有 pending/ack 两个 endpoint）
- 审计日志可区分不同 bridge 的操作

---

## 3. Pull 大 email 列表性能优化

### 3.1 现状瓶颈

```json
POST /api/v1/admin/pending
{"limit": 50, "emails": ["a1@x.com", ..., "a999@x.com"]}
```

- 1000 地址 → 30KB JSON/次
- SQLite 999 参数上限

### 3.2 方案：移除 email 过滤

bridge 不传 `emails` → gateway 返回该系统所有 pending → bridge 本地 `router.lookup()` 过滤 → 匹配的转发+ACK → 不匹配的留在队列被 TTL 清理。

### 3.3 改动

| 文件 | 改动 |
|------|------|
| `bridge pull.rs` fetch_pending | 移除 emails 数组构建 |
| `bridge pull.rs` process_batch | 逐条 `router.lookup(email)` 过滤 |
| gateway | 无需改动（emails 已是 Optional） |

---

## 4. require_domain_match 扩展

新增裸域匹配逻辑：

```rust
// Domain-level admin: email_address is bare domain (no '@')
if !key.email_address.contains('@') {
    let target_domain = target_email.rsplit('@').next().unwrap_or("");
    if key.email_address == target_domain {
        return Ok(());
    }
}
```

匹配优先级：`admin system_id` > `email_address=""` > 裸域匹配 > exact email 匹配。

---

## 5. 实施顺序

| 阶段 | 内容 | 改动量 | 风险 |
|------|------|--------|------|
| 1 | Pull 性能优化（移除 email 过滤） | bridge 5 行 | 低 |
| 2 | category 契约 + 配额修复 + 创建校验 | gateway ~20 行 + advanced 1 行 + Python 1 行 | 中 |
| 3 | 域级管理员裸域匹配 | auth.rs ~8 行 | 低 |
| 4 | bridge 独立 API key | integrate.sh + bridge 3 文件 | 中 |
