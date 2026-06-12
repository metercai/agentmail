# Bridge Code Review Report

## 审计范围

`amail-bridge/src/{config,admin,router,main}.rs` — Phase 1a 改动部分

## 严重度图例

| 符号 | 含义 |
|------|------|
| 🔴 | 逻辑错误 / 安全漏洞 / 数据丢失风险 |
| 🟡 | 边缘情况 / 设计疑问 / 可改进 |
| ✅ | 正确，无需改动 |

---

## config.rs

### 1. 🔴 `is_dual_port()` 对 IP hostname 误判

```rust
pub fn is_dual_port(&self) -> bool {
    let (_, port) = self.parsed_addr();
    port == 80 && self.hostname.is_some()  // ← 应排除 IP
}
```

**问题**：`hostname = "1.2.3.4:80"` + `addr.port == 80` 会错误触发 dual-port 模式。Dual-port（80→443 redirect）仅在 domain hostname 时有意义。

**修复**：加上 `&& !is_ip_address(self.hostname.as_deref().unwrap_or(""))`

### 2. 🟡 `has_tls()` 类型不够严格

```rust
pub fn has_tls(&self) -> bool {
    self.hostname.as_ref().map_or(false, |h| !is_ip_address(h))
}
```

逻辑正确，但依赖 `is_ip_address` 的 hostname 格式必须含 `:` 端口后缀（否则 IP 无冒号会 fall-through 到 8645 默认端口分支，不影响判定）。建议加注释说明预期格式。

### 3. ✅ `is_ip_address` 辅助函数

```rust
fn is_ip_address(host: &str) -> bool {
    let host_only = host.split(':').next().unwrap_or(host);
    host_only.parse::<std::net::IpAddr>().is_ok()
}
```

IPv4 正确。IPv6（`[::1]:38081`）会因 `[` 开头导致 `parse::<IpAddr>` 失败返回 false——**正确**，IPv6 bridge 地址不在当前使用场景。

---

## admin.rs

### 4. 🔴 `create_route` 返回硬编码 `http://` 协议

```rust
let webhook_url = if state.config.mode == "push" {
    let host = state.config.hostname.as_deref().unwrap_or(&state.config.addr);
    format!("http://{}/webhooks/amail-inbound", host)  // ← 永远 http
} else {
    String::new()
};
```

**问题**：当 `hostname = "bridge.example.com:443"` (domain) 时，bridge 自身以 HTTPS 运行，但返回的 `webhook_url` 却是 `http://` 开头。Gateway 会用 HTTP POST 到 443 端口，可能失败。

**现状分析**：`_auto_register_email` 提交 `webhook_url` 给 gateway 时不解析协议——直接使用 bridge 返回值。所以如果 bridge 返回 `http://` 而实际是 HTTPS，gateway 投递会失败。

**修复**：根据 hostname 类型决定协议：
```rust
let scheme = if state.config.hostname.as_ref().map_or(true, |h| is_ip_address(h)) {
    "http"
} else {
    "https"
};
format!("{}://{}/webhooks/amail-inbound", scheme, host)
```

> 此修复需要将 `is_ip_address` 改为 `pub(crate)` 可见。

### 5. ✅ IP whitelist 安全

`admin_allowed_ips` 正确使用 `check_admin_ip` middleware。未配置时允许所有请求（本地开发友好）。配置后严格检查。

---

## router.rs

### 6. 🔴 `update_route` 有并发数据竞争

```rust
pub fn update_route(&self, email: &str, host: &str, port: u16) {
    let mut routes = self.routes.write().unwrap_or_else(|e| e.into_inner());
    routes.insert(email.into(), ProfileRoute::new(email.into(), host.into(), port));
    drop(routes);
    let overrides = self.load_routes_file();          // ← 读文件
    self.write_routes_file_with(&overrides);          // ← 写文件
}
```

**竞争场景**：

| 时间 | Thread A | Thread B |
|------|---------|---------|
| 1 | `routes.insert("a@b.com", ...)` | |
| 2 | `drop(routes)` | `routes.insert("c@d.com", ...)` |
| 3 | `load_routes_file()` → `{}` | `drop(routes)` |
| 4 | `write_routes_file_with({})` → 写 `{c@d}` | `load_routes_file()` → `{c@d}` |
| 5 | | `write_routes_file_with({c@d})` → 写 `{c@d}` |
| 6 | **a@b.com 永远丢失** | |

根因：`write_routes_file_with` 依赖从文件重读的内容，而非直接从内存写入。

**修复**：`write_routes_file_with` 改为直接从内存 `routes` 构建文件内容，不依赖 `load_routes_file` 的返回值。

```rust
pub fn update_route(&self, email: &str, host: &str, port: u16) {
    let mut routes = self.routes.write().unwrap_or_else(|e| e.into_inner());
    routes.insert(email.into(), ProfileRoute::new(email.into(), host.into(), port));
    drop(routes);
    self.write_current_routes();   // 新方法：直接从内存写
}
```

### 7. 🔴 `remove_route` 同样存在竞争

与 #6 同根同源，修复 `write_routes_file_with` 即可同时解决。

### 8. 🟡 Watcher 竞态：写时读

`write_routes_file_with` 写文件时，watcher 的 inotify 可能在同一毫秒内触发 `load_from_file`。虽然有 `writing_routes` flag 保护，但 flag 的 `store(true)` 和 `std::fs::write` 之间不是原子的。极端情况下 watcher 可能读到部分写入的内容。

**影响**：TOML parse 失败 → `load_routes_file` 返回空 → `load_from_file` 清空路由表。但下一个文件事件会重新加载（如果文件随后写入完整）。

**建议**：写临时文件 + 原子 rename，或接受 risk（低概率）。

### 9. 🟡 `webhook_url` 空字符串 vs pull 模式

`create_route` handler 在 pull 模式下返回 `webhook_url: ""`。Gateway 改判 `webhook_url.trim().is_empty()` → pull。两者对齐。✅

### 10. 🟡 Regex 预计算缺失

`lookup` 中每次 run 都 `find(|(re, _, _, _)| re.is_match(email))`，对每个 regex 做 i> 次匹配。当 regex 数量大时是 O(n*m)。当前 n 很小（≤ 10），可接受。

### 11. ✅ `load_from_file` 两遍扫描正确

第一遍精确匹配插入，第二遍 regex 扩展时 `if routes.contains_key(email) { continue }` 保护精确匹配不被覆盖。逻辑正确。

---

## main.rs

### 12. ✅ 启动流程

```rust
let router = Arc::new(router::ProfileRouter::new(config.routes_file.clone()));
router.load_from_file();
router::start_routes_watcher(router.clone())?;
```

- `new()` 只取 `routes_file` ✅
- `load_from_file()` 在 watcher 前调用 ✅
- Watcher 不阻塞 ✅

---

## 修复优先级

| 优先级 | 问题 | 影响 | 修复难度 |
|--------|------|------|---------|
| 🔴 立即 | #6 #7 `update_route` 并发数据竞争 | Profile 创建时路由丢失 | 中 |
| 🔴 立即 | #4 `webhook_url` 硬编码 `http://` | Domain hostname 时 gateway 回调失败 | 低 |
| 🟡 本次 | #1 `is_dual_port()` 对 IP hostname 误判 | IP hostname + port 80 时错误走 dual-port | 低 |
| 🟡 后续 | #8 Watcher 写时读竞态 | 极端情况下路由短暂清空 | 中 |

## 修复方案

### Fix #4: 协议判断

```rust
// admin.rs create_route handler
let scheme = if state.config.hostname.as_ref().map_or(true, |h| is_ip_address(h)) {
    "http"
} else {
    "https"
};
format!("{}://{}/webhooks/amail-inbound", scheme, host)
```

需要将 `config::is_ip_address` 改为 `pub(crate)`。

### Fix #6 #7: 消除读-修改-写竞争

```rust
// router.rs — 新增方法
fn write_current_routes(&self) {
    let path = &self.routes_file;
    self.writing_routes.store(true, Ordering::SeqCst);
    let routes = self.routes.read().unwrap_or_else(|e| e.into_inner());
    let mut out = String::from("# Auto-generated by amail-bridge.\n# File changes take effect immediately.\n");
    let mut keys: Vec<&String> = routes.keys().collect();
    keys.sort();
    for email in keys {
        if let Some(route) = routes.get(email) {
            out.push_str(&format!("\"{}\" = \"{}:{}\"\n", email, route.host, route.port));
        }
    }
    if let Err(e) = std::fs::write(path, &out) {
        tracing::warn!(path = %path.display(), error = %e, "Failed to write routes file");
    }
}

pub fn update_route(&self, email: &str, host: &str, port: u16) {
    let mut routes = self.routes.write().unwrap_or_else(|e| e.into_inner());
    routes.insert(email.into(), ProfileRoute::new(email.into(), host.into(), port));
    drop(routes);
    self.write_current_routes();
}

pub fn remove_route(&self, email: &str) {
    let mut routes = self.routes.write().unwrap_or_else(|e| e.into_inner());
    routes.remove(email);
    drop(routes);
    self.write_current_routes();
}
```

旧 `write_routes_file_with(&file_overrides)` 仍由 `load_from_file` 内部使用（用于初次加载时保留 regex 模式），保持不变。

### Fix #1: is_dual_port 限 domain

```rust
pub fn is_dual_port(&self) -> bool {
    let (_, port) = self.parsed_addr();
    port == 80 && self.hostname.as_ref().map_or(false, |h| !is_ip_address(h))
}
```
