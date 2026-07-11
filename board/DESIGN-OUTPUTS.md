# A2A Board 产出物传递 & 通知规范化方案

## 架构前提

Gateway 和 Agent 不在同一环境：
- **Gateway**：接收 SMTP 邮件、执行 board 命令、转发 webhook
- **Agent (Hermes)**：接收 webhook payload、运行 agentmail toolset、本地文件存储

附件通过**邮件系统**自然传递——不需要 Gateway 另外存储。

```
Worker → SMTP complete (带附件)
         ↓
Gateway → interceptor: 从 payload 取附件名 → 写入 summary JSON
         → do_complete(conn, task_id, sender, summary)
         → webhook 转发完整邮件（含附件内容）给 Agent
         ↓
Agent   → webhook 收到附件 → 保存到本地 outputs/
         → toolset board_task_show 查询 summary（获取 artifact 引用）
```

## 1. 产出物传递

### 1.1 传递方式

| 方式 | 来源 | 谁处理 |
|------|------|--------|
| SMTP 附件 | `complete` 邮件附件 | Gateway：提取文件名写入 summary；Agent：从 webhook 保存文件 |
| URL 引用 | complete JSON body 的 `artifacts[].url` | Gateway：直接写入 summary |
| 混合 | 两者同时 | 各自处理 |

### 1.2 存储（Agent 侧）

```
~/.agentmail/{system_id}/board/{board_id}/
├── board.db (只读——来自 gateway 数据库)
└── outputs/
    └── {task_id}/
        ├── item-0-login_api.rs
        └── item-1-api_doc.md
```

### 1.3 summary JSON 结构

Worker 在 complete 时描述产出物：

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

- `name`、`type` → 从邮件附件或 body JSON 提取
- `path` → Agent 保存附件后填入
- `url` → Worker 在 body 中提供

### 1.4 Gateway 侧：`do_complete()`

**依据**：当前 `handle_complete`（commands.rs L129-146）不接收 summary，直接写状态。

**改动**：提取 `do_complete(conn, task_id, sender, summary_json)` 公共函数——SMTP interceptor 和 Toolset handler 都调它。

**SMTP 入口**（interceptor.rs L367-373）新增逻辑：
```
从 payload 提取:
  - body JSON 中的 artifacts[].url
  - 附件列表中的文件名 → 构造 {name, type: "attachment"}
合并 → 构造 summary JSON
调用 do_complete(...)
```

**Toolset 入口**：当前没有 `board_complete` 写操作工具——暂时不涉及。如需加，同一入口。

### 1.5 Agent 侧：附件保存

Agent 收到 webhook payload 后：
1. 解析 `payload["attachments"]` 数组
2. 如果是 complete 通知 → 保存到 `outputs/{task_id}/item-{idx}-{name}`
3. 更新 path 到本地缓存（可选——`board_task_show` 已返回 summary JSON 中的路径）

## 2. 父级产出物传递

**现状**：`promote_children`（commands.rs L695-714）只做状态提升（Todo→Ready），不传递父级数据。`notify_assigned`（notify.rs L12-22）不含父级上下文。

**目标**：子任务被 promote 时，通知携带父级产出物的文件名和 URL。

### 2.1 notify_assigned 参数扩展

`notify.rs` 当前的 `notify_assigned(&self, task)` 只取 task 自身字段。增加 `parent_summaries: Option<&[(String, String, String)]>` 参数（父级 short_id、title、artifact 引用行）。

### 2.2 promote_children 调用点

commands.rs L697-709 调 `notify_assigned` 时查父级 summaries 并传入。

### 2.3 show 返回 parent_summaries

`handle_show`（L388-391）返回的 `CommandResponse.data` 附加父级摘要数组。

`handle_get_task`（handlers.rs L89-101）同样附加。

## 3. 通知格式规范

**现状**：notify.rs 11 个函数各自拼写 Subject/Body，英文中文混用。

**目标**：统一模板。

### 3.1 Subject

```
[A2A] {event-type} {short_id}: {title}
```

### 3.2 Body

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

各事件字段基于现有 notify.rs 参数映射，不新增数据来源。

## 4. 并行执行模式

**现状**：
- `parent_ids: Vec<String>` — fan-in 已支持
- `promote_children` L701-705 — 所有 parent Done 才 promote
- 多个 task 引用同一 parent — fan-out 已支持
- `create` 限制 parents 在同 batch — 唯一约束

**目标**：DAG 靠 `parents` 数组完全表达。需改动：

| 需求 | 依据 | 改动 |
|------|------|------|
| 跨 batch parents | handle_create L489-490 父级校验只遍历当前 batch | 去掉同 batch 限制 |
| 循环依赖检测 | create 时 DFS 检查 parents 无环 | db.rs ~20 行 |

其余 fan-out/fan-in/混合模式无需改代码。

### Worker 多任务

收到多个 `assigned` 通知时按邮件顺序处理。`list` + assignee 过滤（API 已有，SMTP `list` params 已有）自行管理优先级。无需改动。

## 5. 实施分阶段

| 阶段 | 内容 | 文件 | 行数 |
|------|------|------|:--:|
| **P1** | `do_complete()` + summary 参数 | `commands.rs` | ~30 |
| **P2** | interceptor 附件名提取 + summary 构造 | `interceptor.rs` | ~30 |
| **P3** | `notify_assigned` 含父级产物 | `notify.rs` + `commands.rs` | ~25 |
| **P4** | `show`/`list` 返回 parent_summaries | `commands.rs` + `handlers.rs` | ~35 |
| **P5** | 跨 batch parents | `commands.rs` | ~5 |
| **P6** | 循环依赖检测 | `db.rs` | ~20 |
| **P7** | 通知 Body 规范化 | `notify.rs` | ~80 |
| **P8** | 测试 + 文档 | `category-6` + GUIDE | |
