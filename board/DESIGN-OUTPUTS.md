# A2A Board 产出物传递 & 通知规范化方案

## 1. 产出物传递

**现状：** Task 有 `summary` 和 `metadata` 字段，但 `summary` 永远是空字符串，`metadata` 仅在 create 时设置后永不修改。`complete` 不支持描述产出物。SMTP 附件被拦截器忽略。

**目标：** Worker 完成时可通过邮件附件和/或 URL 引用传递产出物，后续任务能获取。

### 1.1 传递方式

| 方式 | 来源 | 存到哪里 |
|------|------|---------|
| SMTP 附件 | `complete` 邮件附件 | `outputs/{task_id}/item-{idx}-{filename}` |
| URL 引用 | complete JSON body | summary JSON 中的 `artifacts[].url` |
| 混合 | 两者同时 | path + url 都写入 |

### 1.2 存储布局

```
~/.agentmail/{system_id}/board/{board_id}/
├── board.db
├── role_prompt/
└── outputs/
    └── {task_id}/
        ├── item-0-login_api.rs
        └── item-1-api_doc.md
```

### 1.3 summary JSON 结构

```json
{
  "description": "登录 API 完成",
  "artifacts": [
    {
      "name": "login_api.rs",
      "path": "outputs/tid/item-0-login_api.rs",
      "url": "https://github.com/x/pull/42",
      "type": "code"
    }
  ]
}
```

### 1.4 统一入口

当前 `handle_complete` 的逻辑内嵌在 handler 中，SMTP 和 Toolset 都各走各的。提取为 `do_complete(conn, task_id, sender, summary)` 公共函数：

```
SMTP 入口:
  interceptor: 解析附件 → 保存到 outputs/ → 构造 summary JSON
              ↓
         do_complete(conn, task_id, sender, summary)
              ↓
Toolset/API 入口:
  handler: 直接从请求体取 summary JSON
              ↓
         do_complete(conn, task_id, sender, summary)
```

`do_complete` 内部：
1. 写入 `task.summary`
2. `insert_event("completed", summary)`
3. 有 reviewer → `notify_review_needed`
4. 无 reviewer → `promote_children` + `notify_approved`

### 1.5 当前代码依据

**commands.rs L129-146:** `handle_complete` 不接收 summary，写入状态后调 notifier。

```rust
// L129-145 现状
fn handle_complete(conn, notifier, cmd, sender) {
    let task_id = extract_task_id(cmd)?;  // 从 cmd.task_id 取
    let mut task = db::get_task(conn, &task_id)?;
    require_assignee(&task, sender)?;
    // 无 summary 写入
    if task.reviewer.is_some() {
        task.status = TaskStatus::Reviewing;
    } else {
        task.status = TaskStatus::Done;
    }
    db::update_task(conn, &task)?;
    // ...
}
```

**interceptor.rs L367-373:** 对 SMTP 入口调用 execute_command 时，只传递 subject 解析出的 verb+task_id+params，忽略附件。

```rust
// L367-373 现状
let cmd = A2aCommand { verb, task_id, params };  // params = body JSON
match commands::execute_command(&conn, &notifier, &cmd, &sender) {
```

## 2. 父级产出物传递

**现状：** `promote_children`（commands.rs L695-714）只在父任务全部 Done 时将子任务从 Todo→Ready，不发父级产出物信息。`notify_assigned`（notify.rs）通知不含父级上下文。

**目标：** 子任务被 promote 时，通知中包含父级产出物摘要（文件名/URL）。

### 2.1 notify_assigned 增强

notify.rs L12-22 现状：

```rust
pub fn notify_assigned(&self, task: &Task) {
    let subject = format!("[A2A] assigned {}: {}", task.short_id, task.title);
    let body = format!(
        "task_id: {}\nboard: {}\n标题: {}\n描述: {}\n审阅者: {}\n创建人: {}",
        task.id, task.board_id, task.title, task.body,
        task.reviewer.as_deref().unwrap_or("(无)"),
        task.created_by,
    );
    self.create_email(&task.assignee, &subject, &body);
}
```

改为接受 `parent_summaries: Option<Vec<ParentArtifact>>` 参数，有父级时补充：

```
前序产出物:
  T1 登录 API → outputs/{tid}/item-0-login_api.rs
  T2 UI 设计稿 → https://figma.com/x
```

### 2.2 show 返回 parent_summaries

`handle_show`（commands.rs L388-391）现状只返回 task 本身。增强：

```json
{
  "status": "ok",
  "task": { ... },
  "data": {
    "parent_summaries": [
      {"short_id": "T1", "title": "登录 API", "summary": {...}}
    ]
  }
}
```

## 3. 通知格式规范

**现状：** 11 个 notifier 函数各自拼接 Subject 和 Body，格式不一致，部分用英文，部分用中文。

**目标：** 统一模板，减少 Agent 理解歧义。

### 3.1 Subject 统一

现有 Subject 格式各异（`"Board {} initialized"`, `"[A2A] notice: ..."`, `"[A2A] output: ..."`）。统一为：

```
[A2A] {event-type} {short_id}: {title}
```

### 3.2 Body 统一

```text
── A2A Board ──

{event_label}
  任务: {short_id} — {title}
  看板: {board_short_id}

── 上下文 ──
{context_fields}

── 操作 ──
{action_hint}
```

各事件字段基于现有 notify.rs 参数映射，不新增数据源。详情见 notifier 各函数签名。

## 4. 并行执行模式

**现状：**
- `parent_ids: Vec<String>` — 已支持多父 fan-in
- `promote_children` L701-705 — 已检查所有 parent Done
- 多个 task 引用同一 parent — fan-out 已支持
- `create` 时 `parents` 参数限制在同 batch 内 — 唯一限制

**目标：** DAG 模式全由 `create` + `parents` 表达，无需新动词或新字段。

### 4.1 需要改的

| 需求 | 依据 | 改动 |
|------|------|------|
| 跨 batch parents | `handle_create` L489-490 只遍历当前 batch 做父级校验 | 去掉"同 batch"限制 |
| 循环依赖检测 | create 时检查 parents 不形成环（新） | `db.rs` 加 DFS |

其余 fan-out/fan-in/混合模式无需改代码。

### 4.2 Worker 多任务

现状：Worker 收到多个 `assigned` 邮件，按收件顺序处理。`list` + assignee 过滤通过 API 可用，SMTP 通过 `list` params 可用。无需特殊机制——Worker 自行决定优先级。

## 5. 实施分阶段

| 阶段 | 内容 | 文件 | 改动量 |
|------|------|------|:--:|
| **P1** | `do_complete()` + summary 参数 | `commands.rs` | ~30 行 |
| **P2** | interceptor 附件保存 + summary 合并 | `interceptor.rs` | ~40 行 |
| **P3** | `notify_assigned` 含父级产物 | `notify.rs` + `commands.rs` | ~20 行 |
| **P4** | `show`/`list` 返回 parent_summaries | `commands.rs` + `handlers.rs` | ~30 行 |
| **P5** | 跨 batch parents 解除限制 | `commands.rs` | ~5 行 |
| **P6** | 循环依赖检测 | `db.rs` | ~20 行 |
| **P7** | 通知 Body 规范化 | `notify.rs` | ~80 行 |
| **P8** | 测试 + 文档 | `category-6` + GUIDE | |
