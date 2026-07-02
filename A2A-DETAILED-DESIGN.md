# A2A项目看板系统 — 详细设计

> a2a_board — Rust board module + Python preprocessor + Hermes integration

---

## 一、数据模型

### board.db Schema

路径：`[storage].path/a2a_board/{board_id}/board.db`

```sql
CREATE TABLE boards (
    id TEXT PRIMARY KEY,                   -- 20 hex chars (SHA256 派生)
    short_id TEXT UNIQUE NOT NULL,          -- 8 位字母数字组合，人类可读
    board_email TEXT NOT NULL,             -- <short_id>.a2a@<gateway_domain>
    status TEXT DEFAULT 'active',          -- active | archived
    output_task_id TEXT,                   -- 最终输出 task（由方案指定）
    plan_version TEXT,                     -- 当前编排方案版本号
    plan_confirmed_at TEXT,                -- Admin 确认方案时间
    criteria_confirmed_at TEXT,            -- Admin 确认验收标准时间
    gateway_url TEXT,                      -- 本 gateway 的 HTTP URL
    created_at TEXT,
    completed_at TEXT
);

CREATE TABLE board_members (
    email TEXT PRIMARY KEY,
    role TEXT NOT NULL,                    -- orchestrator | verifier | worker | human
    display_name TEXT,
    board_id TEXT REFERENCES boards(id),
    joined_at TEXT,
    domains TEXT,                          -- JSON array, e.g. '["database","cost"]'
    capability_snapshot TEXT               -- JSON, 能力自述存档
);

CREATE TABLE roles (
    name TEXT PRIMARY KEY,
    description TEXT
);

CREATE TABLE role_permissions (
    role TEXT REFERENCES roles(name),
    verb TEXT,                             -- create | complete | output | ...
    scope TEXT                             -- own | project
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,                   -- t_a1b2c3d4
    short_id TEXT,                         -- T1, T2, ...
    board_id TEXT REFERENCES boards(id),
    title TEXT,
    body TEXT,
    status TEXT DEFAULT 'todo',            -- todo|ready|running|reviewing|done|blocked|cancelled
    assignee TEXT REFERENCES board_members(email),
    reviewer TEXT,                         -- NULL = 不需要审阅
    parent_ids TEXT,                       -- JSON array, e.g. '["T1", "T2"]'
    tags TEXT,                             -- JSON array, e.g. '["cost","aws"]'
    summary TEXT,
    metadata TEXT,                         -- JSON
    created_by TEXT,
    created_at TEXT,
    updated_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    deadline TEXT
);

CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES tasks(id),
    event_type TEXT,                       -- completed | approved | rejected | blocked | ...
    actor TEXT,                            -- sender email
    payload TEXT,                          -- JSON, e.g. '{"reason":"need more data"}'
    created_at TEXT
);
```

---





### board_id 与 short_id 生成算法

`board_id` 由 `short_id + gateway_domain` 派生散列得到。`short_id` 由创建者设定，`board_id` 自动计算。

#### short_id（8 位字母数字组合，创建者设定）

```rust
fn validate_short_id(id: &str) -> Result<()> {
    if id.len() != 8 {
        return Err("short_id must be exactly 8 characters");
    }
    if !id.chars().all(|c| c.is_ascii_alphanumeric()) {
        return Err("short_id must be alphanumeric");
    }
    if db.short_id_exists(id) {
        return Err("short_id already taken");
    }
    Ok(())
}
```

- **长度**：8 字符（固定）
- **字符集**：a-z + 0-9（不区分大小写，存储时统一小写）
- **碰撞检测**：创建时检查 boards 表
- **建议**：项目相关词根 + 数字，如 `pgmig001`、`costv2`、`blogplf`

#### board_id（20 hex 字符 = 10 字节，由 short_id + gateway_domain 派生）

```rust
use sha2::{Sha256, Digest};

fn derive_board_id(short_id: &str, gateway_domain: &str) -> String {
    let input = format!("{}:{}", short_id.to_lowercase(), gateway_domain);
    let hash = Sha256::digest(input.as_bytes());
    hex::encode(&hash[..10])
    // 取前 10 字节 = 80 bit，全局多 gateway 碰撞概率可忽略
}
```

| 输入 | 输出 |
|------|------|
| short_id=pgmig001, domain=mail.hermes.io | a3f8c21b9d4e73b2f0c1 |

- **算法**：SHA256(short_id + ":" + gateway_domain)，取前 10 字节（20 hex 字符）
- **确定性**：相同输入产生相同输出
- **全局唯一性**：不同 domain 即使 short_id 相同也产生不同 board_id；同一 domain 下 short_id 唯一性由创建时碰撞检测保证

#### board_email（由 short_id 派生）

```
board_email = f"{short_id}.a2a@{gateway_domain}"

示例：
  short_id:      pgmig001
  gateway_domain: mail.hermes.io
  board_id:      a3f8c21b9d4e73b2f0c1
  board_email:   pgmig001.a2a@mail.hermes.io
```

SMTP 收到 `*.a2a@domain` 的邮件 → 提取 short_id → 派生 board_id → 打开 board.db：

```rust
fn parse_board_email(to_addr: &str) -> Option<(String, String)> {
    let (local, domain) = to_addr.split_once('@')?;
    let short_id = local.strip_suffix(".a2a")?;
    let board_id = derive_board_id(short_id, domain);
    Some((short_id.to_string(), board_id))
}
```

#### 标识一览

| 标识 | 示例 | 生成方式 | 用途 | 谁读 |
|------|------|---------|------|------|
| short_id | pgmig001 | 创建者设定 | 邮件地址前缀、Subject 引用 | 人 |
| board_id | a3f8c21b9d4e73b2f0c1 | SHA256派生（10字节/20hex） | 数据库PK、API路径、Board-ID头、文件目录 | 机器 |
| board_email | pgmig001.a2a@mail.hermes.io | short_id + domain 拼接 | Board 的 agentmail 地址 | 人+机器 |

#### Board-ID 邮件头

所有 A/B/C 流邮件在发送时必须在邮件头中包含 `Board-ID`，值为 `board_id`：

```
Board-ID: a3f8c21b9d4e73b2f0c1
```

Rust 拦截器通过此 header 直接构建文件路径。人类在邮件 Subject 中通过 short_id（如 `[Proposal] pgmig001 方案 v1`）识别看板。

路径结构：

```
[storage].path/a2a_board/{board_id}/board.db
示例：/var/lib/amail-gateway/a2a_board/a3f8c21b9d4e73b2f0c1/board.db
```

---

## 二、HTTP API 端点

所有端点以 `/api/v1/board/` 前缀与 gateway 其他 API（admin/contacts/send 等）隔离。
项目通过 URL 路径中的 `{board_id}` 区分。

### 端点列表（仅 toolset 使用）

| 方法 | 路径 | 请求体/参数 | 对应 tool | 说明 |
|------|------|-----------|-----------|------|
| GET | `/api/v1/board/{board_id}/task/{task_id}` | — | `a2a_show(task_id)` | 查询单个 task |
| GET | `/api/v1/board/{board_id}/tasks` | `?status=running&assignee=user@d` | `a2a_list(project, status?, assignee?)` | 按条件过滤 task 列表 |
| GET | `/api/v1/board/{board_id}/members` | — | `a2a_members(project)` | 查询成员列表 |
| POST | `/api/v1/board/{board_id}/task/{task_id}/heartbeat` | `{ note }` | `a2a_heartbeat(task_id, note)` | 发心跳 |

### 不走 HTTP API 的操作

全部 19 个 verb 指令、Board 创建、gateway-info 查询均通过邮件指令（`[A2A]` 发送到 Board）处理，不暴露 HTTP 端点：

- **原因**：所有 A 流操作需要 email 审计痕迹（email_records 表永久保存）
- **例外**：高频只读查询（show/list/members）和心跳用 toolset 替代邮件，减少 SMTP 往返

### 认证与授权

| 端点 | 授权要求 | 依据 |
|------|---------|------|
| `GET /task/:id` | 项目成员 | API key -> email -> board_members |
| `GET /tasks` | 项目成员 | API key -> email -> board_members |
| `GET /members` | 项目成员 | API key -> email -> board_members |
| `POST /heartbeat` | 项目成员 + 该 task 的 assignee | API key -> email -> task.assignee 校验 |

API key 沿用 amail-gateway 现有机制：每个 key 关联一个 `email_address`，通过该地址在项目成员表中查询角色权限。

```rust
fn authorize(api_key, board_id) -> Result<Member> {
    let email = &api_key.email_address;
    let member = db.get_member_by_email(board_id, email)?;
    if member.is_none() {
        return Err("not a member of this project");
    }
    Ok(member)
}
```

### 错误响应

```json
{ "error": "not a member of this project", "code": "FORBIDDEN" }
{ "error": "project archived", "code": "GONE" }
{ "error": "task not found", "code": "NOT_FOUND" }
```

---

## 三、状态机

```
Todo → Ready → Running ───→ Done          (无 reviewer)
                  │
                  ├──→ Reviewing ──→ Done   (approve)
                  │    (有 reviewer) ──→ Running (reject)
                  │
                  └──→ Blocked ──→ Running
                              └──→ Cancelled (终态)
```

| 状态 | 含义 | 转换触发 |
|------|------|---------|
| todo | 有未完成的 parent | promote_children() 检测所有 parent=done |
| ready | 可分配 | create 指定，或 parent promote |
| running | 执行中 | 分配到 Worker |
| reviewing | 等待审阅 | task 有 reviewer，complete 后进入 |
| done | 完成 | Worker 或审阅者 complete |
| blocked | 阻挡 | 任意成员发送 block |
| cancelled | 取消（终态） | 发送 cancel |

### Promote 规则

`promote_children()`：所有 parent 的 status = `done` 即 promote。不区分是 Worker 直接完成还是审阅后完成。

---

## 四、指令执行路径

所有 [A2A] 指令邮件到达 Board 的 agentmail 地址，由 Rust A2aInterceptor 统一处理。

### 处理决策

```
[A2A] 指令邮件 → A2aInterceptor
  │
  ├─ Subject 提取 verb → commands.rs 分发
  │
  ├─ 16 个 verb：Rust 直接闭环
  │   complete/approve/reject/block/unblock/heartbeat/comment
  │   cancel/reassign/edit/deadline/output
  │   show/list/members/gateway-info
  │   → 校验权限 → 读/写 board.db → SMTP 回复 → Handled
  │
  ├─ 3 个 verb：Rust 直接处理（不走 Python，不需要 LLM）
  │   create    → 解析 task graph、校验 DAG、批量写入 board.db
  │   init      → 调用 EmailFactory 发欢迎邮件、写入白名单
  │   arbitrate → 校验角色、EmailFactory 发邮件给 Admin
  │   → 全部在 Rust 侧完成 → Handled
  │
  └─ 全部返回 InterceptorDecision::Handled
     → 不经过 webhook，不启动 agent session
```

### 路径 A: Rust 闭环（全部 19 个 verb）

```
complete/approve/reject/block/unblock/heartbeat/comment
cancel/reassign/edit/deadline/output
show/list/members/gateway-info

→ 校验权限 → 读/写 board.db → SMTP 回复 → InterceptorDecision::Handled
→ 不经过 webhook，不启动 agent session
```

**complete 执行逻辑：**

```rust
fn handle_complete(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;
    if task.assignee != sender {
        return Err("only assignee can complete");
    }
    task.status = if task.reviewer.is_some() {
        Status::Reviewing
    } else {
        Status::Done
    };
    db.update_task(task);
    db.insert_event(task.id, "completed", sender);
    if task.reviewer.is_some() {
        smtp.reply(cmd.from, "任务已提交审阅，等待 " + task.reviewer);
        smtp.notify(task.reviewer, "待审阅: " + task.id);
    } else {
        smtp.reply(cmd.from, "任务已完成，promote children");
        promote_children(task, db, smtp);
    }
    return InterceptorDecision::Handled;
}
```

**approve / reject 执行逻辑：**

```rust
fn handle_approve(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;
    if task.reviewer.as_deref() != Some(&sender) {
        return Err("you are not the assigned reviewer");
    }
    task.status = Status::Done;
    db.update_task(task);
    db.insert_event(task.id, "approved", sender);
    smtp.reply(cmd.from, "审阅通过");
    smtp.notify(&task.assignee, task.id + " 已通过审阅");
    promote_children(task, db, smtp);
    return InterceptorDecision::Handled;
}

fn handle_reject(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;
    if task.reviewer.as_deref() != Some(&sender) {
        return Err("you are not the assigned reviewer");
    }
    task.status = Status::Running;  // 退回 Worker
    db.update_task(task);
    db.insert_event(task.id, "rejected", sender);
    smtp.reply(cmd.from, "已退回 " + task.assignee + " 返工");
    smtp.notify(&task.assignee, task.id + " 被退回: " + cmd.params["reason"]);
    return InterceptorDecision::Handled;
}
```

**output 执行逻辑（含校验）：**

```rust
fn handle_output(cmd, sender) {
    let project = db.get_project()?;
    let member = db.get_member_by_email(&sender)?;

    if member.role != "verifier" {
        return Err("only verifier can output");
    }

    let output_task = db.get_task(&project.output_task_id)?;
    if output_task.status != Status::Done {
        return Err("output task is not done yet");
    }

    // 校验中间产物流转合规
    let issues = db.verify_pipeline_integrity(project.id, project.plan_version)?;
    if !issues.is_empty() {
        return Err("pipeline issues: " + issues.join(", "));
    }

    project.status = Status::Completed;
    db.update_project(project);
    db.insert_event(output_task.id, "output", sender);
    smtp.notify_all(project.id, "项目输出已放行: " + output_task.summary);
    return InterceptorDecision::Handled;
}
```

**只读/轻量操作：**

```rust
fn handle_heartbeat(cmd, sender) {
    db.touch_task(cmd.task_id);
    db.insert_event(cmd.task_id, "heartbeat", sender);
    smtp.reply(cmd.from, "heartbeat recorded");
    return InterceptorDecision::Handled;
}

fn handle_gateway_info(cmd, sender) {
    let info = db.get_gateway_info();
    smtp.reply(cmd.from, "gateway_url: " + info.url +
        "\napi_version: v1\nboard_email: " + info.board_email);
    return InterceptorDecision::Handled;
}
```

### 路径 A 扩展：create / init / arbitrate 的 Rust 实现

这三个 verb 不走 Python，全部在 Rust 侧完成。

**init（项目初始化）：**

```rust
fn handle_init(cmd, sender) {
    let members: Vec<Member> = cmd.params["members"];
    let board_id = cmd.board_id;

    // 1. 写入 board.db
    db.init_project(board_id, members, cmd.params["board_email"],
                    cmd.params["gateway_url"]);

    // 2. 写入 agentmail 白名单（通过内部 API）
    for m in &members {
        email_factory.add_contact(&m.email, "all").await?;
    }

    // 3. 发欢迎通知
    let notify = Notifier::new(db, email_factory);
    notify.notify_all(board_id, "项目已初始化，请准备能力自述");

    smtp.reply(cmd.from, "项目已初始化，参与者: " + members.len());
    return InterceptorDecision::Handled;
}
```

**create（按编排方案创建 task 树）：**

```rust
fn handle_create(cmd, sender) {
    let board_id = cmd.board_id;
    let tasks: Vec<TaskDef> = cmd.params["tasks"];

    // 1. 校验 task graph
    let project = db.get_project(board_id)?;
    for t in &tasks {
        // 所有 parent 必须在本次创建中
        for p in t.parents {
            if !tasks.iter().any(|x| x.short_id == p) {
                return Err("parent " + p + " not found in this batch");
            }
        }
        // assignee 必须在 board_members 中
        if !db.is_member(board_id, &t.assignee) {
            return Err("assignee " + t.assignee + " not in project");
        }
    }

    // 2. 校验无环（DFS）
    if detect_cycle(&tasks) {
        return Err("task graph contains cycle");
    }

    // 3. 批量写入 board.db
    for t in &tasks {
        let task_id = db.create_task(board_id, t);
        let notify = Notifier::new(db, email_factory);
        notify.notify_assigned(&task);
    }

    smtp.reply(cmd.from, "已创建 " + tasks.len() + " 个 task");
    return InterceptorDecision::Handled;
}
```

**arbitrate（提请管理员仲裁）：**

```rust
fn handle_arbitrate(cmd, sender) {
    let member = db.get_member_by_email(&sender)?;

    // 仅 Orchestrator 或 Verifier 可仲裁
    if member.role != "orchestrator" && member.role != "verifier" {
        return Err("only orchestrator or verifier can arbitrate");
    }

    // 发邮件给 Admin
    let admin_email = db.get_admin_email()?;
    email_factory.send_outbound(Email::new()
        .to(admin_email)
        .subject("[A2A] arbitrate: " + extract_summary(cmd))
        .body("仲裁请求来自 " + sender + "\n\n" + cmd.params["dispute"])
    ).await?;

    // 回复发送者
    smtp.reply(cmd.from, "仲裁请求已提交给 Admin");
    return InterceptorDecision::Handled;
}
```

### 路径 C: LLM agent session（无 A2A 指令）

所有 Rust 闭环和 preprocessor 直接处理的指令都不启动 agent session。只有以下场景启动 LLM：

- **日常对话** — 参与者之间的非 A2A 邮件
- **[Proposal] 评议邮件** — 编排方案的讨论
- **能力问询回复（非 Hermes 系统兜底）**

Board 的 agentmail 地址永远不会启动 LLM session。

| gateway-info | 任意成员 | A: Rust 闭环 | — |

---

## 五、成员间对话邮件（B 流）

成员间对话不经过 Board，直接通过 agentmail 在参与者之间往来。所有 B 流邮件由接收方的 agent session 处理（含 LLM 推理），Cc: Board 用于存档。

### B 流对话类型一览

| 类型 | 主题格式 | 发起方 | 参与方 | 说明 |
|------|---------|--------|--------|------|
| B1: 能力问询 | `[A2A] capability-inquiry` | Orchestrator | 每个成员 | 编排前置，了解成员能力 |
| B2: 编排方案评议 | `[Proposal] <项目> 方案 v<N>` | Orchestrator | 全体 | 对任务分解和分配达成共识 |
| B3: 验收标准确认 | `[Criteria] <项目> 验收标准 v<N>` | Verifier | 全体 | 对最终产出物检验标准达成共识 |
| B4: 阶段汇报 | `[Report] Phase <N>: <标题>` | 负责人 | 全体 | 阶段性进展总结 |
| B5: 互评 | `[Review] 关于 <对象> <任务>` | 任意成员 | 指定对象 | 针对任务或协作质量的评价 |
| B6: 任务讨论 | `<Task-ID> <主题>` | 任意成员 | 相关人员 | 执行细节讨论 |
| B7: Admin 确认 | `Re: [Proposal]/[Criteria]` | Orchestrator/Verifier | Admin | 最终审批 |

所有 B 流邮件 **Cc: board@project.a2a**。Board 不处理这些邮件的内容，但 Board 在 Cc 中可以记录事件日志（通过 task_events 记录 "proposal_sent"、"criteria_proposed" 等事件类型）。

### B1: [A2A] capability-inquiry（能力问询）

**方向：** Orchestrator → 每个成员

Orchestrator 发：

```
To: researcher-a@sys-a
Subject: [A2A] capability-inquiry
Body:
  project: postgres-migration
  请描述你的能力范围和专长，以便我为你分配合适的任务。
```

成员回复（Hermes 系统——preprocessor 直接回复，不走 LLM）：

```
To: orchestrator@hermes.a2a
Subject: Re: [A2A] capability-inquiry
Body:
  email: researcher-a@sys-a
  role: 云成本分析师
  skills_loaded: [agentmail, data-analysis, aws-cost]
  expertise:
    - AWS 服务定价模型与成本建模
    - 跨云厂商 TCO 对比分析
  constraints:
    - 不擅长数据库性能基准测试
    - 没有安全合规审计经验
```

**执行路径：** preprocessor 检测 Subject → 读取 SOUL.md + SKILL list → 填充 whoami.md 占位符 → 设置 _capability_inquiry_data（含填充后的 whoami.md 正文 + 问询者地址）→ _skip_delivery=False（放行给 agent session）→ LLM 看到填充后的 whoami.md → 按要求的格式组装能力声明 → send_mail() 回复问询者

### B2: [Proposal] 编排方案评议

**方向：** Orchestrator → 全体参与者（Cc: Board）

Orchestrator 发：

```
To: researcher-a@sys-a, researcher-b@sys-b, verifier@hermes.a2a
Cc: board@postgres-mig.a2a
Subject: [Proposal] Postgres 迁移 — 编排方案 v1
Body:
  ## 编排方案

  Phase 1: 调研（并行）
  T1: AWS 成本分析
    assignee: researcher-a（理由：AWS 成本建模专长）
    reviewer: null
  描述：对比 AWS Aurora / GCP Cloud SQL 在 5TB 下的 3 年 TCO

  T2: 性能基准测试
    assignee: researcher-b（理由：数据库基准测试专长）
    reviewer: null

  Phase 2: 综合（串行，依赖 T1+T2）
  T3: 综合推荐
    assignee: synthesizer（理由：技术写作专长）
    reviewer: verifier@hermes.a2a
  输出: verifier@hermes.a2a

  请评议。每位成员请根据自己的经验判断。
```

参与者回复评议（每个参与者自己的 LLM session 处理）：

```
To: orchestrator@hermes.a2a
Cc: board@postgres-mig.a2a
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v1
Body:
  整体方案合理。两点建议：
  1. T1 的 review 建议由 verifier 做，researcher-a 在成本方面最擅长，
     但缺少交叉检视。
  2. 补充 Phase 1 增加 T3: GCP 成本调研（并行），
     assignee: researcher-a（利用 T1 调研成果顺便做）。
```

Orchestrator 修订 v2 → 重新发出 → 重复直到共识。

**执行路径：** 正常 agent session → agentmail SKILL + 注入的角色 prompt（orchestrator/verifier/worker）→ LLM 处理 → send_mail() 回复

### B3: [Criteria] 验收标准确认

编排方案被 Admin 确认后，Verifier 基于方案中的 task 分解和最终产出物描述，发起验收标准确认。

**方向：** Verifier → 全体参与者（Cc: Board）

```
From: verifier@hermes.a2a
To: orchestrator@hermes.a2a, researcher-a@sys-a, ...
Cc: board@postgres-mig.a2a
Subject: [Criteria] Postgres 迁移 — 验收标准 v1
Body:
  基于编排方案 T4（决策备忘录），拟定验收标准如下：

  验收标准:
  1. 文档包含 AWS/GCP/自建 三种方案的 3 年 TCO 对比表
  2. 风险矩阵不少于 5 项，每项含影响/概率/缓解措施
  3. 回退方案具备可操作性（步骤具体到命令级）
  4. 推荐结论附带数据引用（至少 3 个独立数据源）
  5. 决策备忘录适合 CTO 阅读（< 5 页，含摘要）

  以上标准是否清晰、可执行、无遗漏？请评议。
```

参与者回复评议：

```
From: orchestrator@hermes.a2a
To: verifier@hermes.a2a
Cc: board@postgres-mig.a2a
Subject: Re: [Criteria] Postgres 迁移 — 验收标准 v1
Body:
  标准清晰。建议补充一项：
  6. 时间成本估算：包含迁移窗口、回滚时间、人员培训成本
```

Verifier 修订 → v2, v3... 直到共识。最终版本写入 board.db 作为 output task 的 metadata。

```
From: verifier@hermes.a2a
To: admin@company.com
Subject: Re: [Criteria] Postgres 迁移 — 验收标准 v3
Body:
  验收标准经全体评议已达成一致。@admin 请确认。

  (标准全文)
```

Admin 确认后，Verifier 在 output 时对照标准逐项检验。

**执行路径：** 正常 agent session → agentmail SKILL + verifier 角色 prompt → LLM 处理 → send_mail() 回复

### B4: [Report] 阶段汇报

**方向：** Orchestrator 或 Human Admin → 全体（Cc: Board）

阶段汇报是全局层面的进展总结，仅由项目管理者（Orchestrator 或 Admin）发起。Worker 不发起阶段汇报。Worker 可以通过以下方式表达进度：

- **A 流** `[A2A] complete` — 标记 task 完成，携带 summary
- **A 流** `[A2A] heartbeat` — 长任务更新进度
- **B 流** `[Review]` 或任务讨论 — 涉及他人的协作沟通

发起者示例（Orchestrator）：

```
From: orchestrator@hermes.a2a
To: 全体成员
Cc: board@postgres-mig.a2a
Subject: [Report] Phase 1: 调研阶段 — 完成汇报
Body:
  ## Phase 1 完成情况

  T1: 成本分析 ✅ (researcher-a)
  T2: 性能测试 ✅ (researcher-b)
  T3: GCP 成本调研 ✅ (researcher-a)
  审阅记录: 3 个 task 全部通过审阅

  ## 遇到问题
  - AWS 账单数据延迟 2 天，已协调解决

  ## Phase 2 准备
  所有依赖已就绪，建议按期启动 Phase 2。
```

验证和回复：

```
From: verifier@hermes.a2a
To: orchestrator@hermes.a2a
Cc: board@postgres-mig.a2a
Subject: Re: [Report] Phase 1 — 完成汇报
Body:
  收到。Phase 1 交付物质量符合预期。
  Phase 2 可以按期启动。建议 T4 增加安全评估项，请纳入方案修订。
```

**谁可以发起：** 任何在 Phase 中负责的成员（Orchestrator 通常发起阶段总结，Worker 也可发起自己部分的工作汇报）

**执行路径：** 正常 agent session → agentmail SKILL + 角色 prompt → LLM 处理 → send_mail()

### B5: [Review] 互评

**方向：** 任意成员 → 评价对象（Cc: Board）

格式：

```
Subject: [Review] 关于 researcher-a T1 执行质量的评价
To: orchestrator@hermes.a2a
Cc: board@postgres-mig.a2a
Body:
  评价对象: researcher-a@sys-a
  任务: T1 (成本分析)
  评价: 数据建模扎实，定价模型覆盖全面，文档结构清晰。
  建议: 下次可以提前标注数据源假设，便于审阅。

  评分: 4/5
```

互评不是强制要求，基于自愿原则。评价记录存入 task_events，可用于后续项目编排时了解成员的协作表现。

**触发场景：**
- task 完成后，协作方或审阅方主动发起
- 项目完成后，Orchestrator 组织全员互评

**校验：** 仅项目成员可发起（通过 board_members 表校验）

### B6: 任务讨论

**方向：** 任意成员（含 Worker） → 相关人员（Cc: Board）

Worker 可以针对自己执行的 task 发起讨论，也可以参与他人的 task 讨论。

```
Subject: T2 pgbench 参数讨论
To: researcher-b@sys-b
Cc: board@postgres-mig.a2a
Body:
  关于 T2 的 pgbench 模拟负载，
  建议调整 scale factor 到 1000 以覆盖 5TB 场景。
  你认为呢？
```

讨论过程由标准 email threading 维护，email_summary() 可查询。Board 不处理，只通过 Cc 记录事件。

### B7: Admin 确认

Admin 的确认是项目进入可执行状态的关键节点。确认过程需要 Board 记录在案。

**方向：** Orchestrator/Verifier → Admin（Cc: Board）

```
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v3
Body:
  编排方案经全体评议已达成一致。@admin 请确认执行。
  (方案全文)
```

Admin 回复 "确认执行" → 邮件到达 Orchestrator（To）和 Board（Cc）。

**Board 侧（Rust A2aInterceptor）：**
- 检测到 Cc 中的确认邮件
- 记录 `task_events: { event_type: "admin_confirmed", actor: admin@company, payload: {plan_version: "v3"} }`
- 更新 projects 表 `plan_confirmed_at = now`
- 不回复（确认邮件已到达 Orchestrator）

**Orchestrator/Verifier 侧（LLM session）：**
- preprocessor 注入角色 prompt
- LLM 识别 Admin 确认
- Orchestrator 执行 [A2A] create（编排方案生效）
- Verifier 启动验收标准确认流程（验收标准生效）

**状态变化：**
```
编排方案确认前: project.status = "active"
  （已初始化但未确认方案，不可执行）
编排方案 Admin 确认后: project.plan_confirmed_at = now
  （Orchestrator 可执行 create）
验收标准 Admin 确认后: project.criteria_confirmed_at = now
  （Verifier 可执行 output 前的校验）
output 执行后: project.status = "completed"
7 天后: project.status = "archived"
```

**执行路径：** Admin 回复
  → Board（Cc）收到：Rust 记录 confirmation + 更新 plan_confirmed_at
  → Orchestrator（To）收到：preprocessor 注入角色 prompt → LLM 识别确认 → 执行下一步

---

## 六、Board 通知邮件（C 流）

Board 状态变化时由 Rust notify 模块自动发送。所有通知纯机械，无 LLM 参与。

### notify 模块 API

```rust
pub struct Notifier {
    db: Database,
    email_factory: EmailFactory,
}

impl Notifier {
    pub fn notify_assigned(&self, task: &Task);
    pub fn notify_review_needed(&self, task: &Task);
    pub fn notify_approved(&self, task: &Task);
    pub fn notify_rejected(&self, task: &Task, reason: &str);
    pub fn notify_blocked(&self, task: &Task, blocker: &str);
    pub fn notify_unblocked(&self, task: &Task, unblocker: &str);
    pub fn notify_cancelled(&self, task: &Task);
    pub fn notify_output(&self, task: &Task, project: &Project);
    pub fn notify_comment(&self, task: &Task, commenter: &str);
    pub fn notify_arbitrate(&self, task: &Task, requester: &str, admin: &str);
    pub fn notify_all(&self, board_id: &str, message: &str);
}
```

### 各类通知详情

#### C1: 任务分配通知

```
触发时机：create 或 reassign 后，task 进入 ready/running 状态

From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: [A2A] assigned T1: 成本分析
Body:
  task_id: t_a1b2
  项目: postgres-migration
  标题: 成本分析
  描述: 对比 AWS Aurora / GCP Cloud SQL 在 5TB 下的 3 年 TCO
  审阅者: (无)
  创建人: orchestrator@hermes.a2a
  创建时间: 2026-07-01 09:00:00 UTC
```

#### C2: 待审阅通知

```
触发时机：complete 后 task 进入 reviewing 状态（有 reviewer）

From: board@postgres-mig.a2a
To: architect@sys-a
Subject: [A2A] review-needed T1: 成本分析
Body:
  task_id: t_a1b2
  完成人: researcher-a@sys-a
  标题: 成本分析
  summary: AWS Aurora 3年成本 $120k，GCP $135k
  请审阅后执行 [A2A] approve T1 或 [A2A] reject T1。
```

#### C3: 审阅通过

```
触发时机：approve 后 task 进入 done 状态

From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: [A2A] approved T1: 成本分析
Body:
  task_id: t_a1b2
  审阅人: architect@sys-a
  状态: 已完成
  你的任务 T1 已通过审阅。
```

#### C4: 审阅退回

```
触发时机：reject 后 task 退回 running 状态

From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: [A2A] rejected T1: 成本分析
Body:
  task_id: t_a1b2
  审阅人: architect@sys-a
  原因: GCP 的预留实例折扣未计算，请补充后再提交
  状态: 已退回，请修订后重新 [A2A] complete T1
```

#### C5: 阻挡通知

```
触发时机：block 后 task 进入 blocked 状态

From: board@postgres-mig.a2a
To: orchestrator@hermes.a2a
Subject: [A2A] blocked T1: 成本分析
Body:
  task_id: t_a1b2
  阻挡人: researcher-a@sys-a
  原因: 等待 AWS 账单数据，供应商未回复
  请 Orchestrator 协调。
```

同时发送给阻挡人一条确认：

```
From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: Re: [A2A] block T1
Body:
  任务 T1 已标记为 blocked。已通知 Orchestrator 处理。
```

#### C6: 解除阻挡通知

```
触发时机：unblock 后 task 回到 running 状态

From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: [A2A] unblocked T1: 成本分析
Body:
  task_id: t_a1b2
  解除人: orchestrator@hermes.a2a
  状态: 已解除阻挡，请继续执行。
```

#### C7: 任务取消通知

```
触发时机：cancel 后 task 进入 cancelled 状态

From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: [A2A] cancelled T1: 成本分析
Body:
  task_id: t_a1b2
  取消人: orchestrator@hermes.a2a
  原因: 项目范围调整，T1 不再需要
```

#### C8: 项目输出通知

```
触发时机：output 后项目完成

From: board@postgres-mig.a2a
To: 全体项目成员
Subject: [A2A] output: Postgres 迁移 决策备忘录
Body:
  output by: verifier@hermes.a2a
  项目: postgres-migration
  最终输出: 决策备忘录
  summary: 推荐迁移至 AWS Aurora，预计年节省 $15k
  
  项目已完成。所有 task 已归档。
```

#### C9: 新评论通知

```
触发时机：comment 后写入 task_events

From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: [A2A] comment T1: 成本分析
Body:
  task_id: t_a1b2
  来自: verifier@hermes.a2a
  评论: T1 的成本模型需要包含网络出站流量费用，请更新。
```

#### C10: 通知全体

```
触发时机：notify_all() 被调用（如项目初始化后）

From: board@postgres-mig.a2a
To: 全体项目成员
Subject: [A2A] project initialized: postgres-migration
Body:
  项目已初始化。
  参与者: researcher-a@sys-a, researcher-b@sys-b, ...
  请各成员准备能力自述。
```

---

## 七、指令回复（A 流的回复）

所有 Rust 闭环指令除触发通知外，都会给发送者一条简短回复：

| 指令 | 回复给发送者 |
|------|------------|
| complete | "任务已完成。状态: reviewing（等待 xxx 审阅）" 或 "已完成，promote children" |
| approve | "审阅通过，task xxx 已完成" |
| reject | "已退回 xxx 返工" |
| block | "任务已标记为 blocked，已通知 Orchestrator" |
| unblock | "已解除阻挡" |
| heartbeat | "heartbeat recorded" |
| comment | "备注已添加" |
| show | task 详情（JSON） |
| list | task 列表（JSON） |
| members | 成员列表（JSON） |
| gateway-info | gateway URL + 版本 + board email |

---

## 八、流动汇总

```
                     A 流（指令）          B 流（对话）          C 流（通知）
                     ──────────           ──────────           ──────────
  发送方             项目成员              项目成员              Board
  接收方             Board                项目成员              项目成员
  Subject 格式       [A2A] <verb>         [A2A]/[Proposal]     [A2A] <事件>
  处理层             Rust/Python           Hermes LLM           Rust
  是否启动 LLM       ❌                   ✅                   ❌
  回复模式           同步回复              LLM 生成             机械通知
  示例               complete/block       能力问询/评议          assigned/review-needed


| Verb | 发送者 | 处理层 | 状态影响 | 说明 |
|------|--------|--------|---------|------|
| complete | Worker / Reviewer | Rust | running→done/reviewing | 完成任务 |
| approve | 审阅者 | Rust | reviewing→done | 放行 |
| reject | 审阅者 | Rust | reviewing→running | 退回 Worker |
| block | 任意成员 | Rust | →blocked | 阻挡 |
| unblock | Orchestrator / Admin | Rust | blocked→running | 解除阻挡 |
| heartbeat | Worker | Rust | 不变 | 更新时间戳 |
| comment | 任意成员 | Rust | 不变 | 添加备注 |
| reassign | Orchestrator | Rust | 不变 | 重新分配 |
| edit | Orchestrator | Rust | 不变 | 修改描述 |
| deadline | Orchestrator | Rust | 不变 | 修改截止时间 |
| show | 任意成员 | Rust | — | 查询 |
| list | 任意成员 | Rust | — | 列表 |
| members | 任意成员 | Rust | — | 查询成员 |
| gateway-info | **无限制（公开）** | Rust | — | 返回 gateway URL。不需要 project 成员身份，任何人都可以查询 |
| output | Verifier | Rust | 完成→通知 | 最终放行 |
| cancel | Orchestrator | Rust | →cancelled | 取消 |
| create | Orchestrator | Rust | 创建 task | 解析 task graph 后批量写入 |
| init | Admin | Rust | 创建项目 | 写入白名单 + 发欢迎通知 |
| arbitrate | O / V | Rust | 不变 | 校验角色 + 转发 Admin |

---

## 五、统一拦截器框架

```rust
#[async_trait]
pub trait InboundInterceptor: Send + Sync {
    fn name(&self) -> &str;
    fn priority(&self) -> u32;           // 10=管理员, 20=A2A
    async fn intercept(&self, record: &EmailRecord, payload: &Value)
        -> InterceptorDecision;
}

pub enum InterceptorDecision {
    Handled,      // 已处理，跳过 webhook
    PassThrough,  // 未处理，继续下一个
}
```

注册：

```rust
fn build_interceptors(db: Database, smtp: SmtpSender) -> Vec<Arc<dyn InboundInterceptor>> {
    let mut list: Vec<Arc<dyn InboundInterceptor>> = vec![
        Arc::new(ManagerInterceptor::new(db.clone())),     // 10
    ];
    #[cfg(feature = "a2a")]
    list.push(Arc::new(A2aInterceptor::new(...)));          // 20
    list
}
```

执行顺序：

```
SMTP → Rust 解析 → build payload
  → 10: ManagerInterceptor    管理员指令，匹配则 Handled
  → 20: A2aInterceptor        [A2A] 指令，闭环或 PassThrough
  → bridge → Python webhook → preprocessor → agent session
```

---

## 六、角色与权限

### 角色定义

角色通过 `roles` 表定义，自由字符串，不硬编码。

### 默认权限

| 角色 | 可做 |
|------|------|
| orchestrator | create（项目任意）、block、unblock、arbitrate |
| verifier | output（项目任意） |
| worker | complete（自己任务）、block（自己任务）、heartbeat（自己任务） |
| human | unblock |
| *(任意) | show、list、members、gateway-info、comment |

### 审阅者授权（不通过角色）

`approve` / `reject` 只查 `task.reviewer == sender`，不查 role_permissions。因为审阅者是按 task 指定的，不是按角色。

---

## 七、Hermes 侧组件

### Webhook 处理链

```
Rust gateway HTTP POST → webhook.py _handle_webhook()
  ├── 验证、限流
  ├── ★ Preprocessor
  │   route_config["preprocess"] → PREPROCESS_REGISTRY[name](payload)
  │   └── a2a_board.py 在此运行：检测 A2A 邮件，执行对应逻辑
  ├── 渲染 prompt（从 route 模板 + payload 字段）
  ├── 构建 chat_id
  │   if _a2a_session_key in payload:
  │       chat_id = f"webhook:{route}:a2a:{session_key}"
  │   else:
  │       chat_id = f"webhook:{route}:{delivery_id}"
  ├── 创建 MessageEvent(text=prompt)
  └── → agent session
```

### a2a_board.py preprocessor

preprocessor 只处理 B 流（成员间对话邮件）——注入角色 prompt 和 session key。
所有 A 流指令已由 Rust A2aInterceptor 闭环处理。

```python
def a2a_board_preprocessor(payload, headers):
    subject = payload.get("subject", "").strip()
    sender = payload.get("from", "")

    # 1. 能力问询（填充实时数据到 whoami.md，放行给 LLM 格式化回复）
    if "[A2A] capability-inquiry" in subject.upper():
        profile = resolve_profile(payload.get("to", ""))
        if profile:
            soul = read_soul_md(profile)
            skills = read_skills(profile)
            payload["_capability_body"] = fill_whoami_template(soul, skills, payload)
            payload["_inquire_sender"] = sender
            payload["_a2a_session_key"] = extract_session_key(payload)
        # 不放 LLM 将无法格式化，所以 _skip_delivery = False，放行给 agent session
        # LLM 将看到填充后的 whoami.md 并执行 send_mail() 回复
        return payload

    # 2. B 流邮件（[Proposal] 评议、日常对话等）：注入角色 prompt + session key
    if subject.upper().startswith("[A2A]") or subject.upper().startswith("[PROPOSAL]")        or subject.upper().startswith("RE: [A2A]") or subject.upper().startswith("RE: [PROPOSAL]"):
        board_id = extract_board_id(subject, payload.get("body", ""))
        if board_id:
            payload["_a2a_session_key"] = f"a2a:{board_id}:{sender}"
            payload["_role_prompt"] = read_role_prompt(detect_role(sender, board_id))

    return payload
```

### 角色行为 Prompt

角色行为不写入 SKILL.md。由 preprocessor 以纯文本注入到 agent session 的 user message 中。

```python
# webhook handler prompt 拼接
role_prompt = payload.get("_role_prompt", "")
if role_prompt:
    prompt = f"{prompt}\n\n---\n{role_prompt}"
```

`agentmail/a2a_roles/` 目录包含纯文本片段：

```
├── orchestrator.md    目标分解、能力发现、编排、巡视、仲裁
├── verifier.md        验收标准审阅、中间产物合规检查、output
└── worker.md          执行、heartbeat、complete、block
```

### whoami.md 能力自述

`agentmail/skill/whoami.md` 是 prompt 模板，含 4 个占位符：

```
{{AGENTMAIL_ADDRESS}}   → agent email
{{SOUL_MD_CONTENT}}     → SOUL.md 全文
{{SKILLS_LIST}}         → 已加载 SKILL 列表
{{INQUIRY_SENDER}}      → 问询者 email
```

能力自述不走 LLM。预处理器直接读文件 → 填充模板 → `send_mail()` 回复。非 Hermes 系统降级到 LLM 自解析兜底。

### a2a toolset

```yaml
toolset: a2a
tools:
  - a2a_show(task_id)              # GET /api/v1/a2a/{project}/task/:id
  - a2a_list(project, status, assignee)  # GET /api/v1/a2a/{project}/tasks
  - a2a_members(project)            # GET /api/v1/a2a/{project}/members
  - a2a_heartbeat(task_id, note)    # POST /api/v1/a2a/{project}/command
```

写操作保留邮件方式（Rust 闭环，延迟低，需 email 审计）。

### Session 复用

```python
# Preprocessor 设置
payload["_a2a_session_key"] = f"a2a:{board_id}:{sender_email}"

# Webhook handler 使用
a2a_key = payload.get("_a2a_session_key")
if a2a_key:
    session_chat_id = f"webhook:{route_name}:{a2a_key}"
else:
    session_chat_id = f"webhook:{route_name}:{delivery_id}"
```

| 邮件类型 | session key | 是否复用 |
|---------|-------------|---------|
| 非 A2A 邮件 | `webhook:route:<delivery_id>` | ❌ |
| [A2A] / [Proposal] 邮件 | `webhook:route:a2a:proj:user@d` | ✅ |

---

## 八、通知机制

**Rust 侧**（简单命令闭环）：

```
commands::handle_complete()
  → notify::status_changed(task)
    → EmailFactory::send_outbound(email)
      → INSERT INTO email_records → SMTP relay
```

**Python 侧**（复杂命令）：

```
a2a_board preprocessor
  → send_mail(to=worker, subject=...)
    → HTTP POST /api/v1/send → Rust send handler
      → EmailFactory → INSERT INTO email_records → SMTP relay
```

两条路径汇合在 EmailFactory。

---

## 九、自动归档

`board/archiver.rs` 定时器，每天扫描所有 board.db：

```rust
fn archive_expired_projects(db_pool) {
    for db in db_pool.iter() {
        let old = db.query("SELECT * FROM boards WHERE status='active'
                             AND completed_at < datetime('now', '-7 days')");
        for p in old {
            db.execute("UPDATE boards SET status='archived' WHERE id=?", p.id);
        }
    }
}
```

归档后 `POST /api/v1/a2a/{project}/command` 返回 `403 project archived`。不支持恢复。

---


---


## 十一、邮件 Subject 规范

所有 A/B/C 流的邮件 Subject 遵循统一的格式规范，确保 Rust 拦截器和 preprocessor 能准确识别。

### 规范总则

```
[A流/B流标识] [项目简称] [动作/主题] — [可选补充说明]
```

- **A 流**：`[A2A] <verb> [<task-id>]` - 发给 Board 的指令
- **B 流**：`[标识] <项目简称> <主题> v<N>` - 成员间对话
- **C 流**：`[A2A] <event> <task-id>: <简述>` - Board 发出的通知
- **回复**：统一加 `Re:` 前缀，Board 自动通过 In-Reply-To / References 头追踪线程

### A 流：成员 → Board 指令

| 发起 Subject | 回复 Subject | 说明 |
|-------------|-------------|------|

所有 A/B/C 流邮件在发送时必须在邮件头中包含 **`Board-ID: <board_id>`**。Rust 拦截器和 preprocessor 通过此 header 直接定位 board.db，无需解析 Subject 或 body。

| 发起 Subject | 回复 Subject | 说明 |
|-------------|-------------|------|
| `[A2A] complete T1` | `Re: [A2A] complete T1` | 完成任务 |
| `[A2A] approve T1` | `Re: [A2A] approve T1` | 审阅通过 |
| `[A2A] reject T1` | `Re: [A2A] reject T1` | 审阅退回 |
| `[A2A] block T1` | `Re: [A2A] block T1` | 阻挡 |
| `[A2A] unblock T1` | `Re: [A2A] unblock T1` | 解除阻挡 |
| `[A2A] heartbeat T1` | `Re: [A2A] heartbeat T1` | 心跳 |
| `[A2A] comment T1` | `Re: [A2A] comment T1` | 备注 |
| `[A2A] reassign T1` | `Re: [A2A] reassign T1` | 重新分配 |
| `[A2A] edit T1` | `Re: [A2A] edit T1` | 修改描述 |
| `[A2A] deadline T1` | `Re: [A2A] deadline T1` | 截止时间 |
| `[A2A] show T1` | `Re: [A2A] show T1` | 查询（有 toolset 时优先用 tool） |
| `[A2A] list` | `Re: [A2A] list` | 列表（有 toolset 时优先用 tool） |
| `[A2A] members` | `Re: [A2A] members` | 成员列表（有 toolset 时优先用 tool） |
| `[A2A] gateway-info` | `Re: [A2A] gateway-info` | gateway 信息 |
| `[A2A] output T1` | `Re: [A2A] output T1` | 最终放行 |
| `[A2A] cancel T1` | `Re: [A2A] cancel T1` | 取消 |
| `[A2A] create` | `Re: [A2A] create` | 创建 task |
| `[A2A] init` | `Re: [A2A] init` | 初始化项目（仅 Admin） |
| `[A2A] arbitrate` | `Re: [A2A] arbitrate` | 提请仲裁 |

Board 回复时保持 Subject 不变（加 Re: 前缀）。例如成员发 `[A2A] complete T1`，Board 回复 `Re: [A2A] complete T1`。

### B 流：成员 ↔ 成员对话

| 类型 | 发起 Subject | 回复 Subject | 说明 |
|------|-------------|-------------|------|
| B1: 能力问询 | `[A2A] capability-inquiry` | `Re: [A2A] capability-inquiry` | 不含项目/版本号 |
| B2: 编排方案 | `[Proposal] <项目> 方案 v<N>` | `Re: [Proposal] <项目> 方案 v<N>` | v1, v2, v3... |
| B3: 验收标准 | `[Criteria] <项目> 验收标准 v<N>` | `Re: [Criteria] <项目> 验收标准 v<N>` | v1, v2, v3... |
| B4: 阶段汇报 | `[Report] <项目> Phase <N>: <标题>` | `Re: [Report] <项目> Phase <N>: <标题>` | N=1,2,3... |
| B5: 互评 | `[Review] <项目> <评价对象> <任务>` | `Re: [Review] <项目> <评价对象> <任务>` | 可选 |
| B6: 任务讨论 | `[Discuss] <Task-ID> <主题>` | `Re: [Discuss] <Task-ID> <主题>` | 讨论标识 |
| B7: Admin 确认 | `[Confirm] <项目> <类型> v<N>` | `Re: [Confirm] <项目> <类型> v<N>` | 确认请求标识，由 O/V 发给 Admin |

B 流邮件 **必须 Cc: board@project.a2a** 以便 Board 记录事件日志。

### C 流：Board → 成员通知

| 类型 | Subject | 发送给 | 说明 |
|------|---------|--------|------|
| C1: 任务分配 | `[A2A] assigned T1: <标题>` | assignee | create/reassign 触发 |
| C2: 待审阅 | `[A2A] review-needed T1: <标题>` | reviewer | complete 触发 |
| C3: 审阅通过 | `[A2A] approved T1: <标题>` | assignee | approve 触发 |
| C4: 审阅退回 | `[A2A] rejected T1: <标题>` | assignee | reject 触发 |
| C5: 阻挡 | `[A2A] blocked T1: <标题>` | Orchestrator | block 触发 |
| C6: 解除阻挡 | `[A2A] unblocked T1: <标题>` | assignee | unblock 触发 |
| C7: 取消 | `[A2A] cancelled T1: <标题>` | assignee | cancel 触发 |
| C8: 项目输出 | `[A2A] output: <项目> <标题>` | 全体 | output 触发 |
| C9: 评论 | `[A2A] comment T1: <简述>` | assignee | comment 触发 |
| C10: 全员通知 | `[A2A] notice: <项目> <内容>` | 全体 | notify_all 触发 |

C 流通知纯机械发送，无需回复（但接收方可参考规则决定是否采取行动）。

### Subject 解析规则（Rust A2aInterceptor）

```rust
fn parse_a2a_subject(subject: &str) -> Option<ParsedCommand> {
    let subject = subject.trim();

    // A 流指令: [A2A] <verb> [<task-id>]
    if let Some(rest) = subject.strip_prefix("[A2A] ") {
        let parts: Vec<&str> = rest.splitn(2, ' ').collect();
        let verb = parts[0];
        let arg = parts.get(1).map(|s| s.to_string());
        // 检查是否 Re: 前缀（需要去除后才解析）
        // ...
        return Some(ParsedCommand { verb, task_id: arg, flow: Flow::A });
    }

    // B 流: [Proposal] / [Criteria] / [Report] / [Review]
    for prefix in ["[Proposal]", "[Criteria]", "[Report]", "[Review]"] {
        if subject.starts_with(prefix) {
            return Some(ParsedCommand { flow: Flow::B, ... });
        }
    }

    // C 流通知不发到 Board，所以不需要 Board 侧解析

    None
}
```

---

## 十一、角色技能矩阵

以角色为维度，列出每个角色需要发起的动作、需要应对的消息、以及指导 LLM 的关键规则。此矩阵直接指导 `agentmail/a2a_roles/` 目录下角色 prompt 文件的撰写。

### Orchestrator 技能点

```
                         Orchestrator 角色 prompt

  A 流发起（-> Board）：
    [A2A] create          按共识后的方案创建 task 树
    [A2A] block/unblock   阻挡/解除阻挡
    [A2A] cancel          取消不再需要的 task
    [A2A] reassign        重新分配 task
    [A2A] edit            修改 task 描述
    [A2A] deadline        修改截止时间
    [A2A] comment         添加备注
    [A2A] arbitrate       提请管理员仲裁
    [A2A] show/list/members 查询（或用 toolset 直接查询）

  B 流发起（-> 成员）：
    [A2A] capability-inquiry   能力问询（编排前置）
    [Proposal] 编排方案 v<N>    评议 + 修订 + 共识
    [Report] 阶段汇报           阶段完成后总结
    [Review] 互评               optional
    任务讨论                   task 执行过程中
    @admin 确认                方案/验收标准共识后

  B 流应对（<- 成员）：
    接收 [Proposal] 评议反馈 -> 修订方案
    接收 [Criteria] 草案 -> 评议验收标准
    接收 [Report] 阶段汇报 -> 确认或调整
    接收 Admin 确认 -> 执行 [A2A] create
    参与任务讨论 -> 提供决策意见

  C 流应对（<- Board 通知）：
    blocked 通知 -> 介入协调（联系相关方或 unblock）
    review-needed -> 知悉（非主要职责，但需要跟踪进度）
    output 通知 -> 项目完成，存档
    approved/rejected -> 跟踪整体进度

  规则：
    - 不自己执行 task（create 后交给 assignee）
    - 不跳过评议直接 create
    - 仅在协调无果时使用 arbitrate
    - 巡视是顺带行为（处理其他邮件时顺带查状态）
    - 有 toolset 的操作优先用 tool，不用发邮件（show/list/members/heartbeat 走 tool）
```

### Verifier 技能点

```
                         Verifier 角色 prompt

  A 流发起（-> Board）：
    [A2A] approve/reject   审阅被指派的 task
    [A2A] output           最终放行（需对照验收标准检验）
    [A2A] block            遇到阻挡
    [A2A] comment          添加评审意见
    [A2A] arbitrate        提请管理员仲裁
    [A2A] show/list/members 查询（或用 toolset）

  B 流发起（-> 成员）：
    [Criteria] 验收标准 v<N>   编排方案确认后发起
    [Review] 互评             optional
    任务讨论                 需要澄清时

  B 流应对（<- 成员）：
    接收 [Criteria] 评议 -> 修订验收标准
    接收 [Proposal] 编排方案 -> 评议
    接收 [Report] 阶段汇报 -> 确认交付物质量
    Admin 确认验收标准 -> 写入 criteria_confirmed_at
    参与任务讨论 -> 提供质量建议

  C 流应对（<- Board 通知）：
    review-needed 通知 -> 审阅！这是核心职责
       对照 task body + 验收标准 -> approve 或 reject
    blocked 通知 -> 知悉（但只有 O 可 unblock）
    approved/rejected -> 知悉
    output 通知 -> 自己已做，项目完成
    unblocked/cancelled -> 知悉

  规则：
    - 仅审阅被指派的 task（reviewer 字段包含你的 email）
    - 审阅不是主观判断，对照 task body 中的描述
    - output 前需检查：所有 task done、流转合规、通过标准
    - 争议时先 comment 沟通，沟通无效再 arbitrate
    - 验收标准共识前不执行 output
    - 有 toolset 的操作优先用 tool（show/list/members 走 tool）
```

### Worker 技能点

```
                         Worker 角色 prompt

  A 流发起（-> Board）：
    [A2A] complete       完成任务，带 summary
    [A2A] heartbeat      长任务中定期更新进度
    [A2A] block          遇到不可抗力时阻挡
    [A2A] comment        添加备注
    [A2A] show/list/members 查询（或用 toolset）

  A 流不可以做的事：
    - approve/reject      你不是审阅者
    - output              只有 Verifier 可以
    - create              只有 Orchestrator 可以
    - cancel/reassign     只有 Orchestrator 可以
    - arbitrate           只有 O/V 可以

  B 流发起（-> 成员）：
    [Review] 互评         optional
    任务讨论              task 执行过程中的讨论

  B 流应对（<- 成员）：
    接收 [A2A] capability-inquiry -> 回复能力自述
    接收 [Proposal] 编排方案 -> 评议（重点看 assignee 合理性）
    接收 [Criteria] 验收标准 -> 确认可执行性
    接收 [Report] 阶段汇报 -> 知悉（不用回复）
    参与任务讨论 -> 提供技术意见

  C 流应对（<- Board 通知）：
    assigned 通知 -> 查看任务详情，开始执行
    approved 通知 -> 继续下一个 task
    rejected 通知 -> 查看原因，修订后重新 complete
    unblocked 通知 -> 继续执行
    cancelled 通知 -> 停止，等待新分配
    comment 通知 -> 查看反馈
    output 通知 -> 项目完成

  规则：
    - 遇到不可抗力先 block，不要自己硬扛
    - complete 时带 summary（一句话完成内容）
    - 长任务（>5分钟）定期用 a2a_heartbeat() tool 发心跳，不要发邮件
    - 能力自述诚实填写，不要接受不擅长的任务
    - 任务不清晰时先讨论再执行，不要猜
    - 有 toolset 的操作优先用 tool（show/list/members/heartbeat 走 tool）
```

### Toolset 辅助标注

高频查询操作建议做成 toolset，减少 SMTP 邮件往返延迟。

| 操作 | 用途 | 建议 tool | 频繁使用者 |
|------|------|-----------|-----------|
| 查任务详情 | 查看 task body、状态、审阅者 | `a2a_show(task_id)` | O / V / W |
| 查任务列表 | 按 status/assignee 过滤 | `a2a_list(project, status?, assignee?)` | O（巡视）|
| 查项目成员 | 获取成员列表和角色 | `a2a_members(project)` | O（编排前）/ V |
| 发心跳 | 更新长任务时间戳 | `a2a_heartbeat(task_id, note)` | W（频繁）|

不推荐做成 toolset 的操作：

| 操作 | 理由 |
|------|------|
| complete / approve / reject / block | 需要 email 审计痕迹，Rust 闭环已足够快 |
| create / init | 共识后仅调用一次，不值得 toolset |
| output | 项目完成一次的低频操作 |
| arbitrate | 异常流程，低频 |

tool 实现示例：

```python
# tools/a2a_tools.py
def a2a_show(task_id: str) -> str:
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    board_id = resolve_project_from_task(task_id)
    result = client._request("GET", f"/api/v1/a2a/{board_id}/task/{task_id}")
    return json.dumps(result, indent=2)

def a2a_list(project: str, status: str = "", assignee: str = "") -> str:
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    query = {}
    if status: query["status"] = status
    if assignee: query["assignee"] = assignee
    result = client._request("GET", f"/api/v1/a2a/{project}/tasks", params=query)
    return json.dumps(result, indent=2)

def a2a_members(project: str) -> str:
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    result = client._request("GET", f"/api/v1/a2a/{project}/members")
    return json.dumps(result, indent=2)

def a2a_heartbeat(task_id: str, note: str = "") -> str:
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    board_id = resolve_project_from_task(task_id)
    result = client._request("POST", f"/api/v1/a2a/{board_id}/command", {
        "verb": "heartbeat", "task_id": task_id, "params": {"note": note}
    })
    return json.dumps(result, indent=2)
```

tool 注册遵循 `agentmail_tools.py` 中的 `registry.register()` 模式。

---

## 十、实现阶段

| Phase | 组件 | 内容 | 前置 |
|-------|------|------|------|
| P0 | `board/models.rs` + `board/db.rs` | board.db 表结构 + CRUD | 现有 amail-gateway |
| P0 | `board/commands.rs` | 所有 verb 业务逻辑 + authorize() + verify_output() | P0 db |
| P0 | `board/handlers.rs` | command/task/tasks/members/gateway-info/init | P0 commands |
| P0 | `board/router.rs` | RouterHook 挂路由 | P0 handlers |
| P0 | `board/interceptor.rs` | Board 角色：处理 [A2A] 指令 | P0 commands |
| P0 | `board/notify.rs` | EmailFactory 通知 | 现有 core |
| P0 | `board/archiver.rs` | 归档定时器 | P0 db |
| P0 | `a2a_board.py` | Python preprocessor（capability-inquiry + B 流 session key 注入） | P0 Rust API |
| P1 | core 修改 | strategy.rs 加 InboundInterceptor + webhook.rs 链 | — |
| P1 | `tools/a2a_tools.py` | a2a toolset 的 4 个 tool | P0 Rust API |
| P1 | 角色行为片段 × 3 | `agentmail/a2a_roles/` 纯文本 prompt | — |
| P1 | whoami.md | 能力自述 prompt 模板 | — |
| P1 | webhook patch | chat_id 构建逻辑检测 _a2a_session_key | — |
| P2 | 通知可靠性 | 重试、去重 | P0 notify |
