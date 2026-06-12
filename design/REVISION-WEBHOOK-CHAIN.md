# Webhook 配置链路修订方案（终稿）

## 1. 发现的问题

### 1.1 `delivery_mode` 冗余

gateway 用 `delivery_mode` 字段 + `webhook_url` 字段共同决定推送模式：

```
webhook.rs:210  if d.delivery_mode == "pull" {
```

但 `webhook_url` 空与否本身就是 pull/push 的充要条件。gateway 需要的是"是否回调这个 URL"，而不是一个额外的"模式"标签。"mode"应该在 bridge 内部消化，不需要流到 gateway 或 agent 侧。

### 1.2 `bridge_url` 与 `webhook_host` 语义重叠

两个变量都存回调地址，格式不同但含义相同。`_auto_register_email` 需要 if-else 两分支处理。

### 1.3 Step 4 与 Step 5.5 流程割裂

Step 4 输入 webhook 地址，Step 5.5 部署 bridge、探测 push/pull、写配置。两者强相关却分两步。

### 1.4 Bridge `POST /api/v1/routes` 无反馈

只返回 `"ok"`。调用方不知道 bridge 是 push 还是 pull、bridge 对外的地址是什么。所有三种模式（direct/internal/bridge）都调此 API 注册路由，但 bridge 的响应给不了结论。

### 1.5 `probe-webhook` API 适用场景有限

`probe-webhook`（`POST {gateway_url}/probe-webhook {"addr":"ip:port"}`）让远程 gateway 主动连接指定地址，验证 gateway → bridge 可达性。

- **适用**：direct 模式，bridge 在公网 IP 上，需确认 gateway 端能否连到 bridge
- **不适用**：internal/internal 模式 bridge 在内网，gateway 可能不可达、bridge 模式无公网地址固定 pull
- **原问题**：对所有 remote gateway 场景统一调 probe-webhook，但传 `127.0.0.1` 时远端 gateway 连的是自己的 localhost，结论无效

### 1.6 GATEWAY_URL 本机判断缺失

`_auto_register_email` 不知道 gateway 在本机还是远程。本机 gateway 可以直接连 Hermes webhook（127.0.0.1:8644+N），不需要 bridge。

---

## 2. 改进设计目标

1. **删除 `delivery_mode`**：从 gateway（DDL + storage + factory + types + http + webhook.rs）和 Python（`_auto_register_email`、`integrate.sh`）中完全移除
2. **统一 `webhook_host`**：合并 `bridge_url`，格式统一为 `host:port`。`bridge_url` 彻底消除，包括所有读写代码和 legacy migration 逻辑，不做历史兼容
3. **Bridge `POST /api/v1/routes` 增强反馈**：调用方传 `email` + `host` + `port`，bridge 返回 `{"webhook_url": "..." 或 ""}`——bridge 自己决定 push 或 pull
4. **Gateway 改判空**：`d.webhook_url.trim().is_empty()` 代替 `d.delivery_mode == "pull"`
5. **Step 4 合并原 5.5**：一次完成：模式选择 → bridge 部署/验证 → 配置写入
6. **`_auto_register_email` 简化**：本机 gateway → 直连 Hermes；远程 gateway → 调 bridge API 拿 `webhook_url`
7. **配置文件各司其职**：

| 文件 | 内容 |
|------|------|
| `amail_gateway.json` | `gateway_url` + `admin_key` + `system_id` + `domain` + `webhook_host` |
| `amail_bridge.toml` | `addr` + `mode`（direct=push, bridge=pull） |
| `amail.json`（per-profile） | agent 邮箱凭证 + 激活码 |

---

## 3. 改进方法细节

### 3.1 Gateway — 删除 `delivery_mode`，webhook_url 判空

改动按调用层次分组：

#### 3.1.1 存储层（`amail-gateway/src/core/storage.rs`）

| 项 | 改动 |
|---|------|
| DDL CREATE TABLE | 删 `delivery_mode TEXT NOT NULL DEFAULT 'webhook'` 列 |
| ALTER TABLE migration | 删 `ALTER TABLE system_domains ADD COLUMN delivery_mode` migration block |
| `system_domain_row()` | 删 `delivery_mode: r.get(8).unwrap_or_else(…)` 行；后续列如有索引调整 |
| `SystemDomainRecord` struct | 删 `delivery_mode: String` 字段 |
| `insert_system_domain()` 签名 | 删 `delivery_mode: Option<&str>` 参数 |
| `insert_system_domain()` 体 | 删 `let dm = …` 行；INSERT SQL 删 `delivery_mode` 列及对应 `?N` |
| `update_system_domain()` 签名 | 删 `delivery_mode: Option<&str>` 参数 |
| `update_system_domain()` 体 | 删 `let dm = …` 行；UPDATE SQL 删 `delivery_mode = ?4` |
| 3 条 SELECT SQL | 删 `delivery_mode` 列名 |

#### 3.1.2 工厂层（`amail-gateway/src/core/factory.rs`）

| 函数 | 改动 |
|------|------|
| `create_domain()` | 签名删 `delivery_mode: Option<&str>`，调用 `insert_system_domain()` 时删对应实参 |
| `update_domain()` | 签名删 `delivery_mode: Option<&str>`，调用 `update_system_domain()` 时删对应实参 |

#### 3.1.3 类型层（`amail-gateway/src/core/api/types.rs`）

| struct | 改动 |
|--------|------|
| `CreateSystemDomainRequest` | 删 `delivery_mode: Option<String>` |
| `RegisterAddressRequest` | 删 `delivery_mode: Option<String>` |
| `UpdateSystemDomainRequest` | 删 `delivery_mode: Option<String>` |

#### 3.1.4 HTTP 层（`amail-gateway/src/core/api/http.rs`）

| handler | 改动 |
|---------|------|
| `create_system_domain()` | 调 `factory.create_domain()` 删 `req.delivery_mode.as_deref()` |
| `register_address()` | 同上 |

#### 3.1.5 判决层（`amail-gateway/src/core/api/webhook.rs`）

```rust
// 改前
if d.delivery_mode == "pull" {

// 改后
if d.webhook_url.as_deref().map_or(true, |u| u.trim().is_empty()) {
```

#### 3.1.6 检测方法

- `cargo build --lib`（gateway）+ `cargo build --release`（advanced）编译通过
- 可用性测试 85/85 通过

---

### 3.2 Bridge — `POST /api/v1/routes` 响应增强

**文件**：`amail-bridge/src/admin.rs`

#### 3.2.1 `AdminState` 新增 `config` 字段

```rust
pub struct AdminState {
    pub router: Arc<ProfileRouter>,
    pub config: BridgeConfig,   // 新增 — handler 读 mode 和 addr
    pub allowed_ips: Vec<(std::net::IpAddr, u8)>,
    pub startup: std::time::Instant,
}
```

#### 3.2.2 `build_admin_router` 传 `config`

```rust
pub fn build_admin_router(config: &BridgeConfig, router: Arc<ProfileRouter>) -> Router {
    let state = AdminState {
        router,
        config: config.clone(),
        allowed_ips: ...,
        startup: Instant::now(),
    };
    ...
}
```

#### 3.2.3 `create_route` handler

```rust
#[derive(Serialize)]
struct CreateRouteResponse { webhook_url: String }

async fn create_route(State(state): State<AdminState>, Json(body): Json<CreateRouteBody>)
    -> impl IntoResponse
{
    state.router.update_route(&body.email, &body.host, body.port);

    let webhook_url = if state.config.mode == "push" {
        format!("http://{}/webhooks/amail-inbound", state.config.addr)
    } else {
        String::new()
    };

    (StatusCode::OK, Json(CreateRouteResponse { webhook_url })).into_response()
}
```

**请求体**（`CreateRouteBody`，不变）：`{ "email": "a@b.com", "host": "127.0.0.1", "port": 8645 }`

**响应**：`{ "webhook_url": "http://192.168.1.100:38081/webhooks/amail-inbound" }` 或 `{ "webhook_url": "" }`

#### 3.2.4 检测方法

- `cargo build --release`（bridge）
- 启动后：`curl -X POST http://{addr}/api/v1/routes -d '{"email":"t@t.com","host":"127.0.0.1","port":8644}'` 返回 `{"webhook_url":"..."}`

---

### 3.3 `_auto_register_email` — 重写

**文件**：`amail_tools.py`

#### 3.3.1 新增 `_is_local_url()`

```python
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
```

#### 3.3.2 `_auto_register_email` 核心逻辑

```
config = _load_gateway_config()
gateway_url = config.get("gateway_url", "")
wh_port = wh_config["port"]

if _is_local_url(gateway_url):
    webhook_url = f"http://127.0.0.1:{wh_port}/webhooks/amail-inbound"
else:
    webhook_host = config.get("webhook_host", "")
    if not webhook_host:
        fail("Remote gateway but webhook_host not set")

    r = POST http://{webhook_host}/api/v1/routes
          body: { "email": email, "host": "127.0.0.1", "port": wh_port }
    if r.status != 200:
        fail
    webhook_url = r.json()["webhook_url"]

client.register_email(email=email, webhook_url=webhook_url)
```

**删除**：
- `delivery_mode` 参数及所有引用
- `bridge_url` — 所有读取、写入、legacy migration 代码（`_load_gateway_config()` 中 `cfg["bridge_url"]` 迁移行、`_inject_profile_config()` 中 `bridge_url` 字段）

#### 3.3.3 检测方法

- `python3 -c "import amail_tools"` OK
- 集成脚本诊断 `webhook_route`、`profile_hooks` 通过

---

### 3.4 `integrate.sh` — Step 4 合并原 4 + 5.5

#### 3.4.1 完整流程

```
Step 4: Webhook 回调配置

1. GATEWAY_URL 是否本机?

   YES:
     info "Gateway is local — no bridge needed"
     WEBHOOK_HOST=""
     写入 amail_gateway.json: { webhook_host: "" }  ← 覆盖

   NO → 输出 3 选项:

   ┌── [1] direct（公网直达）
   │      输入公网 IP:port
   │      验证: 非回环、非内网、非本机 IP
   │      ── 部署 bridge ──
   │      定位二进制 (AMAIL_BRIDGE_BIN env > 本地 > GitHub)
   │      写入 amail_bridge.toml:  addr={公网IP:port}  mode=push
   │      启动 bridge (nohup)
   │      ── 验证 ──
   │      curl GET http://{公网IP:port}/health → 200  否则报错退出
   │      ── 远程探测 ──
   │      POST {gateway_url}/probe-webhook {"addr":"{公网IP:port}"}
   │        gateway 端测试能否连到 bridge
   │      reachable=true  → step_ok "Gateway can reach bridge"
   │      reachable=false → step_warn "Gateway cannot reach bridge — push may fail"
   │      WEBHOOK_HOST={公网IP:port}

   ├── [2] internal（远端已有 bridge）
   │      输入内网 bridge IP:port
   │      验证: 内网 IP
   │      ── 验证 ──
   │      curl GET http://{内网IP:port}/health → 200  否则报错退出
   │      WEBHOOK_HOST={内网IP:port}

   └── [3] bridge（自建无公网，固定 pull）
          自动检测: 遍历 eth0/ens5/...
          取首个非 127 IPv4，端口 38081
          ── 部署 bridge ──
          定位二进制 (同上)
          写入 amail_bridge.toml:  addr={检测IP:port}  mode=pull
          启动 bridge (nohup)
          ── 验证 ──
          curl GET http://{检测IP:port}/health → 200  否则报错退出
          WEBHOOK_HOST={检测IP:port}
```

#### 3.4.2 写入 `amail_gateway.json`

```
python3 -c "cfg['webhook_host']='${WEBHOOK_HOST}'"
```

#### 3.4.3 删除项

- Step 5.5 整个 section
- `BRIDGE_DEPLOY`、`BRIDGE_MODE`、`BRIDGE_NEEDED` 变量
- `delivery_mode` 写入
- `bridge_url` 写入
- `amail_bridge.toml` 中 `[push]` section（只保留 `addr` + `mode`）

#### 3.4.4 检测方法

- `bash -n integrate.sh` 语法 OK
- 三种模式各跑一遍，逐项检查：输入提示、bridge 启动、`/health` 200、`amail_gateway.json` webhook_host 正确

---

### 3.5 可用性测试

**文件**：`amail-gateway/tests/availability_test.sh`

- 8.10a-d 的 probe-webhook 测试保留（API 端点本身仍需测试：loopback rejection → unreachable → 401 → 403）— **无需改动**

### 3.6 文档更新

### 3.6 文档更新

**文件**：`hermes-amail-integration.md`、`hermes-amail-integration-zh.md`

- 删除 `delivery_mode`、`bridge_url` 字段说明
- Step 4 更新为合并后流程
- 删除 Step 5.5 文档
- `amail_gateway.json` 配置表删除过期字段

---

## 4. 执行步骤与依赖关系

```
Phase 1（可并行）
  ├── 1a: amail-bridge admin.rs
  │        - AdminState 加 config 字段
  │        - build_admin_router 传 config
  │        - create_route 返回 {"webhook_url":"..."}
  │        检测: cargo build --release + curl 验证新响应格式
  │
  └── 1b: amail-gateway 删 delivery_mode
           - storage.rs: DDL + migration + row mapper + SQL + 函数签名（15+ 处）
           - factory.rs: create_domain + update_domain 签名（2 处）
           - types.rs: 3 个 struct 字段（3 处）
           - http.rs: create_system_domain + register_address 传参（2 处）
           - webhook.rs: 判空改法（1 处）
           检测: cargo build --lib + cargo build --release(advanced) + 可用性测试 85/85

Phase 2（依赖 Phase 1）
  └── 2a: amail_tools.py
           - _is_local_url() 新增
           - _auto_register_email 重写
           - 删除 delivery_mode + bridge_url + legacy migration
           检测: import OK + 集成脚本诊断

Phase 3（依赖 Phase 2）
  ├── 3a: integrate.sh Step 4 合并 + 简化
  │        检测: bash -n + 三种模式各跑一遍
  └── 3b: 可用性测试更新（无大改动，可选）

Phase 4
  └── 4a: 文档更新
           检测: grep delivery_mode/bridge_url docs/ 无残留

Phase 5（验证）
  └── 5a: 全部编译 + 可用性测试 85/85 + 集成脚本全流程
```

## 5. 各步骤检测方法

| 阶段 | 检测方法 |
|------|---------|
| 1a | `cargo build --release`（bridge）；`curl POST /api/v1/routes` 返回 `{"webhook_url":"..."}` |
| 1b | `cargo build --lib`（gateway）；`cargo build --release`（advanced）；可用性测试 85/85 |
| 2a | `python3 -c "import amail_tools"` OK；集成脚本诊断通过 |
| 3a | `bash -n integrate.sh` OK；三种模式各跑一遍 |
| 4a | `grep -rn 'delivery_mode\|bridge_url' docs/` 无残留 |
| 5a | 完整集成脚本（Step 1→10）跑通 |
