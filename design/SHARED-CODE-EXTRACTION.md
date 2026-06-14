# Shared Code Extraction Plan — main.rs + server.rs

## 1. Analysis

### main.rs — 90% identical

| Section | Lines | Base | Advanced | Shared? |
|---------|-------|------|----------|---------|
| Imports + CLI struct | 20-66 | same | same | ✅ |
| Commands enum | 61-71 | same | same | ✅ |
| jemalloc | - | none | 6 lines | ❌ |
| `cmd_start` daemon logic | 100-150 | same | same | ✅ |
| `cmd_start` config load | 165 | `amail_base::config::load()` | `toml::from_str` + AdvancedConfig | ❌ |
| `cmd_start` clamp | 179-191 | exists | not | ❌ |
| `cmd_start` server new | 238 | `Server::new(config, …)` | `Server::new(config, advanced, …)` | 1 line diff |
| `cmd_start` activation key | - | none | 6 lines (derive_base_key) | ❌ |
| `cmd_stop` | 261-311 | same | same | ✅ |
| `cmd_status` | 315-329 | same | same | ✅ |
| `read_pid_file` | 334-342 | same | same | ✅ |
| `is_process_alive` | 345-360 | same | same | ✅ |
| `init_tracing` | 363-394 | same (plain writer) | same (TeeWriter) | 2-line wrapper diff |

### server.rs — ~60% shared

| Section | Base Lines | Adv Lines | Shared? |
|---------|-----------|-----------|---------|
| Imports (strategy) | 29-40 | 30-42 | ❌ different impls |
| Server struct | 42-57 | 42-67 | partially (adv adds `advanced` field) |
| `Server::new()` | 60-82 | 65-130 | partially (adv creates resolvers) |
| `setup_admin_key()` | 87-120 | 130-170 | ✅ identical logic |
| `run_with_cancel()` | 140-270 | 170-400 | partially (adv adds ACME, relay) |
| `GracefulShutdown` + shutdown | 250-270 | 400-430 | ✅ identical |
| `spawn_http()` | 730-800 | 890-980 | ✅ identical |
| `spawn_smtp_direct()` | 790-832 | 1040-1080 | ✅ identical (adv adds relay listener) |

## 2. Plan

### Phase A: main.rs → shared CLI module

Move shared code into `amail_base::cli` (new file `src/core/cli.rs`):

```
pub fn cli_main() -> AppResult<()>     // unified main()
pub fn cmd_stop(cli: &Cli)             // unchanged
pub fn cmd_status(cli: &Cli)           // unchanged  
pub fn read_pid_file(path)             // unchanged
pub fn is_process_alive(pid)           // unchanged

pub struct Cli { … }                   // unified struct
pub enum Commands { … }                // unified enum
```

Injection points (where editions differ):
- `config_loader: fn(&str) -> AppResult<(Config, Option<AdvancedConfig>)>`
- `server_builder: fn(Config, Option<AdvancedConfig>, …) -> AppResult<Server>`
- `on_admin_key: fn(&Server, &str)` — advanced derives activation code key
- `log_writer: fn(Box<dyn Write>) -> Box<dyn Write>` — advanced wraps TeeWriter

Each binary's `main.rs` becomes ~15 lines:

```rust
fn main() -> AppResult<()> {
    amail_base::cli::CliMain {
        name: "amail-gateway",
        config_loader: …,   // base: Config::load; advanced: toml::from_str
        server_builder: …,  // base: Server::new; advanced: Server::new(_,advanced,_)
        on_admin_key: …,    // base: noop; advanced: derive_base_key
        log_writer: …,      // base: identity; advanced: TeeWriter::new
    }.run()
}
```

### Phase B: server.rs → shared ServiceRunner

Move shared service lifecycle into a trait or struct in lib:

```
pub struct ServiceRunner {
    http_handle: JoinHandle,
    smtp_handle: JoinHandle,
    retry_handle: JoinHandle,
    cleanup_handle: JoinHandle,
}

impl ServiceRunner {
    pub async fn shutdown(cancel: CancellationToken, handles: Vec<JoinHandle>)
}
```

Keep per-edition logic in `Server::run_with_cancel()`:
- Base: direct SMTP only
- Advanced: ACME + relay listener + rate limiter

### Estimated Changes

| File | Action | Lines |
|------|--------|-------|
| `src/core/cli.rs` | New | +280 |
| `src/main.rs` (gateway) | Rewrite | 394→~30 |
| `src/main.rs` (advanced) | Rewrite | 402→~35 |
| `src/server.rs` (gateway) | Extract | 832→~550 |
| `src/server.rs` (advanced) | Extract | 1216→~750 |

Net reduction: ~400 lines across both editions.

## 3. Recommendation

Phase A (CLI) gives the biggest roi with lowest risk — `cmd_stop`, `cmd_status`, daemon logic are pure passthrough. Phase B (server) is riskier due to the advanced edition's ACME/relay coupling. Do Phase A first.
