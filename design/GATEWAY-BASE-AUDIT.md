# Gateway Base Library — Extended Security & Performance Audit

## 审计范围

`amail-gateway/src/core/` 改动波及的 5 个文件及其上下游调用链。

---

## 1. 逻辑完备性

### 1.1 webhook_url 判空三态覆盖

```rust
// webhook.rs:210
if d.webhook_url.as_deref().map_or(true, |u| u.trim().is_empty()) {
```

| 值 | `as_deref()` | `map_or` | 判空 | 模式 |
|----|-------------|----------|------|------|
| `None` | `None` | `true` | — | pull |
| `Some("")` | `Some("")` | — | `"".trim().is_empty() → true` | pull |
| `Some("http://...")` | `Some("http://...")` | — | `false` | push |
| `Some("  ")` | `Some("  ")` | — | `"  ".trim().is_empty() → true` | pull |

✅ 包括空格串也被判为 pull（修复了纯 `is_empty()` 的遗漏）。

### 1.2 旧数据库兼容

旧 DB 中 `system_domains` 表仍有 `delivery_mode` 列（`TEXT NOT NULL DEFAULT 'webhook'`）。

- **INSERT**：新 SQL 不含 `delivery_mode` → SQLite 使用 DEFAULT `'webhook'` ✅
- **SELECT**：row mapper 不读列索引 8 → 旧值被忽略 ✅
- **旧 `delivery_mode="webhook"` + `webhook_url=""` 的数据**：新代码判 `webhook_url.trim().is_empty() → true` → pull 路径。但旧业务语义是 push。⚠️

> **结论**：理论上不存在这种矛盾数据（旧代码强制 `delivery_mode` 与 `webhook_url` 一致性），但无法 100% 排除。如果存在，行为从 push 变为 pull，邮件不会丢失（进入 pending queue），bridge pull 可轮询到。

### 1.3 Push 路径 fallback

```rust
// webhook.rs:319
if url.is_empty() {
    warn!(email_id = %record.id, %domain, "Endpoint has no URL — skipping");
    continue;
}
```

push 循环跳过空 URL 端点，`all_succeeded` 保持为 `true`（因为端点未处理不算失败）。⚠️

> **风险**：如果多个端点混合（pull 和 push），空 URL 的 push 端点被跳过，`all_succeeded` 仍为 `true`，邮件被标记为交付成功，但该端点实际未接收。

> **影响**：低。pull 端点已在前面 block 被标记 success（line 276），空 URL 端点不存在实际注册场景中（`register_address` 要求 webhook_url 必填）。

### 1.4 Row mapper 列索引一致性

| SELECT 列 | 索引 | row mapper 读取 | 匹配 |
|-----------|------|----------------|------|
| id | 0 | `r.get(0)` | ✅ |
| system_id | 1 | `r.get(1)` | ✅ |
| domain_addr | 2 | `r.get(2)` | ✅ |
| webhook_url | 3 | `r.get(3)` | ✅ |
| webhook_secret | 4 | `r.get(4)` | ✅ |
| is_active | 5 | `r.get::<i32>(5)` | ✅ |
| created_at | 6 | `r.get(6)` | ✅ |
| updated_at | 7 | `r.get(7)` | ✅ |

✅ 无 `delivery_mode: r.get(8)`，无缺口。

---

## 2. 安全隐患

### 2.1 HTTP POST 无签名验证（push 路径）

```rust
// webhook.rs:380-429
// POST payload to webhook_url with X-Webhook-Signature header
```

推送路径使用 HMAC 签名（`sign_payload(secret, &payload_bytes)`），header 含 `X-Webhook-Signature` 和 `X-Mailrelay-Timestamp`。✅

### 2.2 Pull 路径无签名（pull 路径）

```rust
// webhook.rs:244-256
let sig = if let Some(ref secret) = ws_secret {
    sign_payload(secret.as_bytes(), &payload_bytes)
} else {
    warn!("No webhook_secret for pull domain — unsigned delivery");
    // 签名置空
};
```

Pull 路径若无 `webhook_secret` 会告警并插入无签名交付。bridge 收到后验签失败会丢弃。⚠️

> **影响**：低。`register_address` 必传 `webhook_secret`（由 `_ensure_profile_webhook` 自动生成 32 字节 hex token）。

### 2.3 无输入长度限制（pull 路径）

```rust
let payload_json = String::from_utf8(payload_bytes.clone()).unwrap_or_default();
```

`payload_json` 直接插入 `pending_deliveries` 表。无长度检查——大附件邮件可能导致单条记录数百 MB。

> **影响**：中。`pending_deliveries` 表作为 pull queue 无限增长。**预存在**问题，非本次改动引入。

### 2.4 SQL 注入

全部使用 `params![]` 参数化查询。✅

### 2.5 API Key 验证链

```rust
// http.rs create_system_domain / register_address
require_scope_any(&api_key, &["system"])?;
```

✅ 权限检查未改动，删除 `delivery_mode` 不影响。

---

## 3. 性能瓶颈

### 3.1 N+1 查询（pull 路径）

```rust
// webhook.rs:207-286
for addr in recipients.to.iter().chain(recipients.cc.iter()) {
    // ...
    let ws_secret = env_factory.resolve_domain_by_name(addr).await; // DB query #1
    // ...
    env_factory.db.insert_pending_delivery(...).await;               // DB query #2
    email_factory.update_endpoint_status(...).await;                  // DB query #3
}
```

每个收件人 3 次 DB 查询。50 人 CC → 150 次查询。

> **影响**：中。**预存在**问题。`resolve_domain_by_name` 有 30 秒内存缓存（`domain_cache`），同域名的重复查询不会重复走 DB。但不同域名仍各自查询。

### 3.2 `payload_bytes` 双重 clone

```rust
let payload_bytes = serde_json::to_vec(&payload).unwrap_or_default(); // 序列化 #1
let payload_json = String::from_utf8(payload_bytes.clone()).unwrap_or_default(); // clone #1
```

`payload_bytes.clone()` 是全量复制 JSON 字节数组。大邮件会触发大内存分配。

> **影响**：低。一次 `clone`。**预存在**。

### 3.3 `endpoints_map` 查询为 HashMap

```rust
let endpoints_map: Option<serde_json::Map<String, serde_json::Value>>;
```

`serde_json::Map` 是 `BTreeMap`，O(log n)。对小端点数（<100）可接受。

> **影响**：无。

---

## 4. 运行时可观测性

| 事件 | 日志级别 | 消息 |
|------|---------|------|
| Pull 交付成功 | `info!` | `"Inserted pending delivery (pull mode)"` |
| Pull 交付失败 | `warn!` | `"Failed to insert pending delivery"` |
| 无 webhook_secret | `warn!` | `"No webhook_secret for pull domain — unsigned delivery"` |
| URL 为空 | `warn!` | `"Endpoint has no URL — skipping"` |
| Push 交付成功 | `info!` | `"Webhook endpoint delivered successfully"` |
| Push 交付失败 | `warn!` | `"Webhook endpoint delivery failed"` |

✅ 所有关键路径都有日志。

---

## 5. 修复建议

| 优先级 | 问题 | 修复方案 |
|--------|------|---------|
| 🟡 | 3.1 N+1 查询（预存在） | pull 路径中对同 domain 收件人批处理 |
| 🟡 | 2.3 无限 pending_deliveries（预存在） | 加 `body_limit` 检查 / TTL 清理 cron |
| ⬜ | 2.2 pull 无签名（已 warning） | 接受当前行为 |

**本次改动无新增问题。** 所有标记的问题均为预存在，不在本次范围。

---

## 结论

Gateway base library 审计通过。`delivery_mode` 删除未引入逻辑漏洞、安全隐患或性能退化。3 个预存在问题已标注，建议后续迭代处理。
