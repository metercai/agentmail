# A2A Board 产出物传递方案

## 0. 架构关键

```
Worker 发 complete（带附件）→ Board 地址 → Gateway SMTP
  → interceptor 提取附件 metadata → 写入 task.summary
  → notify 发送通知邮件（带附件）→ Agent 邮箱 → webhook
  → Agent 从 webhook 接收附件（通用能力，不做二次存储）
  → Toolset 通过 API 查询 summary（获取 artifact 元数据，核验附件是否收到）
```

核心逻辑：
- Gateway **不存储**文件——附件跟着邮件流走
- Agent **不二次提取**——webhook 已保存附件到本地
- 附件通过 notify 邮件链转发——`complete` 邮件附件 → 提取 metadata → notify 邮件带附件发出

## 1. 产出物传递

### 1.1 完整链路

```
Worker
  ↓ SMTP complete T1 + login_api.rs（附件）
Gateway SMTP Receiver
  ↓ interceptor: 解析 MIME → 提取附件名/类型/大小 → 暂存附件内容（内存 or /tmp）
  ↓ do_complete(task_id, sender, summary_json)
  ↓ notify_review_needed(&task) — 构造邮件：Subject + Body + 附件
Gateway SMTP Sender
  ↓ 发送通知邮件给 reviewer
Agent（reviewer）
  ↓ webhook 收到通知邮件（通用入口）→ 附件自动保存
  ↓ 用 toolset 查询 task.summary 核验 artifact 列表
```

### 1.2 Gateway 改动

**interceptor.rs**（当前 L367-373 仅解析 subject+body）：

```
handle_board_email():
  if verb == "complete":
    // 已有：解析 verb + task_id + body JSON
    // 新增：
    1. 从 payload["attachments"] 取附件列表
    2. 构造 artifact 条目：{name, size, content_type, type: "attachment"}
    3. 合并 body JSON 中的 url 引用
    4. 构造 summary JSON
    5. 暂存附件内容（传给 notify 用）
    6. 调用 do_complete(conn, task_id, sender, summary)
    7. 构造通知邮件时携带附件
```

**notify.rs**（当前 `create_email` 只发文本）：

```
create_email() → create_email_with_attachments(recipient, subject, body, attachments)
```

**commands.rs**：提取 `do_complete()` 公共函数（P1，~30 行）。

### 1.3 summary JSON 结构

```json
{
  "description": "登录 API 完成，REST 接口，JWT 认证",
  "artifacts": [
    {"name": "login_api.rs", "size": 2048, "type": "attachment"},
    {"name": "PR #42", "url": "https://github.com/x/pull/42", "type": "url"}
  ]
}
```

### 1.4 Agent 侧

Agent 通过通用 webhook 接收通知邮件——附件已自动保存到本地（通用能力，非 board 专属）。Toolset 查询：

```
board_task_show(T1)
→ {"status":"ok", "task":{..., "summary":{...}}}
```

Agent 用 `summary.artifacts[].name` 与 webhook 接收到的附件文件名核验一致性。

### 1.5 Toolset 可靠性验证

Toolset 是纯查询入口（HTTP API），不传递文件。可靠性验证方式：

| 方式 | 说明 |
|------|------|
| 附件名匹配 | `summary.artifacts[].name` vs webhook 接收的附件文件名 |
| 数量匹配 | `summary.artifacts` 的 attachment 条目数 vs webhook 附件数 |
| 大小校验 | `summary.artifacts[].size` vs webhook 附件的实际大小 |

若不一致，Agent 可通过会话流反馈异常。

## 2. 父级产出物传递

**现状**：`promote_children`（commands.rs L695-714）只做 Todo→Ready，`notify_assigned`（notify.rs L12-22）不含父级上下文。

**目标**：子任务 promote 时，通知携带父级 artifact 列表。

### 2.1 notify_assigned 参数扩展

增加 `parent_artifacts: Option<Vec<(&str, &str)>>` — 每项是 `(short_id, artifact_line)`：

```
前序产出物:
  T1 登录 API
    - login_api.rs (2KB, attachment)
    - PR #42 (https://github.com/x/pull/42)
```

### 2.2 show 返回 parent_summaries

`handle_show`（L388-391）和 `handle_get_task`（handlers.rs L89-101）的 `CommandResponse.data` 附加父级摘要数组。

## 3. 通知格式规范

统一 Subject + Body 模板（notify.rs 11 个函数）。格式同前版方案，以现有 notify.rs 参数映射为准。

## 4. 并行执行模式

无需新增功能——`parents` 数组 + `promote_children` 已覆盖 DAG。仅需：
- 放开 create 的"同 batch" parents 限制（commands.rs ~5 行）
- 循环依赖检测（db.rs ~20 行）

## 5. 实施分阶段

| 阶段 | 内容 | 文件 |
|------|------|------|
| **P1** | `do_complete()` + summary 参数 | `commands.rs` |
| **P2** | interceptor 提取附件 metadata + 通知带附件 | `interceptor.rs` + `notify.rs` |
| **P3** | `notify_assigned` 含父级产物 | `notify.rs` + `commands.rs` |
| **P4** | `show`/`list` 返回 parent_summaries | `commands.rs` + `handlers.rs` |
| **P5** | 跨 batch parents + 循环检测 | `commands.rs` + `db.rs` |
| **P6** | 通知 Body 规范化 | `notify.rs` |
| **P7** | 测试 + 文档 | `category-6` + GUIDE |
