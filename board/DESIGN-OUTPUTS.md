# A2A Board 指令附件流转与产出物传递方案

## 1. 概述

A2A Board 是多 Agent 邮件协作看板。本方案解决两个核心问题：
- Worker 产出的附件如何传递到下游 Reviewer 和后续 Worker
- 长期运行中如何检测僵死任务、自动提醒和归档

方案覆盖：附件流转、通知规范、Task 状态机、Board 配额。

## 2. 架构

```
Worker SMTP (带附件) → Gateway receiver.rs
  ├─ save_attachment → 文件落地 + attachments_meta + 下载权限
  └─ trigger_tx → Scheduler
                   ↓
A2aInterceptor → execute_command
  ├─ 读 attachments_json → 构造 summary → 写 task.summary
  ├─ create_permission (assignee + reviewer + board 地址)
  └─ notify → create_outbound (attachments = attachments_json)
                   ↓
              mail_count ≥ 2 → 附件受保护
                   ↓
Agent ←── SMTP/Webhook ←── 通知邮件 (含附件)
  ├─ 在线: webhook 自动保存
  └─ 离线: toolset → summary JSON → API download
```

## 3. 数据模型

### Task 字段

```rust
pub summary: String;    // JSON: 产出物描述
```

### summary JSON

与邮件记录的 `attachments_json` 对齐：

```json
{
  "description": "登录 API 完成",
  "artifacts": [
    {"attachment_id":"abc123", "filename":"login_api.rs", "content_type":"text/plain", "size":2048},
    {"filename":"PR #42", "url":"https://github.com/x/pull/42", "type":"url"}
  ]
}
```

## 4. Task 状态机

### 4.1 状态流转

```
Triage → Todo → Ready → Running → Reviewing → Done → Archived
           ↑       ↓         ↕ Blocked      ↕
           └─ promote_children    └─ block/unblock
                                       ↓
                                   Cancelled
```

| 状态 | 进入 | 退出 |
|------|------|------|
| Triage | create 不设 assignee | edit status→todo |
| Todo | create + parents 不满足 | promote_children→Ready |
| Ready | create + parents 满足 / promote | heartbeat→Running |
| Running | heartbeat (assignee 首次) | complete→Reviewing |
| Reviewing | complete (有 reviewer) | approve→Done / reject→Running |
| Done | approve | archive→Archived |
| Blocked | block | unblock→Running |
| Cancelled | cancel | archive→Archived |
| Archived | archive | (终态) |

### 4.2 Heartbeat 规则

| 检查 | 条件 | 不满足 |
|------|------|--------|
| 归属 | sender == assignee | Forbidden |
| 状态 | Ready 或 Running | BadRequest |
| 转移 | Ready → Running | 首次 = 开工 |
| 续存 | Running → updated_at | 仅时间戳 |

只有 assignee 能 heartbeat、Done 后自动拒绝。Sweeper 精确扫描 `Running + updated_at > N`。

## 5. 附件流转

### 5.1 附件通知规则

| 类别 | 动词 | 规则 |
|------|------|------|
| A-传递 | complete, output, comment, create, arbitrate, refresh | 入站附件 → 出站通知携带 |
| B-不传递 | approve, reject, reassign, block, unblock, cancel, edit, deadline, review, reopen | 纯状态变更 |
| C-长期权限 | complete, output | 建 board 地址下载权限 |

### 5.2 保护机制

```
mail_count ≥ 2: notify create_outbound 引用原附件 UUID
perm_count ≥ 1: board 地址下载权限永不过期
30天过期: process_expired_attachments 不删有 perm 的附件
```

### 5.3 传递路径

| 场景 | 路径 |
|------|------|
| 同级 | complete → notify_review_needed (带附件) |
| 父级 | approve → promote_children → notify_assigned (含父级产物) |
| Toolset | board_task_show → summary JSON → API download |
| 外转 | deliver_smtp → load_attachment_data → MIME 附件 |

### 5.4 Agent 获取附件

- 在线：webhook 接收通知邮件 → 附件自动保存
- 离线：board_task_show 拿 uuid → API download (一次性)

### 5.5 父级产出物查询

`show` / `list` 返回 `parent_summaries` 数组。`notify_assigned` 通知含父级 artifact 列表。

## 6. 通知格式

所有 notify 统一 Subject/Body：

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

## 7. Gateway Sweeper

事件流之外的主动补漏。

| 事件 | 频率 | 触发 | 处理 |
|------|:--:|------|------|
| 僵死心跳 | 15min | Running + updated_at > heartbeat_stale | block + notify(assignee+orch) |
| 任务超时 | 6h | Reviewing/AwaitingOwner + 状态持续 > task_timeout | 再次提醒 |
| 自动归档 | 24h | Completed + > task_timeout | Board→Archived + 附件复制 |

僵死心跳后 orchestrator 自行决定：reassign→unblock / unblock→重试 / cancel→终止。

## 8. 并行执行

DAG 通过 `parents` 数组表达。`promote_children` 已支持 fan-out/fan-in。
- 跨 batch parents
- 循环依赖检测 (create 时 DFS)

## 9. Board 归档

Board→Archived 时：
1. 附件从 Gateway 存储复制到 `a2a_board/{bid}/outputs/{tid}/`
2. 删除 board 地址下载权限
3. Board 目录自包含：board.db + outputs/

## 10. 可配置项

```toml
[board]
heartbeat_stale_seconds = 14400   # 僵死心跳 (4h)
task_timeout_seconds = 259200     # 任务超时 (3d)
sweeper_interval_seconds = 900    # 扫描间隔 (15min)

# Advanced only
max_active_boards = 10
archive_retention_days = 365
```

| 参数 | 环境变量 |
|------|---------|
| heartbeat_stale_seconds | AMAILGW_BOARD_HEARTBEAT_STALE_SECONDS |
| task_timeout_seconds | AMAILGW_BOARD_TASK_TIMEOUT_SECONDS |
| sweeper_interval_seconds | AMAILGW_BOARD_SWEEPER_INTERVAL_SECONDS |

## 11. 配额 (Advanced)

Core 预置 trait + 检测点：

```rust
pub trait BoardQuotaChecker {
    fn check_active_boards(&self, system_id: &str) -> AppResult<()>;
}
```

| 检测点 | 位置 |
|--------|------|
| Board 创建 | handle_init |
| 归档清理 | sweeper auto-archive |

Advanced 提供 `AdvancedBoardQuota` 实现，读 `max_active_boards` 和 `archive_retention_days`。

## 12. 实施阶段

| 阶段 | 内容 | 文件 | 行数 |
|------|------|------|:--:|
| **P1** | Task 状态: Triage/Archived, Todo 创建, heartbeat 过滤+Ready→Running | commands.rs | ~40 |
| **P2** | do_complete() + summary 写入 | commands.rs | ~30 |
| **P3** | interceptor 附件: attachments_json→summary, create_permission | interceptor.rs | ~25 |
| **P4** | Notifier 附件字段 + create_outbound | notify.rs | ~10 |
| **P5** | notify_assigned 父级产物 + Body 模板 | notify.rs | ~50 |
| **P6** | show/list parent_summaries + data 字段 | commands.rs + handlers.rs | ~30 |
| **P7** | 跨 batch parents + 循环检测 | commands.rs + db.rs | ~25 |
| **P8** | Gateway Sweeper + BoardConfig | sweeper.rs + config.rs | ~70 |
| **P9** | Board 归档 (附件复制 + 清理) | commands.rs + sweeper.rs | ~30 |
| **P10** | Quota trait + 检测点 (core) | quota.rs | ~15 |
| **P11** | Advanced Quota 实现 | advanced/ | ~35 |
| **P12** | 测试 + 文档 | category-6 + GUIDE | — |

**总计 ~370 行 Core + ~35 行 Advanced。**
