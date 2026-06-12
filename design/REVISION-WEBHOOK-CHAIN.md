# Webhook 配置链路修订方案

## 1. 发现的问题

### 1.1 `delivery_mode` 冗余

当前 gateway 同时依赖 `delivery_mode` 字段和 `webhook_url` 字段来判断推送模式：

```rust
// webhook.rs:210
if d.delivery_mode == "pull" {
```

但 `delivery_mode` 与 `webhook_url` 有隐含的对应关系：

| delivery_mode | webhook_url | 含义 |
|---|---|---|
| `"webhook"` | 有值 | push |
| `"pull"` | 有值（实际不回调） | pull |

`webhook_url` 空与否本身就是 pull/push 的充要条件，`delivery_mode` 是冗余的。

### 1.2 `bridge_url` 与 `webhook_host` 语义重叠

当前两个变量都存回调地址：

| 变量 | 写入时机 | 格式 |
|------|---------|------|
| `webhook_host` | Step 4 | `"x.x.x.x:port"` |
| `bridge_url` | Step 5.5 | `"http://x.x.x.x:port/webhooks/..."` |

`_auto_register_email` 里需要两分支处理，引入不必要的复杂度。

### 1.3 Step 4 与 Step 5.5 逻辑分离不合理

Step 4 输入 webhook 地址，Step 5.5 部署 bridge、探测模式、写配置。两者强相关却分两步，流程割裂。

### 1.4 Bridge 无路由注册反馈

`POST /api/v1/routes` 只返回 `"ok"`，调用方无法知道 bridge 是否正常工作、bridge 对外地址是什么、bridge 是 push 还是 pull。

### 1.5 `probe-webhook` API 设计缺陷

`probe-webhook` 无法准确判断 bridge 可达性（127.0.0.1 在远端 gateway 上被解析为 gateway 自己的 localhost）。且该探测实际上是在 bridge 已经部署启动之后，已经晚了——应该在部署阶段完成验证。

## 2. 改进设计目标

1. **消除冗余字段**：`delivery_mode` 整个删除，`bridge_url` 合并到 `webhook_host`
2. **统一路由注册入口**：三种模式（direct/internal/bridge）都走 `POST /api/v1/routes`
3. **Bridge 增强反馈**：`POST /api/v1/routes` 返回 `{"webhook_url": "..."}`，桥自身根据模式决定返回值
4. **简化判断逻辑**：gateway 用 `webhook_url.is_empty()` 代替 `delivery_mode == "pull"`
5. **Step 4 合并 Step 5.5**：一次完成模式选择与桥部署验证
6. **配置文件各司其职**：

| 文件 | 内容 | 用途 |
|------|------|------|
| `amail_gateway.json` | gateway 连接信息 + webhook_host | 全局配置 |
| `amail_bridge.toml` | bridge 自身参数 | bridge 启动配置 |
| `amail.json`（per-profile） | agent 邮箱凭证 | agent 激活 |

## 3. 改进方法细节

### 3.1 Gateway — 删除 delivery_mode，webhook_url 判空

**文件**：`amail-gateway/src/core/api/webhook.rs`

```rust
// 改前
if d.delivery_mode == "pull" {

// 改后
if d.webhook_url.trim().is_empty() {
```

**文件**：`amail-gateway/src/core/api/types.rs`

`RegisterAddressRequest`、`CreateSystemDomainRequest`、`UpdateSystemDomainRequest` 中删除 `delivery_mode: Option<String>` 字段。

**文件**：`amail-gateway/src/core/api/http.rs`

`register_address`、`create_system_domain` handler 中删除 `delivery_mode` 参数传参。

**文件**：`amail-gateway/src/core/storage.rs`

DDL `CREATE TABLE system_domains` 中删除 `delivery_mode TEXT NOT NULL DEFAULT 'webhook'` 列。

**检测方法**：编译通过 + 可用性测试 85/85 通过。

### 3.2 Bridge — 增强 POST /api/v1/routes 响应

**文件**：`amail-bridge/src/admin.rs`

**改前 handler**：

```rust
async fn create_route(...) -> impl IntoResponse {
    state.router.update_route(&body.email, &body.host, body.port);
    (StatusCode::OK, "ok").into_response()
}
```

**改后 handler**：

```rust
#[derive(Serialize)]
struct CreateRouteResponse {
    webhook_url: String,
}

async fn create_route(
    State(state): State<AdminState>,
    Json(body): Json<CreateRouteBody>,
) -> impl IntoResponse {
    state.router.update_route(&body.email, &body.host, body.port);

    let mode = &state.config.mode;  // "push" | "pull"
    let webhook_url = if mode == "push" {
        format!("http://{}/webhooks/amail-inbound", state.config.addr)
    } else {
        String::new()  // pull → 空串
    };

    (StatusCode::OK, Json(CreateRouteResponse { webhook_url })).into_response()
}
```

**`AdminState` 新增 `config` 字段**：

```rust
pub struct AdminState {
    pub router: Arc<ProfileRouter>,
    pub config: BridgeConfig,          // 新增
    pub allowed_ips: Vec<(std::net::IpAddr, u8)>,
    pub startup: std::time::Instant,
}
```

**`build_admin_router` 改造**：

```rust
pub fn build_admin_router(config: &BridgeConfig, router: Arc<ProfileRouter>) -> Router {
    let state = AdminState {
        router,
        config: config.clone(),      // 新增
        allowed_ips: ...,
        startup: Instant::now(),
    };
    ...
}
```

**检测方法**：编译通过 + 启动 bridge 后 `curl POST /api/v1/routes` 返回 `{"webhook_url":"..."}`。

### 3.3 `_auto_register_email` — 统一为 bridge 路由注册

**文件**：`amail_tools.py`

```python
# ── 判断 gateway 是否本机 ──
def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return True
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return host == local_ip
    except:
        return False


# ── _auto_register_email 核心逻辑 ──
config = _load_gateway_config()
gateway_url = config.get("gateway_url", "")
webhook_host = config.get("webhook_host", "")
wh_port = wh_config["port"]   # profile 的 Hermes webhook 端口

if _is_local_url(gateway_url):
    # 本机 gateway → 无 bridge，直连 Hermes webhook
    webhook_url = f"http://127.0.0.1:{wh_port}/webhooks/amail-inbound"
else:
    # 远程 gateway → 经 bridge，调路由 API
    if not webhook_host:
        logger.error("[amail_gateway] Remote gateway but webhook_host not set")
        return

    try:
        r = requests.post(
            f"http://{webhook_host}/api/v1/routes",
            json={
                "email": email,
                "host": "127.0.0.1",
                "port": wh_port,
            },
            timeout=5,
        )
        if r.status_code != 200:
            logger.error("[amail_gateway] Bridge route creation failed: %s", r.status_code)
            return
        data = r.json()
        # bridge 响应:
        #   push → {"webhook_url": "http://bridge:port/webhooks/amail-inbound"}
        #   pull → {"webhook_url": ""}
        webhook_url = data.get("webhook_url", "")
    except Exception as e:
        logger.error("[amail_gateway] Bridge unreachable: %s", e)
        return

# 提交到 gateway（无 delivery_mode 参数）
result = client.register_email(email=email, webhook_url=webhook_url)
```

**删除**：
- `delivery_mode` 参数所有引用
- `bridge_url` 读取、处理、迁移代码
- `_derive_webhook_url` 不再需要（bridge 直接返回正确值）

**检测方法**：Python Import OK + 集成脚本诊断通过 + 地址注册成功。

### 3.4 `integrate.sh` — Step 4 合并原 4 + 5.5

**流程**：

```
Step 4: Webhook 回调配置

GATEWAY_URL 是否本机 (127/内网IP/localhost)?
  │
  ├─ YES → webhook_host=""，无 bridge
  │       写入 amail_gateway.json: { webhook_host: "" }
  │
  └─ NO  → 输出 3 选项:

      [1] direct（公网直达）
          输入公网 IP:port，验证非内网非回环
          ── 部署 bridge ──
          检查 AMAIL_BRIDGE_BIN env → 下载/本地
          写入 amail_bridge.toml: { addr: 公网IP:port, mode: push }
          启动 bridge
          ── 验证 ──
          curl GET http://{公网IP:port}/health → 200
          ── 写入配置 ──
          webhook_host = 公网IP:port

      [2] internal（远端已有 bridge）
          输入内网 bridge IP:port
          ── 验证 ──
          curl GET http://{内网IP:port}/health → 200
          ── 写入配置 ──
          webhook_host = 内网IP:port

      [3] bridge（自建无公网）
          ── 自动检测 ──
          遍历 eth0/ens5/... 取首个非127 IPv4
          端口固定 38081
          ── 部署 bridge ──
          写入 amail_bridge.toml: { addr: 检测IP:port, mode: pull }
          启动 bridge
          ── 验证 ──
          curl GET http://{检测IP:port}/health → 200
          ── 写入配置 ──
          webhook_host = 检测IP:port
```

**写入 `amail_gateway.json` 的 Python 片段**：

```bash
python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg['webhook_host'] = '${WEBHOOK_HOST}'
json.dump(cfg, open(p, 'w'), indent=2)
"
```

**删除**：
- Step 5.5 整个 section
- `BRIDGE_DEPLOY`、`BRIDGE_MODE`、`BRIDGE_NEEDED` 变量
- `probe-webhook` 调用
- `delivery_mode` 写入
- `bridge_url` 写入

**检测方法**：三种模式分别走一次，确认 bridge 启动、`/health` 200、`amail_gateway.json` 正确。

### 3.5 可用性测试更新

**文件**：`amail-gateway/tests/availability_test.sh`

8.10a 的 probe loopback 测试改为测试 bridge 的 `/health` 端点（或直接删除，因为 probe-webhook 不再是集成流程的一部分）。

### 3.6 文档更新

**文件**：`hermes-amail-integration.md`、`hermes-amail-integration-zh.md`

- 删除 `delivery_mode` 字段说明
- 删除 `bridge_url` 字段说明
- Step 4 更新为合并后的 3 选项
- 删除 Step 5.5 文档
- `amail_gateway.json` 配置表中删除过期字段

## 4. 执行步骤与依赖关系

```
Phase 1（可并行）
  ├── 1a: amail-bridge admin.rs 增强 POST /api/v1/routes 响应
  └── 1b: amail-gateway 删 delivery_mode（types.rs + http.rs + storage.rs + webhook.rs）

Phase 2（依赖 Phase 1）
  └── 2a: amail_tools.py 重写 _auto_register_email
           + 新增 _is_local_url
           + 删除 delivery_mode、bridge_url

Phase 3（依赖 Phase 2）
  ├── 3a: integrate.sh Step 4 合并 + 简化
  └── 3b: 可用性测试更新

Phase 4（最后）
  └── 4a: 文档更新

Phase 5（验证）
  └── 5a: 全部编译 + 可用性测试 85/85 + 集成脚本全流程
```

## 5. 各步骤检测方法

| 阶段 | 检测方法 |
|------|---------|
| 1a | `cargo build --release`（bridge）；启动后 `curl -X POST /api/v1/routes -d '{"email":"t@t.com","host":"127.0.0.1","port":8644}'` 返回 `{"webhook_url":"..."}` |
| 1b | `cargo build --lib`（gateway）；可用性测试 85/85 |
| 2a | `python3 -c "import amail_tools"` OK |
| 3a | `bash -n integrate.sh` 语法 OK；三种模式各跑一遍确认行为 |
| 3b | 可用性测试 85/85 |
| 4a | `grep -rn 'delivery_mode\|bridge_url' docs/` 无残留 |
| 5a | 完整集成脚本跑通（从 Step 1 到 Step 10）|
