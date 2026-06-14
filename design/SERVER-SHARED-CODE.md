# server.rs Shared Code Extraction Plan

## Analysis Summary

| Section | Lines Base | Lines Adv | Shared? |
|---------|-----------|-----------|---------|
| `Server` struct | ~30 | ~40 | ❌ 字段不同 |
| `Server::new()` | ~35 | ~65 | ❌ 参数不同 |
| `setup_admin_key()` | ~40 | ~60 | partially (key gen相同) |
| `run()` | ~15 | ~15 | ✅ 完全一致 |
| `run_with_cancel()` | ~110 | ~215 | partially (关机序列相同) |
| `GracefulShutdown` | ~25 | ~25 | ✅ 完全相同 |
| `spawn_http()` | ~65 | ~220 | ❌ 高级版有TLS/ACME/vhost |
| `spawn_smtp_direct()` | ~30 | ~30 | ✅ 完全相同 |

## Extractable Pure Shared Code (~230 lines)

### 1. `GracefulShutdown` → `src/core/server/shutdown.rs` (25行)

```rust
pub struct GracefulShutdown { ... }
impl GracefulShutdown {
    pub async fn wait_for_shutdown(cancel, http, smtp, retry, cleanup)
    pub async fn join_with_timeout(handle, timeout_secs, name)
}
```

两端完全相同，直接移。

### 2. `spawn_smtp_direct()` → `src/core/server/smtp.rs` (30行)

SMTP listener 启动+关机包装。

### 3. `run()` → delegate to `run_with_cancel()` (15→1行)

```rust
pub async fn run(&self) -> AppResult<()> {
    self.run_with_cancel(CancellationToken::new()).await
}
```

### 4. run_with_cancel() helper → `src/core/server/runner.rs` (80行)

提取可重用的"构建 HTTP state + router + 启动各服务 + 等待关机"框架。差异点通过 struct 字段注入：

```rust
pub struct ServiceHandles {
    pub http: JoinHandle<AppResult<()>>,
    pub smtp: JoinHandle<AppResult<()>>,
    pub retry: JoinHandle<()>,
    pub cleanup: JoinHandle<()>,
}

pub async fn run_services_and_wait(
    cancel: CancellationToken,
    start_http: impl FnOnce(Router) -> JoinHandle<...>,
    start_smtp: impl FnOnce(...) -> JoinHandle<...>,
    start_retry: impl FnOnce(...) -> JoinHandle<...>,
    ...
) -> AppResult<()>
```

但这回到了闭包注入——简单点可以直接把 HTTP state 和 router 构建逻辑留在各版，只抽关机序列。

## Recommended Plan (最小侵入)

仅提取纯共享的三块：

| 提取内容 | 目标文件 | 行数 |
|---------|---------|------|
| `GracefulShutdown` | `src/core/server/shutdown.rs` | 25 |
| `spawn_smtp_direct` | `src/core/server/smtp.rs` | 30 |
| `run()` → 委托 `run_with_cancel` | 两版各改1行 | 2 |

净减 ~50 行。两版 server.rs 从 832+1216=2048 行缩至约 1998 行。
