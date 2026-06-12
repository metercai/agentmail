# Phase 1b: amail-gateway — 删除 delivery_mode

## 总体策略

1. 删字段，不改 SQL 列索引（避免 migration 复杂度）
2. `webhook_url` 列已存在（TEXT 类型，可存空字符串）
3. 改判空逻辑即可——`delivery_mode` 不再被任何代码读取

## 文件 1: `amail-gateway/src/core/api/types.rs`

删 3 个 struct 中的 `delivery_mode` 字段：

```rust
// CreateSystemDomainRequest — 删这行:
pub delivery_mode: Option<String>,

// RegisterAddressRequest — 删这行:
pub delivery_mode: Option<String>,

// UpdateSystemDomainRequest — 删这行:
pub delivery_mode: Option<String>,
```

## 文件 2: `amail-gateway/src/core/api/http.rs`

删 2 个 handler 中的 `delivery_mode` 传参：

```rust
// create_system_domain — 删 dlivery_mode 实参
// 改前:
factory.create_domain(&id, &body.system_id, &body.domain, None, None, None,
    body.delivery_mode.as_deref()).await?;
// 改后:
factory.create_domain(&id, &body.system_id, &body.domain, None, None, None).await?;

// register_address — 同理删 delivery_mode 实参
```

## 文件 3: `amail-gateway/src/core/factory.rs`

删 2 个函数签名中的 `delivery_mode` 参数：

```rust
// create_domain() — 删最后一个参数
pub async fn create_domain(&self, id, system_id, domain, webhook_url,
    webhook_secret, manager_address, /* delivery_mode 删 */) -> AppResult<...> {
    self.db.insert_system_domain(id, system_id, domain, webhook_url, webhook_secret /* 删 delivery_mode */).await?;
    ...
}

// update_domain() — 同理删 delivery_mode 参数
```

## 文件 4: `amail-gateway/src/core/storage.rs`

### 4.1 DDL CREATE TABLE — 删列

```sql
-- 改前
CREATE TABLE IF NOT EXISTS system_domains (
    id TEXT PRIMARY KEY,
    system_id TEXT NOT NULL,
    domain_addr TEXT NOT NULL UNIQUE,
    webhook_url TEXT,
    webhook_secret TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    delivery_mode TEXT NOT NULL DEFAULT 'webhook'   -- 删此行
);

-- 改后
CREATE TABLE IF NOT EXISTS system_domains (
    id TEXT PRIMARY KEY,
    system_id TEXT NOT NULL,
    domain_addr TEXT NOT NULL UNIQUE,
    webhook_url TEXT,              -- TEXT 可存空字符串
    webhook_secret TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 4.2 ALTER TABLE migration — 删整个 block

```rust
// 删这整个块 (line 346-350):
{
    conn.execute_batch(
        "ALTER TABLE system_domains ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'webhook';",
    )
    .or_else(|e| {
        tracing::debug!(...);
        Ok::<_, rusqlite::Error>(())
    })?;
}
```

### 4.3 SystemDomainRecord — 删 delivery_mode

```rust
pub struct SystemDomainRecord {
    pub id: String,
    pub system_id: String,
    pub domain: String,
    pub webhook_url: Option<String>,
    pub webhook_secret: Option<String>,
    // pub delivery_mode: String,  ← 删
    pub is_active: bool,
    pub created_at: String,
    pub updated_at: String,
}
```

### 4.4 system_domain_row — 删 delivery_mode 映射

```rust
// 删这行:
delivery_mode: r.get(8).unwrap_or_else(|_| "webhook".to_string()),
```

### 4.5 insert_system_domain() — 删参数和 SQL

```rust
// 签名: 删 delivery_mode: Option<&str>
pub async fn insert_system_domain(&self, id, system_id, domain,
    webhook_url, webhook_secret) -> AppResult<SystemDomainRecord> {

// 体: 删这行
// let dm = delivery_mode.map(String::from).unwrap_or_else(|| "webhook".to_string());

// INSERT SQL: 删 delivery_mode 列和 ?6 参数
// 改前:
"INSERT INTO system_domains (id, system_id, domain_addr, webhook_url, webhook_secret, delivery_mode, is_active, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 1, ?7, ?7)"
// 改后:
"INSERT INTO system_domains (id, system_id, domain_addr, webhook_url, webhook_secret, is_active, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, 1, ?6, ?6)"

// params! 中删 dm:
// 改前: params![id, system_id, domain, webhook_url, webhook_secret, dm, now]
// 改后: params![id, system_id, domain, webhook_url, webhook_secret, now]

// Ok() 返回:
// 改前: delivery_mode: dm,
// 改后: (删此行)
```

### 4.6 update_system_domain() — 删参数和 SQL

```rust
// 签名: 删 delivery_mode: Option<&str>
pub async fn update_system_domain(&self, id, webhook_url, webhook_secret,
    is_active) -> AppResult<...> {

// 体: 删 let dm = ...
// UPDATE SQL: 删 delivery_mode = ?4
// 改前:
"UPDATE system_domains SET webhook_url = ?1, webhook_secret = ?2, is_active = ?3, delivery_mode = ?4, updated_at = ?5 WHERE id = ?6"
// 改后:
"UPDATE system_domains SET webhook_url = ?1, webhook_secret = ?2, is_active = ?3, updated_at = ?4 WHERE id = ?5"

// params! 重编号
```

### 4.7 SELECT SQL — 删 delivery_mode 列名（3 条）

```sql
SELECT id, system_id, domain_addr, webhook_url, webhook_secret, is_active, created_at, updated_at
  FROM system_domains WHERE ...
```

## 文件 5: `amail-gateway/src/core/api/webhook.rs`

```rust
// 改前 (line 210)
if d.delivery_mode == "pull" {

// 改后
if d.webhook_url.as_deref().map_or(true, |u| u.trim().is_empty()) {
```

## 检测方法

```bash
# gateway (library)
cd /home/ubuntu/amail-gateway
cargo build --lib 2>&1 | tail -5

# advanced (binary)
cargo build --release 2>&1 | tail -5

# 可用性测试
./tests/availability_test.sh
# 预期: 全部 PASS (85/85 → 可能因删字段导致测试用例调整，见 Phase 3b)

# 验证二进制中无 delivery_mode 字符串
strings ./target/release/amail-advanced | grep -c delivery_mode
# 预期: 0
```
