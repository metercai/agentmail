# Webhook 配置链路修订方案（终稿 v3）

## 1. 发现的问题

### 1.1 `delivery_mode` 冗余

gateway 用 `delivery_mode` 字段 + `webhook_url` 字段共同决定推送模式：

```
webhook.rs:210  if d.delivery_mode == "pull" {
```

但 `webhook_url` 空与否本身就是 pull/push 的充要条件。gateway 需要的是"是否回调这个 URL"，不是额外的"模式"标签。mode 应该在 bridge 内部消化，不需要流到 gateway 或 agent 侧。

### 1.2 `bridge_url` 与 `webhook_host` 语义重叠

两个变量都存回调地址，格式不同但含义相同。`_auto_register_email` 需要 if-else 两分支处理。必须彻底清除 `bridge_url`，不做历史兼容（尚未实际部署）。

### 1.3 Step 4 与 Step 5.5 流程割裂

Step 4 输入 webhook 地址，Step 5.5 部署 bridge、探测 push/pull、写配置。两者强相关却分两步。

### 1.4 Bridge `POST /api/v1/routes` 无 webhook_url 反馈

核心问题：当有 bridge 桥接时，agent 不知道 gateway 回调应该用什么地址——是 bridge 的公网地址还是空字符串（pull）。

当前 `POST /api/v1/routes` 只返回 `"ok"`，`_auto_register_email` 无法从 bridge 获取正确的 `webhook_url`。bridge 必须把 `webhook_url` 作为响应的一部分返回给调用方。

### 1.5 `probe-webhook` API 适用场景有限

`probe-webhook`（`POST {gateway_url}/probe-webhook {"addr":"ip:port"}`）让远程 gateway 主动连接指定地址，验证 gateway → bridge 可达性。

- **适用**：direct 模式，bridge 在公网 IP 上，需确认 gateway 端能否连到 bridge
- **不适用**：internal 模式 bridge 在内网 gateway 可能不可达、bridge 模式无公网地址固定 pull
- **原问题**：对所有 remote gateway 场景统一调 probe-webhook，但传 `127.0.0.1` 时远端 gateway 连的是自己的 localhost，结论无效

### 1.6 Bridge 监听地址与对外地址混淆

当前 `addr` 既是 bridge 的监听地址（本机），又是 `create_route` 返回给 agent 的地址（提交给 gateway）。但 direct 模式下：

- 本机实际 IP 可能是 NAT 后的内网地址
- 用户输入的公网 IP:port 是 NAT 映射，不是本机真实 IP
- bridge 应绑定本机可用地址（`0.0.0.0:port` 或检测到的内网 IP）
- 返回给 gateway 的应该是用户指定的公网 IP:port（或域名:port）

需要一个独立的 `hostname` 配置项来表达"对外声明的地址"。

### 1.7 配置文件读写权限未明确

| 文件 | 写权限 | 创建者 |
|------|--------|--------|
| `amail_gateway.json` | **仅 integrate.sh** | 集成阶段写入 |
| `amail.json`（per-profile） | `_auto_register_email` | profile 创建时写入 |
| `amail_bridge.toml` | integrate.sh | 桥部署时写入 |

agent 进程不能写 `amail_gateway.json`——它是全局信息，应由集成脚本维护。`_auto_register_email` 只能读取。

### 1.8 GATEWAY_URL 本机判断重复

`_auto_register_email` 计划新增 `_is_local_url()` 判断 gateway 是否本机。但集成脚本 Step 1 已经连接并测试过 gateway_url，这个结论可以通过 `amail_gateway.json` 的 `webhook_host` 字段传递——空表示本机、非空表示有 bridge。不需要重复判断。

---

## 2. 改进设计目标

1. **删除 `delivery_mode`**：从 gateway（DDL + storage + factory + types + http + webhook.rs）和 Python（`_auto_register_email`、`integrate.sh`）中完全移除
2. **彻底清除 `bridge_url`**：所有读写代码和 legacy migration 逻辑，不做历史兼容
3. **Bridge `POST /api/v1/routes` 增强反馈**：返回 `{"status":"ok","webhook_url":"..."}`——bridge 自己决定 push/pull
4. **Bridge 分离 `addr` 与 `hostname`**：
   - `addr`：本机监听地址（`0.0.0.0:port` 或检测到的内网 IP:port）
   - `hostname`：对外声明的地址（公网 IP:port 或域名:port），`create_route` 返回此值；支持 IP 形式（免 TLS）
5. **Gateway 改判空**：`webhook_url.is_empty()` 代替 `delivery_mode == "pull"`
6. **Step 4 合并原 5.5**：一次完成模式选择 → bridge 部署/验证 → 配置写入
7. **数据流单向**：`integrate.sh` → `amail_gateway.json` → `_auto_register_email` → `amail.json`。agent 只读 `amail_gateway.json`
8. **集成脚本可重复运行**：已有配置值作为交互菜单的默认值，不丢失

---

## 3. 配置文件

### 3.1 `~/.hermes/amail_gateway.json`（全局 gateway 配置，仅 integrate.sh 写入）

```json
{
  "gateway_url": "https://amail.token.tm:443",
  "admin_key": "20cc1b...",
  "system_id": "base-xxx",
  "domain": "mydomain.com",
  "webhook_host": "1.2.3.4:38081"
}
```

**`webhook_host` 的含义**：

| 值 | 含义 | `_auto_register_email` 行为 |
|---|------|---------------------------|
| `""` | gateway 在本机 | 直连 Hermes webhook |
| `"ip:port"` 或 `"domain:port"` | 有 bridge（对外的 `hostname`） | 调 bridge API 拿 `webhook_url` |

### 3.2 `~/.hermes/amail_bridge.toml`（bridge 自身配置，integrate.sh 写入）

```toml
# 本机监听地址（bridge 实际绑定的 IP:port）
addr = "0.0.0.0:38081"

# 对外声明的地址（公网 IP:port 或域名:port）
# create_route API 返回此值给 agent
# 支持 IP 形式（免 TLS）和域名形式
hostname = "1.2.3.4:38081"

# 工作模式
mode = "push"
```

**`hostname` 与 TLS**：

| hostname 形式 | 示例 | TLS |
|-------------|------|-----|
| IP:port | `"1.2.3.4:38081"` | 不需要 |
| domain:port | `"bridge.example.com:443"` | 启用 |

### 3.3 `~/.hermes/profiles/{name}/amail.json`（per-profile，`_auto_register_email` 写入）

```json
{
  "email": "default@mydomain.com",
  "activation_code": "base-xxxx-...",
  "gateway_url": "https://amail.token.tm:443",
  "domain": "mydomain.com",
  "system_id": "base-xxx"
}
```

---

## 4. 改进方法细节

### 4.1 Gateway — 删除 `delivery_mode`，webhook_url 判空

改动按调用层次分组：

#### 4.1.1 存储层（`amail-gateway/src/core/storage.rs`）

| 项 | 改动 |
|---|------|
| DDL CREATE TABLE | 删 `delivery_mode TEXT NOT NULL DEFAULT 'webhook'` 列 |
| ALTER TABLE migration | 删 `ALTER TABLE system_domains ADD COLUMN delivery_mode` migration block |
| `system_domain_row()` | 删 `delivery_mode: r.get(8).unwrap_or_else(…)` 行 |
| `SystemDomainRecord` struct | 删 `delivery_mode: String` 字段 |
| `insert_system_domain()` 签名 | 删 `delivery_mode: Option<&str>` 参数 |
| `insert_system_domain()` 体 | 删 `let dm = …` 行；INSERT SQL 删 `delivery_mode` 列及对应 `?N` |
| `update_system_domain()` 签名 | 删 `delivery_mode: Option<&str>` 参数 |
| `update_system_domain()` 体 | 删 `let dm = …` 行；UPDATE SQL 删 `delivery_mode = ?4` |
| 3 条 SELECT SQL | 删 `delivery_mode` 列名 |

#### 4.1.2 工厂层（`amail-gateway/src/core/factory.rs`）

| 函数 | 改动 |
|------|------|
| `create_domain()` | 签名删 `delivery_mode: Option<&str>`，调用 `insert_system_domain()` 删对应实参 |
| `update_domain()` | 签名删 `delivery_mode: Option<&str>`，调用 `update_system_domain()` 删对应实参 |

#### 4.1.3 类型层（`amail-gateway/src/core/api/types.rs`）

| struct | 改动 |
|--------|------|
| `CreateSystemDomainRequest` | 删 `delivery_mode: Option<String>` |
| `RegisterAddressRequest` | 删 `delivery_mode: Option<String>` |
| `UpdateSystemDomainRequest` | 删 `delivery_mode: Option<String>` |

#### 4.1.4 HTTP 层（`amail-gateway/src/core/api/http.rs`）

| handler | 改动 |
|---------|------|
| `create_system_domain()` | 调 `factory.create_domain()` 删 `req.delivery_mode.as_deref()` |
| `register_address()` | 同上 |

#### 4.1.5 判决层（`amail-gateway/src/core/api/webhook.rs`）

```rust
// 改前
if d.delivery_mode == "pull" {

// 改后
// webhook_url 为空 → pull 模式，存 pending_deliveries
// webhook_url 有值 → push 模式，POST 回调
if d.webhook_url.as_deref().map_or(true, |u| u.trim().is_empty()) {
```

**需验证**：gateway `webhook_url` 字段（`TEXT` 类型）是否可以存储空字符串 `""`。如果不能，使用单个空格 `" "` 表示 pull 模式，判空改为 `u.trim().is_empty()`。

#### 4.1.6 检测方法

- `cargo build --lib`（gateway）+ `cargo build --release`（advanced）编译通过
- 可用性测试 85/85 通过

---

### 4.2 Bridge — `hostname` 配置 + `POST /api/v1/routes` 响应增强

#### 4.2.1 新增顶层 `hostname` 配置（`amail-bridge/src/config.rs`）

```rust
pub struct BridgeConfig {
    pub mode: String,       // "push" | "pull"
    pub addr: String,       // 监听地址 "ip:port"（本机）
    pub hostname: Option<String>,  // 对外地址 "ip:port" | "domain:port"
    // ...
}
```

兼容性：未配置 `hostname` 时回退到 `addr`。

#### 4.2.2 `AdminState` 新增 `config` 字段（`amail-bridge/src/admin.rs`）

```rust
pub struct AdminState {
    pub router: Arc<ProfileRouter>,
    pub config: BridgeConfig,   // 新增
    pub allowed_ips: Vec<(std::net::IpAddr, u8)>,
    pub startup: std::time::Instant,
}
```

#### 4.2.3 `build_admin_router` 传 `config`

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

#### 4.2.4 `create_route` handler

```rust
#[derive(Serialize)]
struct CreateRouteResponse {
    status: String,          // "ok"
    webhook_url: String,     // push → 完整 URL, pull → ""
}

async fn create_route(State(state): State<AdminState>, Json(body): Json<CreateRouteBody>)
    -> impl IntoResponse
{
    state.router.update_route(&body.email, &body.host, body.port);

    let webhook_url = if state.config.mode == "push" {
        // 优先用 hostname（对外地址），fallback 到 addr（监听地址）
        let host = state.config.hostname.as_deref().unwrap_or(&state.config.addr);
        format!("http://{}/webhooks/amail-inbound", host)
    } else {
        String::new()  // pull → 空串
    };

    (StatusCode::OK, Json(CreateRouteResponse {
        status: "ok".to_string(),
        webhook_url,
    })).into_response()
}
```

**请求体**（不变）：`{ "email": "a@b.com", "host": "127.0.0.1", "port": 8645 }`

**响应**：
- push → `{ "status": "ok", "webhook_url": "http://{hostname}/webhooks/amail-inbound" }`
- pull → `{ "status": "ok", "webhook_url": "" }`

#### 4.2.5 检测方法

- `cargo build --release`（bridge）
- 启动后：`curl POST /api/v1/routes -d '{"email":"t","host":"127.0.0.1","port":8644}'` → `{"status":"ok","webhook_url":"..."}`

---

### 4.3 `_auto_register_email` — 重写

**数据流（单向）**：

```
integrate.sh
  → 写入 amail_gateway.json: { webhook_host: "" | "ip:port" }
                                  ↓（只读）
                        _auto_register_email
                          → 写入 amail.json: { email, activation_code, ... }
                          → 调 bridge API（远程 gateway 时）
                          → 调 gateway API 注册地址
```

**核心逻辑**：

```python
config = _load_gateway_config()
webhook_host = config.get("webhook_host", "")   # integrate.sh 已判断好
wh_port = wh_config["port"]

if not webhook_host:
    # webhook_host = "" → gateway 在本机
    # integrate.sh Step 1 已验证 gateway_url 是本机，这里直接信任
    webhook_url = f"http://127.0.0.1:{wh_port}/webhooks/amail-inbound"
else:
    # webhook_host 有值 → 远程 gateway，有 bridge
    # POST bridge API 拿 webhook_url
    try:
        r = requests.post(
            f"http://{webhook_host}/api/v1/routes",
            json={"email": email, "host": "127.0.0.1", "port": wh_port},
            timeout=5,
        )
        if r.status_code != 200:
            logger.error("[amail_gateway] Bridge route creation failed: %s", r.status_code)
            return
        data = r.json()
        webhook_url = data.get("webhook_url", "")
        # push → "http://{hostname}/webhooks/amail-inbound"
        # pull → ""
    except Exception as e:
        logger.error("[amail_gateway] Bridge unreachable: %s", e)
        return

# 提交到 gateway（无 delivery_mode 参数）
result = client.register_email(email=email, webhook_url=webhook_url)
```

**删除**：
- `_is_local_url()` — 不再需要，integrate.sh 已判断
- `delivery_mode` — 所有引用
- `bridge_url` — 所有读取、写入、legacy migration 代码
- `_inject_profile_config()` 中 `bridge_url` 字段

#### 检测方法

- `python3 -c "import amail_tools"` OK
- 集成脚本诊断 `webhook_route`、`profile_hooks` 通过

---

### 4.4 `integrate.sh` — Step 4 合并原 4 + 5.5

#### 4.4.1 完整流程

```
Step 4: Webhook 回调配置

1. GATEWAY_URL 是否本机?（Step 1 已连接成功，此时已知）

   YES:
     info "Gateway is local — no bridge needed"
     WEBHOOK_HOST=""
     BRIDGE_HOSTNAME=""        ← bridge 对外地址（无 bridge 时为空）
     写入 amail_gateway.json: { webhook_host: "" }

   NO → 输出 3 选项:

   ┌── [1] direct（公网直达）
   │      输入公网 IP:port 或 domain:port
   │      验证: 非回环、非内网
   │      ── 检测本机监听地址 ──
   │      AUTO_ADDR = 自动检测非 loopback IPv4:38081（同 bridge 模式）
   │      如果检测失败，用 0.0.0.0:38081
   │      ── 部署 bridge ──
   │      定位二进制 (AMAIL_BRIDGE_BIN env > 本地 > GitHub)
   │      写入 amail_bridge.toml:
   │        addr = AUTO_ADDR             ← 本机监听地址
   │        hostname = 用户输入           ← 对外地址
   │        mode = push
   │      启动 bridge (nohup)
   │      ── 验证 ──
   │      curl GET http://{AUTO_ADDR}/health → 200  否则报错退出
   │      ── 远程探测 ──
   │      POST {gateway_url}/probe-webhook {"addr":"用户输入"}
   │      reachable=true  → step_ok "Gateway can reach bridge"
   │      reachable=false → step_warn（不退出，允许继续）
   │      WEBHOOK_HOST=用户输入        ← 对外地址写入 gateway.json
   │      BRIDGE_HOSTNAME=用户输入     ← bridge 对外地址写入 gateway.json

   ├── [2] internal（远端已有 bridge）
   │      输入内网 bridge IP:port
   │      验证: 内网 IP
   │      ── 验证 ──
   │      curl GET http://{内网IP:port}/health → 200  否则报错退出
   │      WEBHOOK_HOST=内网IP:port
   │      BRIDGE_HOSTNAME=""

   └── [3] bridge（自建无公网，固定 pull）
          自动检测: 遍历 eth0/ens5/...
          取首个非 127 IPv4，端口 38081
          如果检测失败，用 127.0.0.1:38081 作为 fallback
          ── 部署 bridge ──
          定位二进制 (同上)
          写入 amail_bridge.toml:
            addr = 检测IP:port           ← 本机监听地址
            hostname = ""（留空）
            mode = pull
          启动 bridge (nohup)
          ── 验证 ──
          curl GET http://{检测IP:port}/health → 200  否则报错退出
          WEBHOOK_HOST=检测IP:port      ← 本机监听地址写入
          BRIDGE_HOSTNAME=""（pull 模式，无对外地址）
```

#### 4.4.2 写入 `amail_gateway.json`

```bash
python3 -c "
import json, os
p = os.path.expanduser('~/.hermes/amail_gateway.json')
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg['webhook_host'] = '${WEBHOOK_HOST}'
json.dump(cfg, open(p, 'w'), indent=2)
"
```

#### 4.4.3 可重复运行（幂等性）

- 已有 `amail_gateway.json` → 读取 `webhook_host` 作为每个选项的默认值
- 已有 `amail_bridge.toml` → 作为默认值，不重新部署
- 已有 profile 已注册 → `_auto_register_email` 跳过（`amail.json` 已存在）
- Step 1（gateway_url）/Step 2（auth）已有复用检测

#### 4.4.4 删除项

- Step 5.5 整个 section
- `BRIDGE_DEPLOY`、`BRIDGE_MODE`、`BRIDGE_NEEDED` 变量
- `delivery_mode` 写入
- `bridge_url` 写入
- `amail_bridge.toml` 中 `[push]` section

#### 4.4.5 检测方法

- `bash -n integrate.sh` 语法 OK
- 三种模式各跑一遍

---

### 4.5 可用性测试

**文件**：`amail-gateway/tests/availability_test.sh`

- 8.10a-d 的 probe-webhook 测试保留（API 端点本身仍需测试）— **无需改动**

### 4.6 文档更新

**文件**：`hermes-amail-integration.md`、`hermes-amail-integration-zh.md`

- 删除 `delivery_mode`、`bridge_url` 字段说明
- Step 4 更新为合并后流程
- 删除 Step 5.5 文档
- `amail_gateway.json` 配置表删除过期字段
- 新增 `hostname` 配置说明

---

## 5. 执行步骤与依赖关系

```
Phase 1（可并行）
  ├── 1a: amail-bridge
  │        - config.rs: 新增 hostname 字段
  │        - admin.rs: AdminState 加 config
  │        - admin.rs: create_route 返回 {"status":"ok","webhook_url":"..."}
  │        检测: cargo build --release + curl 验证
  │
  └── 1b: amail-gateway 删 delivery_mode
           - storage.rs: DDL + migration + row mapper + SQL + 函数签名
           - factory.rs: create_domain + update_domain 签名
           - types.rs: 3 个 struct 字段
           - http.rs: create_system_domain + register_address 传参
           - webhook.rs: 判空改法
           检测: cargo build --lib + cargo build --release(advanced) + 可用性测试 85/85

Phase 2（依赖 Phase 1）
  └── 2a: amail_tools.py
           - _auto_register_email 重写
           - 删除: delivery_mode, bridge_url, legacy migration, _is_local_url
           检测: import OK + 集成脚本诊断

Phase 3（依赖 Phase 2）
  └── 3a: integrate.sh Step 4 合并 + 简化
           - GATEWAY_URL is_local 入口分叉（本机 = webhook_host=""）
           - 3 选项（direct/internal/bridge）
           - 验证: GET /health + probe-webhook（仅 direct）
           - 幂等性: 读已有值作为默认值
           - 删除: BRIDGE_DEPLOY/BRIDGE_MODE/BRIDGE_NEEDED, delivery_mode/bridge_url 写入
           检测: bash -n + 三种模式各跑一遍 + 二次运行确认幂等

Phase 4
  └── 4a: 文档更新
           检测: grep delivery_mode/bridge_url docs/ 无残留

Phase 5（验证）
  └── 5a: 全部编译 + 可用性测试 85/85 + 集成脚本全流程
```

## 6. 各步骤检测方法

| 阶段 | 检测方法 |
|------|---------|
| 1a | `cargo build --release`（bridge）；`curl POST /api/v1/routes` → `{"status":"ok","webhook_url":"..."}` |
| 1b | `cargo build --lib`（gateway）；`cargo build --release`（advanced）；可用性测试 85/85 |
| 2a | `python3 -c "import amail_tools"` OK；集成脚本诊断通过 |
| 3a | `bash -n integrate.sh` OK；三种模式各跑一遍；二次运行确认幂等 |
| 4a | `grep -rn 'delivery_mode\|bridge_url' docs/` 无残留 |
| 5a | 完整集成脚本（Step 1→10）跑通 |
