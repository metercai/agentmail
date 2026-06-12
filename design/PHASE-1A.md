# Phase 1a: amail-bridge — hostname + route response + remove auto-discovery

## 文件 1: `amail-bridge/src/config.rs`

### 1. 提升 PushConfig 字段到 BridgeConfig

改前:
```rust
pub struct BridgeConfig {
    pub mode: String,
    pub addr: String,
    pub push: PushConfig,
    ...
}

pub struct PushConfig {
    pub hostname: Option<String>,
    pub tls_cert: Option<PathBuf>,
    pub tls_key: Option<PathBuf>,
    pub acme_cache: Option<PathBuf>,
    ...
}
```

改后:
```rust
pub struct BridgeConfig {
    pub mode: String,
    pub addr: String,
    /// Public hostname (domain or IP:port). Promoted from push.hostname.
    pub hostname: Option<String>,
    /// TLS cert path (domain hostname only)
    pub tls_cert: Option<PathBuf>,
    /// TLS key path (domain hostname only)
    pub tls_key: Option<PathBuf>,
    /// ACME cache dir (domain hostname only)
    pub acme_cache: Option<PathBuf>,
    ...
}
// PushConfig 删除 hostname/tls_cert/tls_key/acme_cache 字段
```

### 2. has_tls() 改为区分 IP/domain

从 `self.push` 改为 `self`:
```rust
pub fn has_tls(&self) -> bool {
    self.hostname.as_ref().map_or(false, |h| !is_ip_address(h))
}

fn is_ip_address(host: &str) -> bool {
    // 去掉端口部分
    let host_only = host.split(':').next().unwrap_or(host);
    host_only.parse::<std::net::IpAddr>().is_ok()
}
```

### 3. is_dual_port() 改引用路径

```rust
pub fn is_dual_port(&self) -> bool {
    let (_, port) = self.parsed_addr();
    port == 80 && self.hostname.is_some()
}
```

### 4. main.rs 中所有 `config.push.hostname` → `config.hostname`

```rust
// main.rs:301
if config.mode == "push" && config.has_tls() {
```

### 5. 向后兼容

`BridgeConfig` 的 Deserialize derive 保持不变。旧 toml 文件有 `[push] hostname` 需要兼容反序列化。

## 文件 2: `amail-bridge/src/admin.rs`

### 1. AdminState 加 config

```rust
pub struct AdminState {
    pub router: Arc<ProfileRouter>,
    pub config: BridgeConfig,          // 新增
    pub allowed_ips: Vec<(std::net::IpAddr, u8)>,
    pub startup: std::time::Instant,
}
```

### 2. build_admin_router 传 config

```rust
pub fn build_admin_router(config: &BridgeConfig, router: Arc<ProfileRouter>) -> Router {
    let state = AdminState {
        router,
        config: config.clone(),
        allowed_ips: parse_ip_list(&config.admin_allowed_ips),
        startup: Instant::now(),
    };
    ...
}
```

### 3. CreateRouteResponse 新增

```rust
#[derive(Serialize)]
struct CreateRouteResponse {
    status: String,
    webhook_url: String,
}
```

### 4. create_route handler 改

```rust
async fn create_route(
    State(state): State<AdminState>,
    Json(body): Json<CreateRouteBody>,
) -> impl IntoResponse {
    state.router.update_route(&body.email, &body.host, body.port);

    let webhook_url = if state.config.mode == "push" {
        let host = state.config.hostname.as_deref().unwrap_or(&state.config.addr);
        format!("http://{}/webhooks/amail-inbound", host)
    } else {
        String::new()
    };

    (StatusCode::OK, Json(CreateRouteResponse {
        status: "ok".to_string(),
        webhook_url,
    })).into_response()
}
```

## 文件 3: `amail-bridge/src/router.rs`

### 1. 删除函数

- `full_scan()`
- `scan_profile_dir()`
- `load_route()`
- `start_watcher()` — 改为简化版（只监听 amail_routes.toml）

### 2. ProfileRouter::new 简化

```rust
pub fn new(routes_file: PathBuf) -> Self {
    // 不再需要 hermes_home / profiles_dir
    Self {
        routes: RwLock::new(HashMap::new()),
        routes_file,
        regex_patterns: RwLock::new(Vec::new()),
        writing_routes: AtomicBool::new(false),
    }
}
```

### 3. 新增简化 watcher（只监听 amail_routes.toml）

```rust
pub fn start_routes_watcher(router: Arc<ProfileRouter>) -> notify::Result<()> {
    let (tx, rx) = std::sync::mpsc::channel();
    let mut watcher = notify::recommended_watcher(move |res| {
        if let Ok(event) = res {
            let _ = tx.send(event);
        }
    })?;

    if router.routes_file.exists() {
        watcher.watch(&router.routes_file, RecursiveMode::NonRecursive)?;
    }

    tokio::spawn(async move {
        let _watcher = watcher; // keep alive
        while let Ok(event) = rx.recv() {
            let is_our_write = router.writing_routes.load(Ordering::SeqCst);
            let is_routes_file = event.paths.iter().any(|p| *p == router.routes_file);
            if is_routes_file && !is_our_write {
                let file_routes = router.load_routes_file();
                let mut routes = router.routes.write().unwrap_or_else(|e| e.into_inner());
                *routes = file_routes;
            }
        }
    });
    Ok(())
}
```

## 文件 4: `amail-bridge/src/main.rs`

### 1. ProfileRouter::new 调用简化

```rust
// 改前
let router = Arc::new(router::ProfileRouter::new(
    &hermes_home, routes_file.clone(),
));
router::start_watcher(router.clone())?;

// 改后
let router = Arc::new(router::ProfileRouter::new(routes_file.clone()));
router::start_routes_watcher(router.clone())?;
```

## 检测方法

```bash
cd /home/ubuntu/amail-bridge
cargo build --release 2>&1 | tail -5

# 启动 bridge 测试
echo 'addr = "0.0.0.0:38081"
hostname = "1.2.3.4:38081"
mode = "push"' > /tmp/test_bridge.toml

./target/release/amail-bridge -c /tmp/test_bridge.toml &
sleep 1

# 验证 health
curl -s http://127.0.0.1:38081/health | python3 -m json.tool

# 验证 create_route 返回增强响应
curl -s -X POST http://127.0.0.1:38081/api/v1/routes \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","host":"127.0.0.1","port":8644}' \
  | python3 -m json.tool
# 预期: {"status":"ok","webhook_url":"http://1.2.3.4:38081/webhooks/amail-inbound"}

# 验证 pull 模式返回空
kill %1
echo 'addr = "0.0.0.0:38081"
hostname = "1.2.3.4:38081"
mode = "pull"' > /tmp/test_bridge.toml
./target/release/amail-bridge -c /tmp/test_bridge.toml &
sleep 1
curl -s -X POST http://127.0.0.1:38081/api/v1/routes \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","host":"127.0.0.1","port":8644}' \
  | python3 -m json.tool
# 预期: {"status":"ok","webhook_url":""}

kill %1
```
