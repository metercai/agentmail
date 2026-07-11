# A2A Board 产出物传递 & 通知规范化方案

## 0. 架构现实

Gateway SMTP receiver（receiver.rs）对所有入站邮件做统一处理：

```
Worker SMTP → Gateway receiver.rs
  data_end():
    1. parse_mime_detailed → (body, attachments, subject, ...)
    2. create_inbound → 存储邮件记录
    3. 遍历 attachments: save_attachment → 文件落地 + attachment_meta 表 + 权限
    4. update_email_attachments → 附件 UUID 写回邮件记录
    5. trigger_tx → 通知 scheduler 处理
    ↓
Scheduler → 分发到拦截器链 → A2aInterceptor
    ↓
  interceptor: 从 payload 读取 subject/body → execute_command
    ↓
  complete → do_complete(conn, task_id, sender, summary)
```

**关键事实：**
- 附件在 interceptor 执行前已落盘（L695-732）
- 附件 metadata 在 `attachments_meta` 表，含 UUID → 下载权限
- 邮件记录的 `attachments_json` 字段含附件 UUID/文件名/大小
- Gateway 已有附件下载 API（attachment_factory）

## 1. 产出物传递

### 1.1 完整链路

```
Worker SMTP complete T1 + login_api.rs
  ↓
receiver.rs data_end():
  save_attachment(data, sender, "login_api.rs", uuid)  // L701
  create_meta(uuid, filename, content_type, sender)     // L714
  create_permission(uuid, reviewer_email)               // L726
  update_email_attachments(mail_id, json)               // L738
  ↓
interceptor 处理 [A2A] complete:
  从 payload["attachments_json"] 取附件列表
  从 body JSON 取 url 引用
  合并 → 构造 summary JSON
  调用 do_complete(conn, task_id, sender, summary)
  ↓
do_complete:
  写入 task.summary
  insert_event("completed", summary)
  notify_review_needed → 邮件通知 reviewer
```

### 1.2 Agent 获取附件

Agent 有两种方式：

| 方式 | 路径 |
|------|------|
| 通知邮件 | notify_review_needed 邮件中包含附件 UUID → Agent 用 API 下载 |
| Toolset | `board_task_show` 返回 summary JSON（含 artifact 名/大小）→ Agent 用文件名匹配 or API 下载 |

### 1.3 Gateway 改动

**do_complete()**（commands.rs，P1 ~30 行）：
- 从 handle_complete 提取公共函数
- 接受 summary_json 参数
- 写入 task.summary + insert_event + notify

**interceptor**（interceptor.rs L367-373，P2 ~15 行）：
- complete 时从 payload["attachments_json"] 读取 SMTP receiver 已保存的附件列表
- 合并 body JSON 中的 url 引用
- 构造 summary JSON → 传给 do_complete

**notify**（notify.rs，P3 ~20 行）：
- notify_review_needed / notify_assigned 邮件中包含附件 UUID
- Agent 用 UUID 通过 attachment API 下载

### 1.4 summary JSON 结构

```json
{
  "description": "登录 API 完成",
  "artifacts": [
    {"name": "login_api.rs", "size": 2048, "uuid": "abc123...", "type": "attachment"},
    {"name": "PR #42", "url": "https://github.com/x/pull/42", "type": "url"}
  ]
}
```

## 2. 父级产出物传递

与 §1 相同链路——promote_children 时调 notify_assigned，通知中包含父级 task.summary 中的 artifact 列表。

## 3. 通知格式规范

所有 notify 函数统一 Subject + Body 模板。

## 4. 并行执行模式

parents 数组 + promote_children 已覆盖 DAG。仅需跨 batch parents + 循环检测。

## 5. 实施分阶段

| 阶段 | 内容 | 文件 |
|------|------|------|
| **P1** | do_complete() + summary 参数 | commands.rs |
| **P2** | interceptor 读取 attachments_json + 构造 summary | interceptor.rs |
| **P3** | notify 通知含附件 UUID + 父级产物 | notify.rs + commands.rs |
| **P4** | show/list 返回 parent_summaries | commands.rs + handlers.rs |
| **P5** | 跨 batch parents + 循环检测 | commands.rs + db.rs |
| **P6** | 通知 Body 规范化 | notify.rs |
| **P7** | 测试 + 文档 | category-6 + GUIDE |
