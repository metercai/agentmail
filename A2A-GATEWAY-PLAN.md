# a2a_board — Rust amail-gateway 侧方案

> 在已有 amail-gateway 上新增 board 模块，实现 A 流 19 verb 闭环 + C 流通知 + B 流身份注入

---

## 概述

Rust 侧负责 A 流指令处理、C 流通知发送、B 流身份下传。与 Python agentmail 侧的分工：

| 侧 | 职责 | 不做什么 |
|----|------|---------|
| Rust gateway | A 流 19 verb 执行、board.db 管理、C 流通知、向 payload 注入 board_id/board_role | 不读 SOUL.md/SKILLs、不填充模板 |
| Python agentmail | [WhoAmI] 检测、角色 prompt 文件读取、模板填充、a2a toolset | 不写 board.db、不处理 A 流指令 |

---

## 改动清单

| # | 模块 | 内容 | 行数预估 |
|---|------|------|---------|
| 1 | `board/models.rs` | 数据结构定义 | ~100 |
| 2 | `board/db.rs` | board.db CRUD | ~300 |
| 3 | `board/commands.rs` | 19 verb 业务逻辑 + 授权 | ~400 |
| 4 | `board/handlers.rs` | toolset HTTP API（4 端点） | ~100 |
| 5 | `board/router.rs` | RouterHook 挂载路由 | ~30 |
| 6 | `board/interceptor.rs` | A2aInterceptor 拦截 [A2A] 指令 | ~120 |
| 7 | `board/notify.rs` | C 流通知发送 | ~80 |
| 8 | `board/archiver.rs` | 7 天归档定时器 | ~50 |
| 9 | `core/strategy.rs` | 新增 InboundInterceptor trait | ~30 |
| 10 | `core/webhook.rs` | 拦截器链调用 | ~20 |
| 11 | `main.rs` | 注册 A2aInterceptor + board 路由 | ~15 |


---

## 模块设计

### 1. `board/models.rs` — 数据结构

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Board {
    pub id: String,                           // 20 hex chars (SHA256派生)
    pub short_id: String,                     // 8 位字母数字
    pub board_email: String,                  // <short_id>.a2a@<domain>
    pub status: BoardStatus,                  // active | archived
    pub output_task_id: Option<String>,
    pub plan_version: Option<String>,
    pub plan_confirmed_at: Option<String>,
    pub criteria_confirmed_at: Option<String>,
    pub gateway_url: String,
    pub created_at: String,
    pub completed_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BoardStatus { Active, Archived }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Member {
    pub email: String,
    pub role: String,                          // orchestrator | verifier | worker | human
    pub display_name: String,
    pub domains: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: String,                            // t_{board_id}_{short_id}
    pub short_id: String,                      // T1, T2...
    pub board_id: String,
    pub title: String,
    pub body: String,
    pub status: TaskStatus,
    pub assignee: String,
    pub reviewer: Option<String>,
    pub parent_ids: Vec<String>,
    pub tags: Vec<String>,
    pub summary: String,
    pub created_at: String,
    pub updated_at: String,
    pub completed_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TaskStatus {
    Todo, Ready, Running, Reviewing, Done, Blocked, Cancelled
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskEvent {
    pub id: i64,
    pub task_id: String,
    pub event_type: String,
    pub actor: String,
    pub payload: Option<serde_json::Value>,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct A2aCommand {
    pub verb: String,                          // complete | approve | create | ...
    pub task_id: Option<String>,
    pub params: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandResponse {
    pub status: String,
    pub task: Option<Task>,
    pub error: Option<String>,
}
```

### 2. `board/db.rs` — board.db CRUD

数据库文件路径：`[storage].path/a2a_board/{board_id}/board.db`

```rust
pub fn create_board(db: &Database, board: &Board) -> Result<()>;
pub fn get_board(db: &Database, board_id: &str) -> Result<Board>;
pub fn update_board(db: &Database, board: &Board) -> Result<()>;
pub fn add_member(db: &Database, member: &Member) -> Result<()>;
pub fn get_member(db: &Database, board_id: &str, email: &str) -> Result<Option<Member>>;
pub fn list_members(db: &Database, board_id: &str) -> Result<Vec<Member>>;
pub fn create_task(db: &Database, task: &Task) -> Result<()>;
pub fn get_task(db: &Database, task_id: &str) -> Result<Task>;
pub fn list_tasks(db: &Database, board_id: &str, status: Option<&str>, assignee: Option<&str>) -> Result<Vec<Task>>;
pub fn update_task(db: &Database, task: &Task) -> Result<()>;
pub fn insert_event(db: &Database, event: &TaskEvent) -> Result<()>;
pub fn board_exists(db: &Database, short_id: &str) -> Result<bool>;
pub fn verify_pipeline_integrity(db: &Database, board_id: &str, plan_version: &str) -> Result<Vec<String>>;
```

### 3. `board/commands.rs` — 19 verb 业务逻辑

入口函数：

```rust
pub fn execute_command(db: &Database, notifier: &Notifier, cmd: &A2aCommand, sender: &str) -> Result<CommandResponse> {
    match cmd.verb.as_str() {
        // ── A 流: Rust 闭环 ──
        "complete"    => handle_complete(db, notifier, cmd, sender),
        "approve"     => handle_approve(db, notifier, cmd, sender),
        "reject"      => handle_reject(db, notifier, cmd, sender),
        "block"       => handle_block(db, notifier, cmd, sender),
        "unblock"     => handle_unblock(db, notifier, cmd, sender),
        "heartbeat"   => handle_heartbeat(db, cmd, sender),
        "comment"     => handle_comment(db, notifier, cmd, sender),
        "cancel"      => handle_cancel(db, notifier, cmd, sender),
        "reassign"    => handle_reassign(db, notifier, cmd, sender),
        "edit"        => handle_edit(db, cmd, sender),
        "deadline"    => handle_deadline(db, cmd, sender),
        "output"      => handle_output(db, notifier, cmd, sender),
        "show"        => handle_show(db, cmd),
        "list"        => handle_list(db, cmd, sender),
        "members"     => handle_members(db, cmd),
        "gateway-info"=> handle_gateway_info(db, cmd),
        // ── A 流: 需额外逻辑但 Rust 完成 ──
        "create"      => handle_create(db, notifier, cmd, sender),
        "init"        => handle_init(db, notifier, cmd, sender),
        "arbitrate"   => handle_arbitrate(db, notifier, cmd, sender),
        _ => Err("unknown verb"),
    }
}
```

核心授权规则（每个 handler 内校验）：

| verb | 授权条件 |
|------|---------|
| complete | `sender == task.assignee` |
| approve/reject | `sender == task.reviewer` |
| block | 任意项目成员 |
| unblock | `member.role == "orchestrator"` 或 `member.role == "human"` |
| heartbeat/comment | 任意项目成员 |
| cancel/reassign/edit/deadline | `member.role == "orchestrator"` |
| output | `member.role == "verifier"` |
| create | `member.role == "orchestrator"` |
| init | API key scope 含 `agent_admin` |
| arbitrate | `member.role == "orchestrator"` 或 `member.role == "verifier"` |
| show/list/members/gateway-info | 任意项目成员（gateway-info 公开）|

### 4. `board/handlers.rs` — toolset HTTP API

4 个只读/心跳端点，供 Python a2a toolset 使用：

```rust
// GET /api/v1/board/{board_id}/task/{task_id}
pub async fn handle_get_task(...) -> Json<Value>;

// GET /api/v1/board/{board_id}/tasks?status=...&assignee=...
pub async fn handle_list_tasks(...) -> Json<Value>;

// GET /api/v1/board/{board_id}/members
pub async fn handle_list_members(...) -> Json<Value>;

// POST /api/v1/board/{board_id}/task/{task_id}/heartbeat
pub async fn handle_post_heartbeat(...) -> Json<Value>;
```

认证：API key → email → project_members 校验。`heartbeat` 额外校验 `sender == task.assignee`。

### 5. `board/router.rs` — 路由注册

```rust
use crate::core::strategy::RouterHook;

pub struct BoardRouter;

impl RouterHook for BoardRouter {
    fn mount(router: Router) -> Router {
        router
            .route("/api/v1/board/{board_id}/task/{task_id}",     get(handle_get_task))
            .route("/api/v1/board/{board_id}/tasks",              get(handle_list_tasks))
            .route("/api/v1/board/{board_id}/members",            get(handle_list_members))
            .route("/api/v1/board/{board_id}/task/{task_id}/heartbeat", post(handle_post_heartbeat))
    }
}
```

### 6. `board/interceptor.rs` — A2aInterceptor

```rust
#[async_trait]
impl InboundInterceptor for A2aInterceptor {
    fn name(&self) -> &str { "A2aInterceptor" }
    fn priority(&self) -> u32 { 20 }  // 管理员 10, A2A 20, ping-pong 30

    async fn intercept(&self, record: &EmailRecord, payload: &mut Value) -> InterceptorDecision {
        let subject = payload["subject"].as_str().unwrap_or("");
        let sender = payload["from"].as_str().unwrap_or("");

        // ── A 流: [A2A] prefix → Rust 闭环 ──
        if let Some(rest) = subject.strip_prefix("[A2A] ") {
            let verb = rest.split_whitespace().next().unwrap_or("");
            // 从 board_email 解析 board_id
            let to_addr = payload["to"].as_str().unwrap_or("");
            let board_id = parse_board_id(to_addr)?;
            let db = open_board_db(&board_id)?;
            let notifier = Notifier::new(&db, &self.email_factory);

            let cmd = A2aCommand { verb, task_id, params };
            let result = commands::execute_command(&db, &notifier, &cmd, sender);
            
            // 回复发送者
            smtp_reply(record, &result)?;
            return InterceptorDecision::Handled;
        }

        // ── B 流: 非 [A2A] 但来自 board 参与者 → 注入身份 ──
        let to_addr = payload["to"].as_str().unwrap_or("");
        if let Some(board_id) = parse_board_id(to_addr) {
            let db = open_board_db(&board_id)?;
            if let Some(member) = db.get_member(&board_id, sender)? {
                payload["board_id"] = Value::String(board_id);
                payload["board_role"] = Value::String(member.role);
            }
        }

        InterceptorDecision::PassThrough  // 放行给 webhook
    }
}
```

解析 board_id 的辅助函数：

```rust
fn parse_board_id(to_addr: &str) -> Option<String> {
    // to_addr: xk9mp2q.a2a@mail.hermes.io
    // 或 thread 中的任意参与者地址
    let (local, domain) = to_addr.split_once('@')?;
    let short_id = local.strip_suffix(".a2a")?;
    Some(derive_board_id(short_id, domain))
}
```

### 7. `board/notify.rs` — C 流通知

```rust
pub struct Notifier<'a> {
    db: &'a Database,
    email_factory: &'a EmailFactory,
}

impl Notifier {
    pub fn notify_assigned(&self, task: &Task);
    pub fn notify_review_needed(&self, task: &Task);
    pub fn notify_approved(&self, task: &Task);
    pub fn notify_rejected(&self, task: &Task, reason: &str);
    pub fn notify_blocked(&self, task: &Task, blocker: &str);
    pub fn notify_unblocked(&self, task: &Task, unblocker: &str);
    pub fn notify_cancelled(&self, task: &Task);
    pub fn notify_output(&self, task: &Task);
    pub fn notify_comment(&self, task: &Task, commenter: &str);
    pub fn notify_arbitrate(&self, task: &Task, requester: &str, admin: &str);
    pub fn notify_all(&self, board_id: &str, message: &str);
}
```

每条通知调用 `EmailFactory.send_outbound()`，由现有路由引擎决定投递路径：

- **同一 gateway 的参与者**（收件人域名匹配本 gateway 的 system_domain）：
  → 走 webhook 投递（`process_email_webhook`），进入收件人的 inbox
  → 收件人 agent 的 preprocessor 处理
- **外部参与者**（收件人域名不在本 gateway）：
  → `INSERT INTO email_records` → SMTP relay → 外部邮件服务器
  → 由对方的 gateway 或普通邮件客户端接收

路由判断由 `EmailFactory` 内部完成（查 `system_domains` 表判断域名归属），通知模块不关心投递路径。

### 8. `board/archiver.rs` — 归档

```rust
pub fn archive_loop(db_pool: &DbPool) {
    // 每小时扫描一次
    loop {
        for db in db_pool.iter() {
            let expired = db.query(
                "UPDATE boards SET status='archived'
                 WHERE status='active' AND completed_at < datetime('now', '-7 days')"
            );
        }
        thread::sleep(Duration::from_secs(3600));
    }
}
```

### 9. `core/strategy.rs` — 新增 trait

```rust
#[async_trait]
pub trait InboundInterceptor: Send + Sync {
    fn name(&self) -> &str;
    fn priority(&self) -> u32;
    async fn intercept(&self, record: &EmailRecord, payload: &mut Value) -> InterceptorDecision;
}

pub enum InterceptorDecision {
    Handled,      // 已处理，跳过 webhook
    PassThrough,  // 未处理，继续下一个
}
```

### 10. `core/webhook.rs` — 拦截器链调用

在 `process_email_webhook` 函数中，构建 payload 后、构造 webhook POST body 前，依次调用所有已注册的拦截器：

```rust
let mut payload = build_webhook_payload(record);
for interceptor in &self.interceptors {
    match interceptor.intercept(record, &mut payload).await {
        InterceptorDecision::Handled => return Ok(()),  // 跳过 webhook
        InterceptorDecision::PassThrough => continue,
    }
}
// ... 继续发送 webhook
```

### 11. `main.rs` — 注册

```rust
// board 模块（默认编译）
let a2a_interceptor = Arc::new(board::interceptor::A2aInterceptor::new(...));
app.register_interceptor(a2a_interceptor);
app = board::router::BoardRouter::mount(app);
```

### 12. `Cargo.toml` — feature gate

```toml
# [features] 取消注释
default = []
# board 模块默认编译，不设 feature gate
```



---

## B 流身份注入流程

```
SMTP 收到邮件
  ↓
Rust 解析 → EmailRecord
  ↓
process_email_webhook 构建 payload
  ↓
InboundInterceptor 链（priority 排序）:
  10: ManagerInterceptor（管理员指令，如匹配则 Handled）
  20: A2aInterceptor:
        Subject 以 [A2A] 开头？→ A 流，Rust 闭环
        非 [A2A] 但 to 地址含 .a2a 后缀？→ 注入 board_id + board_role → PassThrough
        其他 → 直接 PassThrough
  30: PingPongInterceptor（ping-pong 拦截）
  ↓
webhook POST → Python preprocess_mail_payload
  ↓
[WhoAmI] 检测 → 设 _whoami_prompt | board_id + board_role → 设 _role_prompt + _a2a_session_key
  ↓
BLOCK3 消费 → 追加 prompt / 覆盖 session_chat_id
  ↓
LLM session
```

---

## 数据目录

```
[storage].path/a2a_board/{board_id}/board.db

示例：storage.path = /var/lib/amail-gateway
  → /var/lib/amail-gateway/a2a_board/a3f8c21b9d4e73b2f0c1/board.db
```

---

## 实现阶段

| Phase | 内容 | 前置 |
|-------|------|------|
| P0 | `board/models.rs` + `board/db.rs` | 现有 amail-gateway |
| P0 | `board/commands.rs` | P0 db |
| P0 | `board/notify.rs` | 现有 core EmailFactory |
| P0 | `board/interceptor.rs` | P0 commands |
| P0 | `board/router.rs` + `handlers.rs` | P0 db |
| P1 | `core/strategy.rs` + `core/webhook.rs` | — |
| P1 | `main.rs` 注册 board 模块 | P0 + P1 core |
| P2 | `board/archiver.rs` | P0 db |
| P2 | 全链路 E2E 测试 | P0-P1 |
