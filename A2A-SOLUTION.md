# A2A项目看板系统 — 设计文档

> 基于 agentmail 的开放跨系统 A2A 项目协作看板（a2a_board）

---

## 第一层：业务模型（宏观）

### 一、业务模型与需求规约

#### 解决的问题

多个 agent 分布在不同的 Hermes 实例或非 Hermes 系统上，需要协作完成一个项目。每个 agent 有 agentmail 地址作为身份标识，通过邮件通信。需要一套**看板（board）**来组织、分配、追踪和验收工作——看板是协作能落实下来的具体产物和表现。

#### 核心约束

1. **纯邮件通信** — 所有交互基于 agentmail，人类管理员使用普通邮件客户端
2. **Board 是忠实的记录者** — Board 有专属 agentmail 地址（如 `board@project.a2a`），它是看板数据的宿主。Board 不是 agent，不需要 LLM，直接在 amail-gateway 上通过 Rust 层处理邮件指令并回复。所有项目状态记录和查询反馈由 Board 的 agentmail 地址完成
3. **Orchestrator 负责驱动力** — 分解→提议→评议→共识→执行→巡视→回收
4. **Verifier 闸门** — 最终输出的唯一放行口，需按验收标准审查，同时检查中间产物是否按编排方案流转
5. **仅 Orchestrator 和 Verifier 可提请管理员仲裁**
6. **能力自述而非外部指定** — 每个 agent 基于自身上下文（SOUL.md + 已加载 SKILL）定义自己的角色和能力
7. **编排是团队共识而非一人决策** — 通过评议达成集体共识
8. **amail-gateway 非中心化** — 不同 agent 可能隶属不同的 amail-gateway 系统。但 Board 的 agentmail 地址固定，锁定 board 数据存储所在的 amail-gateway

#### Board 角色详解

Board 是项目看板的核心实体，拥有专属 agentmail 地址（如 `board@postgres-mig.a2a`）。

**Board 是什么：**
- 有专属 agentmail 地址，可接收和回复邮件
- 不是 Hermes agent，不需要 agent session 和 LLM
- 宿主在特定的 amail-gateway 上（该 gateway 的存储路径下保存 board.db）

**Board 能做什么（通过 Rust 拦截器直接处理）：**

| 操作 | 邮件命令 | 处理方式 |
|------|---------|---------|
| 记录任务状态变化 | `[A2A] complete/block/heartbeat` | Rust 拦截器闭环，写 board.db |
| 查询任务详情 | `[A2A] show T1` | Rust 拦截器闭环，读 board.db 回复 |
| 查询项目成员 | `[A2A] members` | Rust 拦截器闭环，读 board.db 回复 |
| 查询 gateway URL | `[A2A] gateway-info` | Rust 拦截器闭环，返回本 gateway 的 URL |
| 通知相关方 | 自动 | Rust notify → EmailFactory → SMTP |

**Board 的 agentmail 地址用于锁定数据存储所在的 amail-gateway：** 所有参与者向 `board@project.a2a` 发送指令邮件，SMTP 路由保证邮件到达该网关。其他参与者通过 `[A2A] gateway-info` 获取该 gateway 的 HTTP URL，此后可直接通过 REST API 查询 board 数据。

#### 参与方与角色

```
Project Team
├── Human Admin        (普通邮箱)
│   └── 确认编排方案、仲裁争议
├── Orchestrator       (agentmail 地址)
│   └── 能力发现→编排提议→巡视→回收→可提请仲裁
├── Verifier(s)        (agentmail 地址，可多人，各有专长领域)
│   └── 按验收标准审阅交付物→检查中间产物流转合规→
│       可提请仲裁→最终输出放行
├── Worker(s)          (agentmail 地址，可多人)
│   └── 能力自述→执行任务→完成/阻挡
├── Board              (agentmail 地址，宿主于特定 amail-gateway)
│   └── 记录状态→查询反馈→状态通知→gateway 信息提供
│       不需要 LLM，Rust 直接处理
└── Other Participants (agentmail 地址)
    └── 评议编排方案
```

#### 通信模型

所有通信通过 agentmail 邮件完成，不新增通道、不新增编码协议、不新增 CLI。

| 邮件类型 | Subject 格式 | 说明 |
|---------|-------------|------|
| 指令 | `[A2A] <verb> [<task-id>]` | 结构化命令，发给 Board，Rust 拦截器处理 |
| 通知 | `[A2A] <event> <task-id>: <简述>` | Board 发出的状态变化通知 |
| 能力问询 | `[A2A] capability-inquiry` | Orchestrator 向成员发出的能力自述请求 |
| 编排提议 | `[Proposal] <项目名> 方案 v<N>` | Orchestrator 发给全体参与者的评议邮件 |
| 仲裁请求 | `[A2A] arbitrate` | Board 转发给 Human Admin 的裁决请求 |
| 仲裁回复 | `Re: [A2A] arbitrate: ...` | Human Admin 的回复，Rust 检测并处理 |
| Gateway 查询 | `[A2A] gateway-info` | 查询 Board 所在 gateway 的 HTTP URL |
| 日常对话 | 无特殊前缀 | 普通 agentmail 对话 |

#### 邮件流向分类

根据发送者和接收者的不同，项目中的邮件分为三类：

```
A: 成员 → Board（指令邮件）
   Worker → Board: [A2A] complete/block/heartbeat
   Verifier → Board: [A2A] approve/reject/output
   Orchestrator → Board: [A2A] create/cancel/reassign
   Admin → Board: [A2A] init/add-member
   任意成员 → Board: [A2A] show/list/members/gateway-info/comment
   → Rust A2aInterceptor 或 Python preprocessor 处理
   → Board 直接回复结果

B: 成员 ↔ 成员（对话邮件）
   Orchestrator → 每个成员: [A2A] capability-inquiry（能力问询）
   Orchestrator → 全体: [Proposal] 编排方案 v1（评议邀请）
   参与者回复评议: "同意。但 T1 的 assignee 建议改为..."
   Orchestrator → 全体: [Proposal] 编排方案 v2（修订版）
   Orchestrator → Admin: @admin 请确认（审批请求）
   Worker ↔ Worker: 日常技术讨论（普通邮件）
   → 经过 agent session，LLM 处理
   → Cc: Board 用于存档，但 Board 不处理

C: Board → 成员（通知邮件）
   Board → assignee: [A2A] assigned T1: 成本分析（任务分配通知）
   Board → reviewer: [A2A] review-needed T1（待审阅通知）
   Board → Worker: [A2A] unblocked T1（解除阻挡通知）
   Board → 全员: [A2A] output T4: xxx（项目输出通知）
   Board → sender: Re: [A2A] complete T1（指令回复）
   → 由 Rust notify 模块自动发送（EmailFactory → SMTP relay）
   → 无 LLM 参与，纯机械通知
```

**Board 只接收 A 类邮件（指令）。Board 发送 C 类邮件（通知/回复）。B 类邮件在成员之间直接往来，Board 只是在 Cc 中抄送以保存记录。**

#### 完整编排流程

```
Phase 0: 项目初始化
  Admin → Board: [A2A] init（成员列表）
  Board: 写入 board.db + Rust notify 通知全体

Phase 1: 能力发现
  Orchestrator → 每个成员: [A2A] capability-inquiry
  每个成员回复能力自述
  Orchestrator 汇总为能力矩阵

Phase 2: 编排共识
  Orchestrator 撰写方案 v1（每个 task 附 assignee 理由 + reviewer）
  → [Proposal] 发给全体参与者
  → 参与者评议
  → Orchestrator 修订 → 重复直到无异议
  → @admin 确认

Phase 3: 执行
  Orchestrator → Board: [A2A] create
  Board: 写入 board.db，回复确认 + 通知 assignees

Phase 4: 协作流转
  Worker → Board: [A2A] complete → Rust 写 board.db + 回复 + 通知
  Verifier → Board: [A2A] approve/reject → Rust 更新状态
  Orchestrator 巡视（通过 a2a toolset 或 [A2A] list）

Phase 5: 完成
  Verifier → Board: [A2A] output
  Board: Rust 校验中间产物合规 + 写 board.db + 通知全员
  7 天后自动归档
```

---

## 第二层：架构设计（中观）

### 二、总体架构

#### 系统架构图

```
                          ┌──────────────────────────────────────────────────────────────┐
                          │           Rust amail-gateway（Board 宿主 + 数据持久层）      │
                          │                                                              │
                          │  [storage].path/a2a_board/{project_id}/board.db              │
                          │                                                              │
                          │  ┌──────────────────────────────────────────────────────┐    │
                          │  │              axum HTTP Server (:8080)               │    │
                          │  │  POST /api/v1/a2a/{project}/command                │    │
                          │  │  GET  /api/v1/a2a/{project}/task/:id               │    │
                          │  │  GET  /api/v1/a2a/{project}/gateway-info           │    │
                          │  │  PUT  /api/v1/a2a/{project}/init                   │    │
                          │  └──────────────────────────────────────────────────────┘    │
                          │                                                              │
                          │  ┌──────────┐  ┌────────────────────────────────────┐      │
                          │  │  core/  │  │  board/ (feature-gated)            │      │
                          │  │         │  │  ┌────────────────────────────┐    │      │
                          │  │         │  │  │ interceptor.rs (pri=20)    │    │      │
                          │  │         │  │  │ 处理 [A2A] 指令           │    │      │
                          │  │         │  │  │ 包含 Board 角色行为        │    │      │
                          │  │         │  │  │ commands.rs                │    │      │
                          │  │         │  │  │ handlers.rs · db.rs        │    │      │
                          │  │         │  │  │ notify.rs · models.rs      │    │      │
                          │  │         │  │  │ archiver.rs                │    │      │
                          │  │         │  │  └────────────────────────────┘    │      │
                          │  └──────────┘  └────────────────────────────────────┘      │
                          │                                                              │
                          │  拦截器链（priority 排序）:                                  │
                          │    10: ManagerInterceptor     管理员指令                     │
                          │    20: A2aInterceptor         处理 [A2A] 指令（Board 角色）  │
                          └──────────────────────────────────────────────────────────────┘
                            SMTP ↕ Board@project.a2a         HTTP API ↕ 跨系统访问
                                     │                                 │
                          ┌──────────┴─────────────────────────────────┴──────────┐
                          │    多个 amail-gateway 系统（非中心化）               │
                          │    每个系统可以下挂不同类型的 agent 系统              │
                          │                                                        │
                          │  amail-gateway A                    amail-gateway B    │
                          │  ├─ Hermes agent 1                 ├─ Hermes agent 3   │
                          │  ├─ 自定义 agent 2                 └─ LLM API agent 4  │
                          │  └─ ...                                                 │
                          │                                                        │
                          │  但 Board 的 agentmail 地址固定（如 board@p.a2a）     │
                          │  → 通过 SMTP 路由锁定数据存储所在的 gateway            │
                          │  → 通过 [A2A] gateway-info 获知该 gateway 的 HTTP URL │
                          │  → 之后可直接通过 REST API 高速访问 board 数据         │
                          └────────────────────────────────────────────────────────┘
```

#### 各层职责

| 层 | 实现 | 职责 | 关键原则 |
|---|------|------|---------|
| Board 数据层 | Rust amail-gateway `board/` 模块 | 状态机执行、数据读写、通知发送、HTTP API、邮件指令回复 | Board 有专属 agentmail 地址，不需要 LLM |
| 逻辑处理层 | Python preprocessor + agent session | 复杂命令处理、LLM 推理 | Python 是 API 客户端 |
| 通信层 | email / SMTP | 所有交互通过邮件 | 不新增通道 |

#### 角色行为说明

角色行为不是独立 SKILL，不写入 SKILL.md 文件。Orchestrator/Verifier/Worker 的行为指导由 preprocessor 在检测到 A2A 邮件时，**以纯文本形式动态注入到 agent session 的 user message 中**。agentmail SKILL 保持不变。

---

## 第三层：组件设计（微观）

### 三、amail-gateway 数据持久层（Rust board 模块）

#### 数据模型 — board.db

路径：由 amail-gateway 配置 `[storage].path` 自动衍生。

```
[storage].path/a2a_board/{project_id}/board.db

例如：storage.path = /var/lib/amail-gateway
  → /var/lib/amail-gateway/a2a_board/postgres-migration/board.db
```

```
projects
├── id TEXT PRIMARY KEY
├── board_email TEXT NOT NULL       # board@postgres-mig.a2a
├── status TEXT (active / archived)
├── created_at TEXT
├── completed_at TEXT
└── gateway_url TEXT               # 本 gateway 的 HTTP URL

project_members
├── email TEXT PRIMARY KEY
├── role TEXT
├── display_name TEXT
├── project_id TEXT
├── joined_at TEXT
├── domains TEXT (JSON array)
└── capability_snapshot TEXT (JSON)

roles
├── name TEXT PRIMARY KEY
└── description TEXT

role_permissions
├── role TEXT REFERENCES roles(name)
├── verb TEXT
└── scope TEXT (own / project)

tasks
├── id TEXT PRIMARY KEY
├── short_id TEXT
├── project_id TEXT
├── title TEXT, body TEXT
├── status TEXT
├── assignee TEXT
├── reviewer TEXT
├── parent_ids TEXT (JSON array)
├── tags TEXT (JSON array)
├── summary TEXT, metadata TEXT (JSON)
├── created_by TEXT
├── created_at TEXT, updated_at TEXT
├── completed_at TEXT, cancelled_at TEXT
└── deadline TEXT

task_events
├── id INTEGER PRIMARY KEY AUTOINCREMENT
├── task_id TEXT, event_type TEXT, actor TEXT
├── payload TEXT (JSON)
└── created_at TEXT
```

#### 网络路由

```
POST /api/v1/a2a/{project_id}/command     body: { verb, task_id?, params }
GET  /api/v1/a2a/{project_id}/task/:id
GET  /api/v1/a2a/{project_id}/tasks       query: ?status=...&assignee=...
GET  /api/v1/a2a/{project_id}/members
GET  /api/v1/a2a/{project_id}/gateway-info     # 返回本 gateway 的 URL
PUT  /api/v1/a2a/{project_id}/init        body: { members, ... }
```

#### Board 的邮件指令处理

所有发给 Board agentmail 地址的 `[A2A]` 邮件由 Rust `A2aInterceptor` 处理，**不需要经过 webhook → preprocessor → agent session 链路**：

```
A2aInterceptor (priority 20):
  检测 Subject 是否以 [A2A] 开头
  → 解析 verb + task_id + params
  → 执行对应命令（读/写 board.db）
  → 构造回复邮件（通过 SMTP 直接回复发送方）
  → 返回 Handled（跳过 webhook 投递）
```

| Verb | Board 处理 | 需要 LLM？ |
|------|-----------|-----------|
| complete / block / unblock / heartbeat | Rust 写 board.db + 回复 + 通知 | ❌ |
| approve / reject | Rust 校验 `sender == task.reviewer` + 更新状态 | ❌ |
| show / list / members | Rust 读 board.db + 回复 | ❌ |
| gateway-info | Rust 返回本 gateway 的 HTTP URL | ❌ |
| output | Rust 校验 Verifier 角色 + 中间产物流转合规 + 通知 | ❌ |
| cancel / reassign / edit / deadline | Rust 写 board.db + 回复 | ❌ |
| comment | Rust 写入 task_events + 通知 | ❌ |
| **create** | **放行到 Python preprocessor**（需验证 task graph） | ✅ |
| **arbitrate** | **放行到 Python preprocessor**（需发邮件给 Admin） | ✅ |
| **init** | **放行到 Python preprocessor**（需建立白名单） | ✅ |

**Board 回复邮件格式示例：**

```
From: board@postgres-mig.a2a
To: researcher-a@sys-a
Subject: Re: [A2A] complete T1
Body:
  status: completed
  task_id: t_a1b2
  new_status: reviewing
  reviewer: architect@sys-a
  通知已发送给 architect@sys-a 等待审阅。
```

#### Board gateway 发现机制

跨系统参与者需要直接通过 HTTP API 查询 board 数据时：

```
1. 发送 [A2A] gateway-info 到 board@project.a2a
2. Board Rust 拦截器回复：
   gateway_url: https://amail-gateway.io:8443
3. 此后可直接调用：
   GET https://amail-gateway.io:8443/api/v1/a2a/project/task/t_a1b2
```

#### 统一拦截器框架

```rust
#[async_trait]
pub trait InboundInterceptor: Send + Sync {
    fn name(&self) -> &str;
    fn priority(&self) -> u32;
    async fn intercept(&self, record: &EmailRecord, payload: &Value)
        -> InterceptorDecision;
}

pub enum InterceptorDecision {
    Handled,      // 已处理，跳过 webhook
    PassThrough,  // 未处理，继续下一个
}
```

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

#### 状态机

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

#### 指令执行路径

所有 A2A 指令邮件发送到 Board 的 agentmail 地址（`board@project-a2a`），由 Rust A2aInterceptor 统一接收。根据指令类型走三条路径之一。

```
[指令邮件到达 board@project.a2a]
  ↓
Rust A2aInterceptor (priority 20)
  ├── 路径 A: Rust 闭环（无需 LLM，立即回复）
  │   ├── complete / approve / reject
  │   ├── block / unblock / heartbeat
  │   ├── comment / cancel / reassign / edit / deadline
  │   ├── show / list / members / gateway-info
  │   └── output
  │
  ├── 路径 B: Python preprocessor（需要复杂逻辑，不自启 LLM session）
  │   ├── create       → 验证 task graph 一致性后调 Rust API
  │   ├── init         → 初始化项目 + 白名单 + contact profiles
  │   └── arbitrate    → 构造仲裁请求邮件发送给 Admin
  │
  └── 路径 C: 放行到 agent session（需要 LLM 推理）
      └──（当前无指令走此路径——所有 LLM 活动发生在日常对话
           和 [Proposal] 评议邮件，不由 A2A 指令触发）
```

#### 路径 A: Rust 闭环（详细执行逻辑）

##### complete

```rust
fn handle_complete(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;

    // 校验发送者
    if task.assignee != sender {
        return Err("only assignee can complete");
    }

    // 状态转换
    task.status = if task.reviewer.is_some() {
        Status::Reviewing
    } else {
        Status::Done
    };

    db.update_task(task);
    db.insert_event(task.id, "completed", sender);

    // 回复 + 通知
    if task.reviewer.is_some() {
        smtp.reply(cmd.from, "任务已提交审阅，等待审阅者 "+task.reviewer);
        smtp.notify(task.reviewer, "待审阅任务: " + task.id);
    } else {
        smtp.reply(cmd.from, "任务已完成，正在 promote children");
        promote_children(task, db, smtp);
    }

    return InterceptorDecision::Handled;
}
```

##### approve / reject

```rust
fn handle_approve(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;

    // 校验发送者是 task 指定的审阅者
    if task.reviewer.as_deref() != Some(&sender) {
        return Err("you are not the assigned reviewer");
    }

    task.status = Status::Done;
    db.update_task(task);
    db.insert_event(task.id, "approved", sender);
    smtp.reply(cmd.from, "审阅通过，task "+task.id+" 已完成");
    smtp.notify(&task.assignee, "你的任务 "+task.id+" 已通过审阅");
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
    smtp.reply(cmd.from, "已退回 "+task.assignee+" 返工");
    smtp.notify(&task.assignee, "你的任务 "+task.id+" 被退回，原因: "+cmd.params["reason"]);
    return InterceptorDecision::Handled;
}
```

##### block / unblock

```rust
fn handle_block(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;

    // 任意成员可 block（但不允许多次重复 block）
    task.status = Status::Blocked;
    db.update_task(task);
    db.insert_event(task.id, "blocked", sender);
    smtp.notify_all(task.project_id, "任务 "+task.id+" 被 "+sender+" 阻挡");

    // 自动通知 Orchestrator
    let orch = db.get_orchestrator_email();
    smtp.notify(orch, "需协调: "+task.id+" 被 "+sender+" 阻挡");
    return InterceptorDecision::Handled;
}

fn handle_unblock(cmd, sender) {
    let task = db.get_task(cmd.task_id)?;
    let member = db.get_member_by_email(&sender)?;

    // 仅 Orchestrator 或 Human 可 unblock
    if member.role != "orchestrator" && member.role != "human" {
        return Err("only orchestrator or human can unblock");
    }

    task.status = Status::Running;
    db.update_task(task);
    db.insert_event(task.id, "unblocked", sender);
    smtp.notify(&task.assignee, "你的任务 "+task.id+" 已解除阻挡");
    return InterceptorDecision::Handled;
}
```

##### output

```rust
fn handle_output(cmd, sender) {
    let project = db.get_project()?;
    let member = db.get_member_by_email(&sender)?;

    // 1. 角色校验
    if member.role != "verifier" {
        return Err("only verifier can output");
    }

    // 2. 检查最终 task 是否完成
    let output_task = db.get_task(&project.output_task_id)?;
    if output_task.status != Status::Done {
        return Err("output task is not done yet");
    }

    // 3. 检查中间产物流转合规
    let issues = db.verify_pipeline_integrity(project.id, project.plan_version)?;
    if !issues.is_empty() {
        return Err("pipeline integrity check failed: " + issues.join(", "));
    }

    // 4. 通知全员 project output
    project.status = Status::Completed;
    db.update_project(project);
    smtp.notify_all(project.id, "项目输出已放行，"+output_task.summary);
    return InterceptorDecision::Handled;
}
```

##### heartbeat / comment / show / list / members / gateway-info

这些是只读或轻量操作，直接读 board.db 回复，不写状态：

```rust
fn handle_heartbeat(cmd, sender) {
    db.touch_task(cmd.task_id);         // 更新 updated_at
    db.insert_event(cmd.task_id, "heartbeat", sender);
    smtp.reply(cmd.from, "heartbeat recorded");
    return InterceptorDecision::Handled;
}

fn handle_gateway_info(cmd, sender) {
    let info = db.get_gateway_info();  // 从 config 或 projects 表读取
    smtp.reply(cmd.from,
        "gateway_url: " + info.url + "\n" +
        "api_version: v1\n" +
        "board_email: " + info.board_email);
    return InterceptorDecision::Handled;
}
```

#### 路径 B: Python preprocessor（详细执行逻辑）

preprocessor 收到 payload。三个指令需要处理：

##### init（项目初始化）

```python
def a2a_board_preprocessor(payload, headers):
    subject = payload.get("subject", "")
    body = payload.get("body", "")

    if "[A2A] init" not in subject.upper():
        return payload  # 不是 init，继续检查其他

    # 解析 body 中的成员列表
    members = parse_members_from_body(body)

    # 调用 Rust API 写入 board.db
    client = _GatewayClient(gateway_url, api_key)
    result = client._request("PUT", f"/api/v1/a2a/{project_id}/init", {
        "members": members,
        "board_email": f"board@{project_id}.a2a",
        "gateway_url": gateway_url,
    })

    # 建立 agentmail 白名单
    for m in members:
        manage_contacts(action="add", address=m["email"], direction="all")

    # 设置 session key，放行给 agent session 做后续通知
    payload["_a2a_session_key"] = f"a2a:{project_id}:{sender_email}"
    payload["_role_prompt"] = read_role_prompt("orchestrator")

    return payload
```

##### create（按编排方案创建 task 树）

```python
if "[A2A] create" in subject.upper():
    # 解析 task graph
    tasks = parse_task_graph_from_body(body)

    # 校验 task graph 一致性
    # - 所有依赖的 parent task 存在
    # - 项目内无环
    # - 所有 assignee 在 project_members 中

    # 调用 Rust API 批量创建
    for t in tasks:
        client._request("POST", f"/api/v1/a2a/{project_id}/command", {
            "verb": "create", "params": t
        })

    payload["_a2a_session_key"] = f"a2a:{project_id}:{sender_email}"
    # 不放 LLM，直接返回 ok
    # 实际 agentmail 工具的 send_mail 调用后面的 preprocessor
    # 会再次经过这个 handler——需要设置 _skip_delivery 防止循环
    return payload
```

##### arbitrate（提请管理员仲裁）

```python
if "[A2A] arbitrate" in subject.upper():
    # 检查发送者权限（仅 Orchestrator / Verifier）
    sender = payload.get("from", "")
    member = lookup_member(sender)
    if member.role not in ("orchestrator", "verifier"):
        send_mail(to=sender, subject="Re: ...", body="无仲裁权限")
        payload["_skip_delivery"] = True
        return payload

    # 构造仲裁邮件发给 Admin
    admin_email = lookup_admin_email()
    send_mail(
        to=admin_email,
        subject="[A2A] arbitrate: " + extract_summary(body),
        body="仲裁请求来自 " + sender + "\n\n" + extract_dispute(body),
        message_id=payload.get("message_id", ""),
    )

    send_mail(to=sender, subject="Re: ...", body="仲裁请求已提交给 Admin")
    payload["_skip_delivery"] = True
    return payload
```

#### 路径 C: LLM agent session

所有 Rust 闭环和 preprocessor 直接处理的指令都不启动 agent session。**只有以下场景会启动 agent session：**

- **日常对话** —— 参与者之间的非 A2A 邮件
- **[Proposal] 评议邮件** —— Orchestrator 发出的编排方案，参与者回复讨论
- **能力问询的回复（非 Hermes 系统兜底）** —— 非 Hermes 系统无 SOUL.md 文件时

这些场景由 agentmail SKILL 和注入的角色行为 prompt 指导 LLM 处理。Board 的 agentmail 地址永远不会启动 LLM session。

#### Verb 一览表

| Verb | 发送者 | 执行路径 | 状态影响 | 说明 |
|------|--------|---------|---------|------|
| complete | Worker / Reviewer | A: Rust 闭环 | running→done/reviewing | 完成任务 |
| approve | 审阅者 | A: Rust 闭环 | reviewing→done | 放行 |
| reject | 审阅者 | A: Rust 闭环 | reviewing→running | 退回 Worker |
| block | 任意成员 | A: Rust 闭环 | →blocked | 阻挡 |
| unblock | Orchestrator / Admin | A: Rust 闭环 | blocked→running | 解除阻挡 |
| heartbeat | Worker | A: Rust 闭环 | 不变 | 更新时间戳 |
| comment | 任意成员 | A: Rust 闭环 | 不变 | 添加备注 |
| reassign | Orchestrator | A: Rust 闭环 | 不变 | 重新分配 |
| edit | Orchestrator | A: Rust 闭环 | 不变 | 修改描述 |
| deadline | Orchestrator | A: Rust 闭环 | 不变 | 修改截止时间 |
| show | 任意成员 | A: Rust 闭环 | — | 查询 |
| list | 任意成员 | A: Rust 闭环 | — | 列表 |
| members | 任意成员 | A: Rust 闭环 | — | 查询成员 |
| gateway-info | 任意成员 | A: Rust 闭环 | — | 返回 gateway URL |
| output | Verifier | A: Rust 闭环 | 完成→全员通知 | 最终放行 |
| cancel | Orchestrator | A: Rust 闭环 | →cancelled | 取消 |
| create | Orchestrator | B: Python preprocessor | 创建 task | 按方案创建 |
| init | Admin | B: Python preprocessor | 创建项目 | 初始化 |
| arbitrate | Orchestrator / Verifier | B: Python preprocessor | 不变 | 提请管理员 |

#### output 校验逻辑

```rust
fn handle_output(&self, cmd: &A2aCommand) -> Result {
    let task = self.db.get_task(&cmd.task_id)?;
    let project = self.db.get_project()?;

    // 1. 校验发送者角色
    let member = self.db.get_member_by_email(&cmd.sender)?;
    if member.role != "verifier" {
        return Err("only verifier can output");
    }

    // 2. 校验该 task 是项目最终输出 task
    // （由编排方案指定，project 表记录 output_task_id）

    // 3. 校验中间产物流转合规
    // 检查所有中间 task 是否已按编排方案完成
    // - 所有非 output 的 task 状态为 done
    // - 被审阅退回的 task 最终也是 done（有 approved 事件）
    // - 没有未处理的 cancelled 导致依赖断裂

    // 4. 写入 board.db、通知全员
    self.notify.project_output(&task)?;
    Ok(...)
}
```

#### 通知机制

Rust 侧：`EmailFactory.send_outbound()` → `email_records` 表 → SMTP relay。
Python 侧：`send_mail()` → `POST /api/v1/send` → Rust send handler → 同一条链路。

#### 自动归档

`board/archiver.rs` 定时器，每天扫描。output 完成超过 7 天 → `SET status=archived`。归档后拒接 command。不支持恢复。

---

### 四、Hermes agent 逻辑层（Python）

#### Webhook 处理链

```
Rust gateway HTTP POST → webhook.py _handle_webhook()
  ├─ 验证、限流
  ├─ ★ 预处理器（patch 脚本注入）
  │   PREPROCESS_REGISTRY[name](payload) ← a2a_board.py
  ├─ 渲染 prompt
  ├─ 创建 MessageEvent(text=prompt)
  └─ → agent session
```

**只有复杂命令（create/arbitrate/init）和日常对话会走到 agent session。** 简单命令已在 Rust A2aInterceptor 中闭环。

#### Preprocessor：a2a_board.py

```
收到邮件 → a2a_board preprocessor 运行

  ├─ Subject 含 [A2A] capability-inquiry？
  │   → 读取 ~/.hermes/profiles/<name>/SOUL.md + skills list
  │   → 填充 whoami.md 模板
  │   → send_mail() 回复，不启动 LLM
  │   → payload["_skip_delivery"] = True
  │
  ├─ Subject 含 [A2A] create / init / arbitrate？
  │   → 调用 _GatewayClient 访问 Rust API
  │   → 设置 _a2a_session_key
  │   → 注入角色行为 prompt 到 payload["_role_prompt"]
  │   → 放行给 agent session
  │
  └─ 其他邮件
      → 放行（不处理）
```

#### 角色行为注入

角色行为不写入 SKILL.md 文件。而是由 preprocessor 在检测到 A2A 复杂命令时，将对应角色的行为指导文本添加到 `payload["_role_prompt"]` 中。Webhook handler 在构建 prompt 时拼接此内容到 user message 中：

```python
# webhook handler prompt 构建逻辑
role_prompt = payload.get("_role_prompt", "")
if role_prompt:
    prompt = f"{prompt}\n\n---\n{role_prompt}"
```

角色行为停留在**纯文本 prompt 层面**，不改变 SKILL 加载路径。`agentmail/a2a_roles/` 目录包含纯文本片段：

```
├── orchestrator.md    目标分解、能力发现、编排、巡视、仲裁
├── verifier.md        验收标准审阅、中间产物合规检查、output
└── worker.md          执行、heartbeat、complete、block
```

#### whoami.md 能力自述

`agentmail/skill/whoami.md` 是 prompt 模板，含 4 个占位符。能力自述不走 LLM，由 preprocessor 直接处理。

非 Hermes 系统的 agent（没有 `~/.hermes/profiles/` 目录）降级到 LLM 自解析兜底。

#### Toolset 设计

新增 `a2a` toolset，用于高频查询优化：

```yaml
toolset: a2a
tools:
  - a2a_show(task_id)
  - a2a_list(project, status, assignee)
  - a2a_members(project)
  - a2a_heartbeat(task_id, note)
```

所有写操作（complete/block/unblock/output等）保留邮件方式——Rust 拦截器处理，延迟已很低，且需要 email 审计痕迹。

#### 利用现有 agentmail 能力

| 避免新造 | 使用现有能力 |
|---------|------------|
| 成员白名单 | `manage_contacts()` |
| 角色标注 | `set_contact_profile(relationship="a2a:role:project")` |
| 任务评论线程 | email threading + `email_summary()` |
| 项目讨论追踪 | 标准邮件线程 |

---

## 第四层：核心协作流程

### 五、能力发现与团队共识

#### 两套信息体系

| 维度 | 个人认知（per-agent） | 集体共识（board DB） |
|------|---------------------|---------------------|
| 存储 | `agent_state[agent_addr]` | `board.db` 项目文件 |
| 写入者 | agent 自身 | 全体参与者通过共识流程 |
| 视角 | 主观、个性化 | 客观、可验证 |
| 同步 | 通过邮件自然流动 | — |

#### 能力发现流程

Orchestrator 向每个项目成员发送 `[A2A] capability-inquiry` 邮件。成员回复能力自述（Hermes 系统由 preprocessor 直接回复，非 Hermes 系统由 agent 自身回复）。

#### 编排共识流程

```
Orchestrator 基于能力矩阵撰写方案 v1
  → [Proposal] 发给全体参与者
  → 参与者评议
  → Orchestrator 修订
  → 重复直到无新异议 → @admin 确认
  → Orchestrator → Board: [A2A] create
```

### 六、审阅机制

#### 逐 task reviewer 字段

| 场景 | reviewer 字段 | 流转 |
|------|-------------|------|
| 不需审阅 | `null` | complete → done → promote |
| 单审阅者 | `architect@sys` | complete → reviewing → approve → done |
| 多人审阅 | 创建审阅 task | T1r-arch + T1r-dba → 都 done → T3 |

`reviewer` 可以是任意项目成员，不限于 Verifier。

#### 审阅拒绝

reject → `reviewing → running`（自动退回 Worker）。Worker 不服 → `block` → Orchestrator 查询事件日志解决。

### 七、Verifier 审查标准

Verifier 为最终 output 把关，需按以下维度审查：

| 审查维度 | 检查内容 |
|---------|---------|
| 任务完成度 | 所有 task 状态是否为 done，是否有未处理的 rejected 循环 |
| 流转合规 | 中间产物是否按编排方案的依赖关系流转，有无跳过的步骤 |
| 审阅记录 | 被审阅的 task 是否有 approve 事件，拒绝是否有合理原因 |
| 交付物质量 | task summary 和 metadata 是否完整、格式是否规范 |

审查不是主观判断，而是对照编排方案和 board 事件日志进行校验。Board 的 `output` handler 会自动检查前三个维度（代码级校验），第四个维度由 Verifier 的 SKILL 指导 LLM 判断。

### 八、Session 复用机制

所有发给 Board 的 `[A2A]` 指令邮件**不需要 session 复用**（Rust 拦截器直接处理，不走 webhook）。

需要 session 复用的只有**复杂命令**（create/arbitrate/init）和**日常对话**——它们走到 Python agent session。同一项目同一参与者的这些邮件复用 session 上下文。

---

## 第五层：实施

### 九、实现阶段

| Phase | 组件 | 内容 | 前置 |
|-------|------|------|------|
| P0 | `board/models.rs` + `board/db.rs` | board.db 表结构 + CRUD（含 gateway_url 字段） | 现有 amail-gateway |
| P0 | `board/commands.rs` | 所有 verb 业务逻辑 + `authorize()` + `verify_output()` | P0 db |
| P0 | `board/handlers.rs` | command/task/tasks/members/gateway-info/init | P0 commands |
| P0 | `board/router.rs` | RouterHook 挂路由 | P0 handlers |
| P0 | `board/interceptor.rs` | Board 角色：处理 [A2A] 指令，简单命令闭环，复杂放行 | P0 commands |
| P0 | `board/notify.rs` | EmailFactory 通知 | 现有 core |
| P0 | `board/archiver.rs` | 归档定时器 | P0 db |
| P0 | `a2a_board.py` | Python preprocessor（capability-inquiry/create/arbitrate/init） | P0 Rust API |
| P1 | core 修改 | strategy.rs 加 InboundInterceptor + webhook.rs 链 | — |
| P1 | `tools/a2a_tools.py` | a2a toolset 的 4 个 tool | P0 Rust API |
| P1 | 角色行为片段 × 3 | `agentmail/a2a_roles/` 纯文本 prompt 片段 | — |
| P1 | whoami.md | 能力自述 prompt 模板 | — |
| P2 | 通知可靠性 | 重试、去重 | P0 notify |
