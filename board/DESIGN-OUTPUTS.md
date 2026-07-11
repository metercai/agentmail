# A2A Board 产出物传递 & 通知规范化方案

## 1. 产出物传递

### 1.1 三种传递方式共存

| 方式 | 来源 | summary JSON 内容 |
|------|------|------------------|
| SMTP 附件 | `complete` 邮件附件 | `{"name":"x.rs", "path":"outputs/{tid}/item-0-x.rs"}` |
| URL 引用 | JSON body 或 Toolset | `{"name":"PR #42", "url":"https://github.com/x/pull/42"}` |
| 混合 | SMTP 附件 + JSON body | path + url 都写入 |

### 1.2 存储布局

```
~/.agentmail/{system_id}/board/{board_id}/
├── board.db
├── role_prompt/
└── outputs/
    └── {task_id}/
        ├── item-0-login_api.rs
        ├── item-1-api_doc.md
        └── manifest.json
```

### 1.3 数据模型

**Task 字段：**
```rust
pub summary: String,    // JSON: {"description":"...", "artifacts":[...]}
pub metadata: Option<String>,  // create 时设定，保持不变
```

**summary JSON 结构：**
```json
{
  "description": "登录 API 完成，REST 接口，JWT 认证",
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

### 1.4 两条入口，同一 `do_complete()`

```
┌─ SMTP [A2A] complete T1 (带附件) ─┐
│  interceptor 保存附件到 outputs/    │
│  解析 JSON body 中 artifacts[].url │
│  合并 → 构造 summary JSON           │
└──────────┬─────────────────────────┘
           ▼
       do_complete(conn, task_id, sender, summary_json)
           │
           ├─ 写入 task.summary
           ├─ insert_event("completed", summary)
           ├─ notify_review_needed (有 reviewer)
           └─ 否则 promote_children + notify_approved

┌─ Toolset/API complete ────────────┐
│  传入 summary JSON (url only)      │
└──────────┬────────────────────────┘
           ▼
       do_complete(conn, task_id, sender, summary_json)
```

### 1.5 interceptor 附件处理

```
handle_board_email():
  if verb == "complete":
    1. 解析 payload["attachments"] 数组
    2. 对每个 attachment:
       - 写到 outputs/{task_id}/item-{idx}-{filename}
       - 写入 manifest
    3. 从 body JSON 取 artifacts[].url
    4. 合并 attachment paths + urls → 构造 summary JSON
    5. 调用 do_complete(...)
```

## 2. 父级产出物传递

### 2.1 promote_children 通知增强

子任务被 promote（Todo→Ready）时，通知包含父级产出物摘要：

```
Subject: [A2A] assigned T3: 产品页集成登录
Body:
  ── A2A Board ──
  
  新任务分配
    任务: T3 — 产品页集成登录
    看板: web-redesign
  
  ── 上下文 ──
    描述: 用 T1 的 API 和 T2 的设计稿实现产品页
    分配人: dev@company.com
    审阅者: qa@company.com
    创建人: pm@company.com
    前序产出物:
      T1 登录 API          → outputs/t_T1_xxx/item-0-login_api.rs
      T2 UI 设计稿         → https://figma.com/x
  
  ── 操作 ──
    开始执行后发 [A2A] heartbeat T3
```

### 2.2 show/list 返回 parent_summaries

```
[A2A] show T3
↓
{
  "status": "ok",
  "task": { ... },
  "data": {
    "parent_summaries": [
      {"short_id":"T1","title":"登录 API","summary":{...}},
      {"short_id":"T2","title":"UI 设计稿","summary":{...}}
    ]
  }
}
```

## 3. 通知格式规范

### 3.1 Subject 模板

```
[A2A] {event-type} {short_id}: {title}

event-type: assigned, review-needed, approved, rejected,
            blocked, unblocked, cancelled, output,
            comment, arbitrate, notice
```

| 事件 | Subject |
|------|---------|
| assigned | `[A2A] assigned {sid}: {title}` |
| review-needed | `[A2A] review-needed {sid}: {title}` |
| approved | `[A2A] approved {sid}: {title}` |
| rejected | `[A2A] rejected {sid}: {title}` |
| blocked | `[A2A] blocked {sid}: {title}` |
| unblocked | `[A2A] unblocked {sid}: {title}` |
| cancelled | `[A2A] cancelled {sid}: {title}` |
| output | `[A2A] output {sid}: {title}` |
| comment | `[A2A] comment {sid}: {title}` |
| arbitrate | `[A2A] arbitrate {sid}: {title}` |
| notify_all | `[A2A] notice: {message}` |

### 3.2 Body 模板

```
── A2A Board ──

{event_label}
  任务: {short_id} — {title}
  看板: {board_short_id}

── 上下文 ──
{context_fields}

── 操作 ──
{action_hint}
```

**各事件具体格式：**

#### assigned
```
── 上下文 ──
  描述: {body}
  分配人: {assignee}
  审阅者: {reviewer}
  创建人: {created_by}
  前序产出物:
    {short_id} {title} → {artifact_refs}

── 操作 ──
  开始执行后发 [A2A] heartbeat {sid}
```

#### review-needed
```
── 上下文 ──
  完成人: {assignee}
  产出物:
    {artifact_name} → {path_or_url}

── 操作 ──
  [A2A] approve {sid}   — 通过
  [A2A] reject {sid}    — 退回
```

#### approved
```
── 上下文 ──
  审阅人: {reviewer}

── 操作 ──
  已完成，无后续操作
```

#### rejected
```
── 上下文 ──
  审阅人: {reviewer}
  原因: {reason}

── 操作 ──
  修改后重新 [A2A] complete {sid}
```

#### blocked
```
── 上下文 ──
  发起人: {blocker}
  原因: {reason}

── 操作 ──
  Orchestrator 协调处理
```

#### unblocked
```
── 上下文 ──
  解除人: {unblocker}

── 操作 ──
  继续执行
```

#### cancelled
```
── 上下文 ──
  (none)

── 操作 ──
  停止工作等待新分配
```

#### output
```
── 上下文 ──
  提交人: {verifier}
  任务: {short_id} — {title}
  摘要: {summary}

── 操作 ──
  [Confirm] output {board}  — 验收通过，项目完成
  [A2A] reopen              — 驳回，任务回到 Running
```

#### comment
```
── 上下文 ──
  来自: {commenter}
  内容: {text}

── 操作 ──
  直接回复邮件讨论
```

#### arbitrate
```
── 上下文 ──
  请求人: {requester}
  关联: {task_id}
  争议: {dispute}

── 操作 ──
  Owner/Admin 介入调解
```

#### notify_all
```
── 上下文 ──
  {message}

── 操作 ──
  (none)
```

## 4. 实施分阶段

| 阶段 | 内容 | 文件 |
|------|------|:--:|
| **P1** | `do_complete()` 提取，summary 参数写入 | `commands.rs` |
| **P2** | interceptor 附件保存 + summary 合并 | `interceptor.rs` |
| **P3** | `notify_assigned` 通知含父级产出物 | `notify.rs` |
| **P4** | `show`/`list` 返回 parent_summaries | `commands.rs` + `handlers.rs` |
| **P5** | 所有通知 Body 规范化 | `notify.rs` |
| **P6** | 测试 + 文档同步 | `category-6` + `A2A-BOARD-GUIDE` |
