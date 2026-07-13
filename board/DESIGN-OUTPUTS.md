# A2A Board 指令附件流转和产出物传递方案

## 1. 目标

Board 任务执行过程中，Worker 产出的附件（代码、文档、设计稿等）需要：
- 通过邮件通知链传递给下游 Reviewer 和后续 Worker
- 持久保存到 Board 归档，供离线 Agent 通过 Toolset 查询下载
- 通知格式统一规范，减少多 Agent 理解歧义

## 2. 架构

```
Worker SMTP (带附件) → Gateway receiver.rs
  data_end():
    ├─ save_attachment → 文件落地 + attachments_meta 表
    ├─ create_permission → RCPT TO 收件人权限
    └─ trigger_tx → Scheduler
                       ↓
Scheduler → A2aInterceptor
  intercept():
    ├─ 从 payload 提取 attachments_json → 注入 cmd.params + Notifier
    ├─ execute_command → handler → do_complete/do_output
    │    ├─ 构造 summary JSON → 写入 task.summary
    │    ├─ insert_event
    │    ├─ create_permission (assignee + reviewer + board_address)
    │    └─ notify_* → create_email
    │              ↓
    │         create_outbound(attachments = attachments_json)
    │              ↓
    │         mail_count ≥ 2 → 附件文件受保护
    │
    ├─ Scheduler → deliver_smtp/deliver_webhook
    │    └─ load_attachment_data → 读文件 → MIME 附件
    │
Agent ←── SMTP/Webhook ←── 通知邮件 (含附件实体)
  ├─ 在线：webhook 自动保存附件到本地
  └─ 离线：toolset board_task_show → summary JSON → API download
```

## 3. 数据模型

### Task 字段

```rust
pub summary: String,  // JSON
```

### summary JSON 结构

与邮件记录 `attachments_json` 字段对齐：

```json
{
  "description": "登录 API 完成",
  "artifacts": [
    {"attachment_id": "abc123", "filename": "login_api.rs", "content_type": "text/plain", "size": 2048},
    {"filename": "PR #42", "url": "https://github.com/x/pull/42", "type": "url"}
  ]
}
```

附件条目复用 `attachment_id` / `filename` / `content_type` / `size` 四字段（与 `receiver.rs` L708-713 一致）。URL 引用加 `url` + `type: "url"` 区分。

## 4. 附件生命周期保护

三条保护线，确保附件在 Board 活跃期间不被删除：

| 保护线 | 机制 | 生效范围 |
|--------|------|---------|
| `mail_count` | notify create_outbound 传入 attachments_json → 多封邮件引用同一 UUID | 通知邮件投递前 |
| `board_address perm` | interceptor create_permission(board_address) → perm_count ≥ 1 → 永不过期 | Board 全生命周期 |
| `assignee+reviewer perm` | interceptor create_permission(assignee, reviewer) → 一次性下载 | Agent 首次下载 |

### 4.1 30 天过期保护

`process_expired_attachments`（flows.rs L315）定时扫描 720h 前创建的附件。保护条件：

```rust
if perm_count == 0 && mail_count <= 1 {
    // 删除文件
}
```

`board_address` 权限保持 `perm_count ≥ 1` → 永不触发删除。通知邮件投递完成后 `mail_count` 回落，但权限仍在。直到 Board 归档时主动回收。

### 4.2 附件转发覆盖

所有 14 个 notify 函数通过 `Notifier.attachments_json` 字段统一携带附件，无需逐个改动：

#### 附件通知规则

"入站有附件 → 出站通知带附件" 不是无条件适用。按指令场景分类：

**A 类：传递附件（入站有附件，出站通知携带）**

| 动词 | 场景 | 附件含义 | 出站通知 |
|------|------|---------|---------|
| `complete` | worker 提交产出物 | 任务交付物 | notify_review_needed ✅ |
| `output` | verifier 提交最终产出 | 最终交付物 | notify_output ✅ |
| `comment` | 任何人评论 | 讨论文件（截图、参考文档）| notify_comment ✅ |
| `create` | orch 创建任务 | 设计规格、模板 | notify_assigned ✅ |
| `arbitrate` | 请求仲裁 | 争议证据 | notify_arbitrate ✅ |
| `refresh`/`init` | owner 初始化/更新 board | 看板配置 | notify_all ✅ |

**B 类：不传递附件（纯状态变更，入站附件忽略）**

| 动词 | 场景 | 原因 |
|------|------|------|
| `approve` | 审阅通过 | 无新工作产物 |
| `reject` | 审阅退回 | 无新工作产物 |
| `reassign` | 重新分配 | 管理操作 |
| `block`/`unblock` | 阻塞/解除 | 状态信号 |
| `cancel` | 取消任务 | 管理操作 |
| `edit`/`deadline` | 编辑/设截止 | 无通知 |
| `review` | 设审阅者 | reviewer 已有 task 上下文 |
| `reopen` | 驳回产出 | 状态信号 |

**C 类：Board 级下载权限（产出物长期保留）**

仅 A 类中的 `complete` 和 `output`——只有这两个指令的附件是项目交付物，需要建 `board_address` 下载权限保护到归档。其余 A 类指令的附件为临时交流，仅靠通知邮件转发。

## 5. 产出物传递

### 5.1 同级传递（reviewer）

```
Worker → complete T1 (带附件)
  → notify_review_needed (带附件) → Reviewer 收到
```

### 5.2 父级传递（下游 Worker）

```
T1 approve → promote_children
  → notify_assigned (含父级 artifact 列表) → 下游 Worker 收到
```

`notify_assigned` 通知 Body 包含父级产物摘要：

```
── 上下文 ──
  前序产出物:
    T1 登录 API
      - login_api.rs (2KB, application/octet-stream)
      - PR #42 (https://github.com/x/pull/42)
```

### 5.3 Toolset 查询

```
board_task_show(T3)
→ {
    "status": "ok",
    "task": {...},
    "data": {
      "parent_summaries": [
        {"short_id":"T1","title":"登录 API","summary":{...}},
        {"short_id":"T2","title":"UI 设计稿","summary":{...}}
      ]
    }
  }
```

### 5.4 Agent 获取附件

| 场景 | 路径 |
|------|------|
| 在线 | webhook 收通知邮件 → 附件自动保存 → toolset 查询核验 metadata |
| 离线 | toolset board_task_show → 拿 attachment_id → API download → 一次性下载 |

外转 SMTP（Agent 在另一 Gateway）确认有效：`deliver_smtp` → `load_attachment_data` 读文件 → `send_email` 封装 MIME 附件。

## 6. 通知格式规范

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

## 7. 并行执行

DAG 通过 `parents` 数组表达，`promote_children` 已支持 fan-out/fan-in。需改动：
- 跨 batch parents（解除 create 中"同 batch"限制）
- 循环依赖检测（create 时 DFS）

## 8. Board 归档

Board → `Archived`（已有 `BoardStatus::Archived`）时：

1. 遍历所有 task 的 `summary.artifacts`
2. 有 `attachment_id` 的附件复制到 `a2a_board/{board_id}/outputs/{task_id}/`
3. 更新 summary JSON：引用改为本地路径
4. 删除 `board_address` 下载权限——原文件走 30 天自然回收
5. Board 目录自包含——board.db + outputs/ 可直接打包导出

## 9. 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `models.rs` | `CommandResponse` 加 `data: Option<Value>` | 统一返回结构 |
| `commands.rs` | `do_complete()` + `data_response()` | 统一入口 + summary 写入 |
| `commands.rs` | `do_heartbeat()` / `do_roles()` | API/SMTP 共享核心逻辑 |
| `commands.rs` | `handle_show`/`handle_list` 返回 parent_summaries | 父级产物查询 |
| `commands.rs` | 跨 batch parents + 循环检测 | DAG 支持 |
| `interceptor.rs` | 读 attachments_json → 注入 cmd.params + Notifier | 附件入口 |
| `interceptor.rs` | `create_permission` (assignee+reviewer+board) | 下载权限 |
| `notify.rs` | `Notifier` 加 `attachments_json` 字段 | 所有通知自动携带 |
| `notify.rs` | `create_email` 传入 attachments_json | mail_count 保护 |
| `notify.rs` | `notify_assigned` 含父级产物 | 下游上下文 |
| `notify.rs` | 全部 11 个函数 Body 模板统一 | 通知规范 |
| `handlers.rs` | `handle_list_roles` 调 `do_roles()` | API 复用 |
| `handlers.rs` | `handle_get_task` 附加 parent_summaries | API 查询 |
| `handlers.rs` | `handle_post_heartbeat` 调 `do_heartbeat()` | API 复用 |
| `agentmail_tools.py` | heartbeat 传 actor=toolset | 调用统一 |


## 10. Task 状态机增强

### 10.1 当前状态

```
Ready → Running → Reviewing → Done
         ↕ Blocked
         → Cancelled
  Todo (定义存在但从不创建)
```

### 10.2 目标状态

```
Triage → Todo → Ready → Running → Reviewing → Done → Archived
                  ↑ (promote_children 拉起)
                  ↕ Blocked
                  → Cancelled
```

新增/修复状态转移：

| 状态 | 进入条件 | 来源 | 退出条件 |
|------|---------|------|---------|
| `Triage` | `create` 不设 `assignee`（纯想法） | orchestrator 随手记 | `edit` 设 assignee → Todo |
| `Todo` | `create` 设 `assignee` + `parents` 未满足 | Triage 转化 | parents 全部 Done → Ready |
| `Ready` | `create` 无 parents 或 parents 已满足 | Todo promote | assignee `heartbeat` → Running |
| `Archived` (新) | `[A2A] archive T1` | Done/Cancelled | Board 数据导出后删除 |

### 10.3 改动清单

| 文件 | 改动 | 行数 |
|------|------|:--:|
| `models.rs` | `TaskStatus` 加 `Triage`, `Archived` | ~4 |
| `commands.rs` | `handle_create`: 无 assignee → Triage，有 parents → Todo (不改 Ready) | ~10 |
| `commands.rs` | `handle_edit`: 支持 `{"status":"todo"}` Triage→Todo | ~5 |
| `commands.rs` | `handle_complete`: 不改——仍 Reviewing/Done | 0 |
| `commands.rs` | `handle_archive` (新): Done→Archived | ~15 |

## 11. Kanban Claim 机制分析

### 11.1 机制

kanban 的 claim 是所有权锁——任务被声明后只有声明的 Worker 能操作：

```
Dispatcher tick:
  1. release_stale_claims(): 扫描 claim_expires < now 的 Running 任务
  2. detect_crashed_workers(): 扫描 PID 不存活的任务
  3. promote_ready_tasks(): Todo→Ready (parents done)
  4. atomic_claim(): 声明 Ready 任务 → Running (设 claim_lock=profile + claim_expires=now+15min)

Worker 存活:
  kanban_heartbeat() → 延长 claim_expires ("我还活着")

Worker 僵死:
  PID 不存在 → detect_crashed_workers → reclaim→Ready
  claim_expires 过期 → release_stale_claims → reclaim→Ready
  heartbeat 过期 (>1h) → 即使 PID 存活也 reclaim→Ready
```

### 11.2 a2a_board 差异

a2a 没有进程管理——Worker 是独立 Agent，Gateway 不跟踪 PID。`do_heartbeat` 仅调用 `touch_task` 更新时间戳 + 写入事件记录，不延长任何锁。

### 11.3 可复用部分

`heartbeat` 记录在 `task.updated_at` + `TaskEvent` 已足够做存活判定。Gateway Scheduler 扫到 Running + `updated_at > N hours ago` → 判定僵死。

## 12. Gateway Scheduler — 最小化主动管理

### 12.1 原则

Scheduler 只做现有 notify 事件流**做不到**的事——补漏，不重复。

| 现有事件流已覆盖 | Scheduler 补漏 |
|----------------|--------------|
| complete → notify_review_needed | 审阅者 N 天不回：提醒 reviewer |
| approve → promote_children → notify_assigned | 任务 N 天没心跳：block + 通知 |
| output → Board AwaitingOwner | Owner N 天不确认：提醒 |
| block → notify_blocked | (已覆盖) |
| (被动) | Board Completed N 天未归档：自动归档 |

### 12.2 扫描周期

```
Gateway Scheduler (每 tick)
  ├─ BoardSweeper (每 15 min)
  │    ├─ scan_stale_heartbeats()
  │    │    Running + updated_at > 4h → block(reason="worker silence") + notify_blocked
  │    │
  │    └─ scan_stale_reviews()
  │         Reviewing + status 持续 > 3d → remind reviewer via notify_review_needed
  │
  └─ BoardSweeper (每 24 h)
       ├─ scan_awaiting_owner()
       │    Board AwaitingOwner + > 3d → notify_output(reminder) to verifier
       │
       └─ scan_completed_boards()
            Board Completed + > 30d → auto archive (→ Archived)
```

### 12.3 实现

```rust
// server.rs 或 scheduler 目录新增 board_sweeper.rs
pub async fn run_board_sweeper(
    storage_path: &str,
    email_factory: &EmailFactory,
    attachment_factory: &AttachmentFactory,
) {
    loop {
        tokio::time::sleep(Duration::from_secs(900)).await; // 15 min
        // 1. Stale heartbeats
        let boards = list_active_boards(storage_path);
        for board in boards {
            let tasks = list_tasks(&conn, &board.id, Some("running"), None);
            for task in tasks {
                let elapsed = now - task.updated_at;
                if elapsed > 4 * 3600 {
                    // block task + notify
                }
            }
        }
        // 2. Stale reviews (every 6h)
        if (tick_count % 24 == 0) {
            // scan reviewing tasks + notify
        }
        // Daily: scan AwaitingOwner + auto-archive
    }
}
```

### 12.4 改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/board/sweeper.rs` (新) | ~80 行 | 扫描逻辑 |
| `src/server.rs` | 启动时 spawn sweeper | ~5 行 |

不改现有任何 handler 和 notify。sweeper 独立运行，只读扫描 + 写状态 + 发通知。

### 12.5 与事件流的关系

```
主动事件流 (已有):
  邮件到达 → interceptor → execute_command → notify → 邮件发出

Sweeper (新增/补漏):
  定时扫描 → 发现僵死/超时 → notify → 邮件发出
```

两者永不重叠——Sweeper 只处理**长时间无新事件**的情况。一旦 Agent 有新邮件发来，事件流自然接手。
