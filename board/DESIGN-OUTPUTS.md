# A2A Board 产出物传递方案

## 1. 架构基础

```
Worker SMTP complete (带附件) → Gateway receiver.rs
  data_end(): parse MIME → save_attachment → mail_id 写入 meta
  trigger_tx → Scheduler → Interceptor chain → A2aInterceptor
  interceptor: 处理 [A2A] complete
    ├─ 读取 attachments_json → 构造 summary
    ├─ 写入 task.summary
    ├─ create_permission (assignee + reviewer + board_address)
    └─ 调 do_complete()
  do_complete():
    ├─ 更新 task.status
    ├─ insert_event
    └─ notify_review_needed (通知带附件 UUID)
notify 创建出站邮件:
  create_outbound(attachments=attachments_json) → mail_id 引用
Scheduler 投递通知邮件:
  load_attachment_data → 读文件 → SMTP/Webhook → Agent 接收
```

## 2. 数据模型

### Task 字段
```rust
pub summary: String,     // JSON: {"description":"...", "artifacts":[...]}
```

### summary JSON
```json
{
  "description": "登录 API 完成",
  "artifacts": [
    {"attachment_id":"abc123", "filename":"login_api.rs", "content_type":"text/plain", "size":2048},
    {"filename":"PR #42", "url":"https://github.com/x/pull/42", "type":"url"}
  ]
}
```

## 3. 三条保护线

| 机制 | 保护范围 | 实现 |
|------|---------|------|
| `mail_count` | 通知邮件引用 → 邮件交付前不删 | notify create_outbound 传入 attachments_json |
| `perm_count` | board 地址永续权限 → 附件永不过期 | interceptor create_permission(board_address) |
| `perm_count` | assignee + reviewer 一次性下载权 | interceptor create_permission(assignee, reviewer) |

### 时效分析
- `cleanup_completed_email`：邮件交付完成时检查 `mail_count <= 1 && perm_count == 0` → 不删（有权限/引用）
- `process_expired_attachments`：720h（30d）定时扫描，检查同上 → board_address 权限永续保护

## 4. 附件传递路径

### 路径 A：通知邮件（Agent 在线）
```
notify 通知邮件（含附件）→ SMTP → Agent webhook → 附件自动保存到本地
Toolset: board_task_show → summary JSON → 匹配本地文件名/size 核验
```

### 路径 B：API 下载（Agent 离线/晚加入）
```
Toolset: board_task_show → summary JSON → 提取 uuid
         → GET /api/v1/attachments/:id → consume_download (一次性)
         → 保存到本地
```

## 5. Gateway 改动清单

| 文件 | 改动 | 行数 | 说明 |
|------|------|:--:|------|
| `commands.rs` | `do_complete()` 提取 + summary 参数 | ~30 | SMTP/Toolset 统一入口 |
| `interceptor.rs` | 读 attachments_json → 构造 summary | ~20 | complete + output 时处理附件 |
| `interceptor.rs` | `create_permission` (assignee+reviewer+board) | ~15 | complete + output 时创建下载权限 |
| `notify.rs` | `Notifier` 加 `attachments_json: Option<String>` 字段 | ~3 | 一次改动，所有通知自动携带附件 |
| `notify.rs` | `create_email` 检查并传入 attachments_json | ~3 | mail_count 保护 |
| `commands.rs` | `notify_assigned` 含父级产物 | ~10 | promote_children 时 |
| `commands.rs` | `show`/`list` 返回 parent_summaries | ~15 | data 字段 |
| `handlers.rs` | `handle_get_task` 附加 parent_summaries | ~15 | API 查询 |
| `commands.rs` | 跨 batch parents | ~5 | DAG 支持 |
| `db.rs` | 循环依赖检测 | ~20 | DAG 校验 |
| `notify.rs` | Body 模板统一 | ~80 | 通知规范化 |

**总计 ~207 行。**

## 6. Agent 侧

无代码改动——复用通用 webhook 附件接收。

- Toolset `board_task_show` → `{data: {artifacts: [...], parent_summaries: [...]}}`
- Toolset `board_task_list ?parents=true` → 父级 summary 注入
- Attachment 下载 → `GET /api/v1/attachments/:id`（一次性，Agent 自行缓存）

## 7. 通知格式

所有 notify 函数统一 Subject + Body 模板：

```
Subject: [A2A] {event-type} {short_id}: {title}

Body:
── A2A Board ──

{event_label}
  任务: {short_id} — {title}
  看板: {board_short_id}

── 上下文 ──
{context_fields}

── 操作 ──
{action_hint}
```

## 8. 并行执行

DAG 通过 `parents` 数组表达，无需新字段或新动词。改动：
- 跨 batch parents（解除 create 中"同 batch"限制）
- 循环依赖检测（create 时 DFS）

## 9. 附件流转覆盖 & Board 归档

### 9.1 Notifier 字段生效范围

`Notifier` 加 `attachments_json` 后，所有 14 个 notify 函数自动携带附件——无需逐个改动。

| 类别 | 动词 | count |
|------|------|:--:|
| 产出物（建 board 级权限） | `complete`, `output` | 2 |
| 临时交流（不建 board 级权限） | `create`, `comment`, `review`, `approve`, `reject`, `reassign`, `block`, `unblock`, `cancel`, `reopen`, `arbitrate`, `refresh` | 12 |

两类区别仅在于是否调 `create_permission(board_address)`——产出物需要长期保留，临时文件仅靠通知邮件转发。

### 9.2 Board 归档时权限回收

Board `completed` 后，清除该 board 所有附件的 `board_address` 下载权限——后续由 30 天自然生命周期管理。处理入口：`handle_confirm_output`（interceptor.rs）或 `handle_output` 成功后 Owner 确认时。

