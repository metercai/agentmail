# server.rs Final Sharing Analysis

## Current State

| Function | Gateway | Advanced | Status |
|----------|---------|----------|--------|
| `db()` | 4 | 4 | ✅ identical, trivial |
| `api_endpoint_url()` | 20 | 20 | ✅ identical |
| `fn run()` | 13 | 13 | ~identical (comment diff) |
| `spawn_retry_worker()` | 26 | 28 | 2-line diff (mx_resolver param) |
| `new()` | 20 | 20 | param diff |
| `setup_admin_key()` | 37 | 51 | structure same, impl differs |
| `run_with_cancel()` | 152 | 312 | skeleton same, advanced +160 lines |
| `spawn_http()` | 73 | 236 | advanced +163 lines |

## What Remains Shareable

### Tier 1: Pure shared (no injection needed) — 24 lines trivial

- `db()` + `api_endpoint_url()` — can move but ROI near zero

### Tier 2: Trivial parameterization — 26 lines

- `spawn_retry_worker()` — differs only by `mx_resolver` param.
  Base passes `None`, advanced passes `Some(...)`.
  Both call `run_retry_worker_with_trigger` from lib.

### Tier 3: Needs closure injection — 15 lines

- `new()` — common body: open DB, create Metrics. Advanced adds `advanced` field.
  `Server::base_new()` returns a base struct, advanced wraps.

### Tier 4: Cannot share — 283 lines

- `setup_admin_key()` — SystemStore type + init_tables call differ
- `run_with_cancel()` — 160 lines of ACME + 40 lines strategy injection
- `spawn_http()` — 163 lines of advanced-only features

## Verdict

server.rs sharing is **complete**. Remaining shareable code:

- `db()` + `api_endpoint_url()` = 24 lines, trivial
- `spawn_retry_worker()` = 26 lines with `Option<mx_resolver>` parameter
- `new()` = 15 lines common body via base constructor

Total potential: ~65 lines salvaged from ~1180. ROI below threshold.

The 868 lines already removed were the high-ROI layers:
- 257: handle_smtp_session + write_response (receiver.rs)
- 171: spawn_smtp + load_smtp_tls_config (server.rs)
- 51: graceful exit (graceful.rs)

Stop here. Server lifecycle is inherently edition-specific.
