# 方案验证：Postgres 迁移项目 — 全链路追踪

## 场景：Worker 完成任务 → Verifier 审阅放行 → promote 下游

```
T1(成本分析)         T2(性能评估)         ← Worker 并行完成
    ↘                  ↙
      T3(综合推荐)    ← T1+T2 全 done 后 promote
         ↙
      T4(决策备忘录)  ← T3 done 后 promote，Verifier 最终输出
```

---

## 第 1 步：Orchestrator 创建任务

### 流程

```
Orchestrator agent → 发送邮件
  To: board@postgres-mig.a2a
  Subject: [A2A] create

  Body:
    tasks:
      - task_id: T1    ← Orchestrator 指定简短标识
        title: 成本分析
        assignee: research-a@sys-a.a2a
        body: 比较 AWS、GCP、自建 Postgres 3 年成本
      - task_id: T2
        title: 性能评估
        assignee: research-b@sys-b.a2a
        body: ...
      - task_id: T3
        title: 综合推荐
        assignee: synthesizer@sys-c.a2a
        parents: [T1, T2]
      - task_id: T4
        title: 决策备忘录
        assignee: verifier@hermes.a2a
        parents: [T3]
```

### Rust 侧

```rust
// A2aInterceptor.intercept()
// verb=create → is_simple()=false → return PassThrough
// 不放任何标记，只是放行

// 邮件正常进入 bridge → Python webhook
```

### Python 侧

```python
# a2a_board preprocessor
# 检测 [A2A] create
# 调用 PUT /api/v1/a2a/create
```

### 缺失检测

**✅ 已覆盖。** 但是：

**⚠ 缺失：`PUT /api/v1/a2a/create` 的请求体中，`task_id` 需要由 Orchestrator 指定还是由 Rust 自动生成？**

如果是 Rust 自动生成（如 `t_a1b2c3d4`），Orchestrator 无法在 `parents` 中引用 T1、T2。方案：Orchestrator 指定简短名（T1、T2...），Rust 在 DB 中存储时映射为内部 ID（`t_a1b2c3d4`），但保留 short_id 用于 `parents` 引用。

---

## 第 2 步：Rust 处理 create

### 数据库操作

```sql
-- 原子性：在事务中创建 4 个 task
BEGIN;
INSERT INTO tasks (short_id, id, title, assignee, status, body)
VALUES ('T1', 't_a1b2', '成本分析', 'research-a@sys-a.a2a', 'ready', '...');
INSERT INTO tasks (short_id, id, title, assignee, status, body)
VALUES ('T2', 't_c3d4', '性能评估', 'research-b@sys-b.a2a', 'ready', '...');
-- T3: parents referenced by short_id, resolved to t_a1b2 + t_c3d4
INSERT INTO tasks (short_id, id, title, assignee, status, body, parent_ids)
VALUES ('T3', 't_e5f6', '综合推荐', 'synthesizer@sys-c.a2a', 'todo',  '...',
        '["t_a1b2","t_c3d4"]');
INSERT INTO tasks (short_id, id, title, assignee, status, body, parent_ids)
VALUES ('T4', 't_g7h8', '决策备忘录', 'verifier@hermes.a2a', 'todo',
        '...', '["t_e5f6"]');
COMMIT;
```

### 响应

```json
HTTP 200
{
  "tasks": {
    "T1": { "task_id": "t_a1b2", "status": "ready" },
    "T2": { "task_id": "t_c3d4", "status": "ready" },
    "T3": { "task_id": "t_e5f6", "status": "todo" },
    "T4": { "task_id": "t_g7h8", "status": "todo" }
  }
}
```

### Python preprocessor 发送分配通知

```python
# 对每个 status=ready 的任务，发送分配邮件
for task_id, task_info in result["tasks"].items():
    if task_info["status"] == "ready":
        send_mail(
            to=assignee_email,
            subject=f"[A2A] assigned {task_id}: 成本分析",
            body=f"任务描述...",
        )
```

### 缺失检测

**⚠ 缺失：`project_members` 表。**

create 操作需要校验 assignee 是不是项目成员。当前方案没有定义此表。

需新增 `a2a/models.rs` 中的结构：

```rust
struct ProjectMember {
    email: String,    // research-a@sys-a.a2a
    role: String,     // worker / orchestrator / verifier / human
}
```

和 `a2a/db.rs` 中的表：

```sql
CREATE TABLE project_members (
    email TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK(role IN ('orchestrator','verifier','worker','human')),
    project_id TEXT NOT NULL
);
```

---

## 第 3 步：Worker research-a 执行 T1

### Worker agent 收到分配邮件

```
From: board@postgres-mig.a2a
Subject: [A2A] assigned T1: 成本分析
Body:
  task_id: t_a1b2
  标题: 成本分析
  描述: 比较 AWS、GCP、自建 Postgres 3 年成本
```

Worker 的 a2a-worker SKILL 指导它：执行任务 → 完成后发 `[A2A] complete`。

### Worker 发送完成

```
Subject: [A2A] complete T1
Body:
  action: complete
  task_id: T1
  status: review-required

  AWS Aurora 成本最优，月均 $10k-$15k。
  详细数据见附件。

  ---metadata
  monthly_cost_low: 10000
  monthly_cost_high: 15000
  winner: AWS Aurora
```

---

## 第 4 步：Rust 拦截 complete（闭环）

### A2aInterceptor

```rust
// verb=complete, is_simple()=true
// 在 webhook 投递前执行：

async fn intercept(&self, payload: &Value) -> A2aDecision {
    let cmd = parse_command(payload)?;

    // 1. 验证任务存在且 assignee 匹配
    let task = self.db.get_task(cmd.task_id)?;
    if task.assignee != cmd.sender {
        self.smtp.send_error(cmd.sender, "not your task");
        return A2aDecision::Handled;
    }

    // 2. 更新状态
    let summary = parse_summary(cmd);
    let metadata = parse_metadata(cmd);
    let needs_review = cmd.params.get("status") == "review-required";

    let new_status = if needs_review { "reviewing" } else { "done" };
    self.db.complete_task(cmd.task_id, new_status, summary, metadata)?;

    // 3. 触发 promote（如果不需要 review 的情况下检查 parent）
    if !needs_review {
        let promoted = self.db.promote_children(cmd.task_id)?;
        for child in promoted {
            self.notify.assigned(&child)?;   // SMTP通知
        }
    }

    // 4. 发通知
    if needs_review {
        self.notify.review_needed(cmd.task_id, &task)?;
    }
    self.notify.status_changed(cmd.task_id, &task)?;

    // 5. 回复 Worker 确认
    self.smtp.reply(cmd.sender, cmd.message_id,
        &format!("T1 completed, status={}", new_status))?;

    A2aDecision::Handled
}
```

### 缺失检测

**⚠ 缺失：`status=reviewing` 状态。** 当前 models.rs 的 TaskStatus 需要包含此状态：

```rust
enum TaskStatus {
    Todo,
    Ready,
    Running,
    Reviewing,     // ← 新增：已提交等待 Verifier 审阅
    Done,          // ← 已审阅通过
    Blocked,
}
```

**⚠ 缺失：`promote_children()` 需要同时检查 sibling 状态。**

```rust
fn promote_children(&self, parent_id: &str) -> Result<Vec<Task>> {
    let children = self.db.get_children_waiting_for(parent_id)?;
    let mut promoted = vec![];
    for child in children {
        // 所有 parent 必须 status=done（审阅通过），不是已完成未审阅
        if self.db.all_parents_done(&child)? {
            self.db.set_status(&child.id, "ready");
            promoted.push(child);
        }
    }
    Ok(promoted)
}
```

**✅ assignee 校验已覆盖。** Rust 从 payload 中读取 sender email，与 task.assignee 比较。

---

## 第 5 步：Verifier 审阅 T1

### Verifier 收到的通知

```
From: board@postgres-mig.a2a
Subject: [A2A] review-needed T1: 成本分析
Body:
  task_id: t_a1b2
  已完成: research-a@sys-a.a2a
  summary: AWS Aurora $10k-$15k/月

  ---handoff
  monthly_cost_low: 10000
  monthly_cost_high: 15000
```

### Verifier 批准

```
Subject: [A2A] complete T1
Body:
  action: complete
  task_id: T1

  数据完整，成本分析合理，放行。
```

### Rust 再次拦截 complete

```rust
// verb=complete, task=T1
// 当前 status=reviewing，不是第一次 review

self.db.complete_task("t_a1b2", "done", ...)?;

// status=done，执行 promote
// T1 done + T2 not yet complete → 不 promote T3
// 仅通知线程
self.notify.status_changed("T1", "done")?;
```

### 缺失检测

**⚠ 缺失：complete 需要区分"Worker 首次提交"和"Verifier 审阅通过"。**

Rust commands.rs 需要根据当前 task 状态做不同处理：

| 当前状态 | 收到 complete | 动作 |
|---------|-------------|------|
| running | Worker 提交 | → reviewing，发通知 |
| reviewing | Verifier 批准 | → done，promote children |
| running | Verifier 批准 | （无意义，忽略或 error） |

---

## 第 6 步：T2 也完成，promote T3

### 类似 T1 的完整流程

```
Worker research-b 完成 T2 → Rust 闭环
  → status = reviewing
  → 通知 Verifier 审阅
  → Verifier 批准 → status = done
  → promote_children("t_c3d4")
    → 检查 T3 的所有 parent
    → t_a1b2: done ✓
    → t_c3d4: done ✓
    → T3 status = todo → ready
    → 返回 promoted = [T3]
```

### Rust notify 发送

```rust
// promote 返回 T3 后
self.notify.assigned(&t3)?;
// SMTP: To synthesizer@sys-c.a2a
// Subject: [A2A] assigned T3: 综合推荐
// Body: T1(T2 已完成审阅，开始综合推荐。)
```

### 缺失检测

**✅ 已覆盖。**

---

## 第 7 步：T3 完成、T4 完成、最终输出

类似流程。最终：

### Verifier 发送 output

```
Subject: [A2A] output T4
Body:
  action: output
  task_id: T4

  最终报告已完成。
  推荐：采用 AWS Aurora Postgres
  迁移周期：6-8 周
  预估成本：$10k-$15k/月
```

### Rust 处理 output

```rust
// verb=output → is_simple()? 
// output 不需要 LLM，是纯状态操作 + 通知全员。
// 可以 Rust 闭环。

// 1. 验证 sender 是 verifier（查 project_members）
// 2. status = done + 标记为 project_output
// 3. 通知全体项目成员：项目完成 + 最终输出
```

### 缺失检测

**✅ `output` 可以 Rust 闭环，不需要走 Python。**

之前认为 output 需要 LLM 判断验收标准，但实际上验收发生在 Verifier 发 `output` 邮件前的审阅过程中。output 命令本身只是一个"发布最终结果"的纯操作。可以改为 Rust 闭环。

---

## 第 8 步：Arbitrate 仲裁

### Orchestrator 发现矛盾

```
Subject: [A2A] arbitrate
Body:
  action: arbitrate
  task_id: T1
  争议: AWS Aurora 中国区不可用
  选项1: 接受海外区部署
  选项2: 改用阿里云 PolarDB
```

### Rust Interceptor

```rust
// verb=arbitrate → is_simple()=false
// 不处理，放行到 Python
return A2aDecision::PassThrough;
```

### Python preprocessor 处理

```python
# a2a_board preprocessor
# 1. 调用 PUT /api/v1/a2a/arbitrate → Rust 记录仲裁请求
# 2. send_mail() 发给 Human Admin
#    To: admin@company.com
#    Subject: [A2A] arbitrate: 需要裁决
#    Body: (转发争议内容)
# 3. 标记 _a2a_board_handled → 跳过 LLM session
```

### Human Admin 回复

```
From: admin@company.com
To: board@postgres-mig.a2a
Subject: Re: [A2A] arbitrate: 需要裁决
Body: 先按选项2评估阿里云 PolarDB，并行做海外区成本对比。
```

### 缺失检测

**⚠ 缺失：Admin 的回复不是 [A2A] 前缀，是普通邮件回复。Board agent 需要识别这是仲裁回复然后执行 unblock。**

Board agent 收到这封邮件后，它的 SKILL 需要：
1. 通过邮件 thread（In-Reply-To / References）关联到原始 arbitrate 请求
2. 理解 Admin 的决策
3. 执行 `[A2A] unblock T1` 或创建新的任务

这需要 Board agent 的 LLM 来处理。但 Board agent 现在设计为"被动服务"，LLM 会话只用于非 [A2A] 对话。Admin 的仲裁回复符合"非 [A2A] 对话"，所以会进入 Board 的 LLM session。OK。

但 Board agent 的 SKILL 需要明确指出这个行为模式：

```
Board SKILL:
  - 收到邮件线程的回复
  - 如果该线程的原始邮件是 [A2A] arbitrate
  - 则提取决策内容 → 调用 A2A API unblock/complete
```

**⚠ 缺失：Board agent 需要能调用 A2A API。**

Board agent 目前只有 agentmail 工具（send_mail 等）。它还需要能调用 Rust 的 A2A REST API。实现方式：

1. 给 Board agent 的 Hermes profile 添加一个自定义工具 `a2a_api_call()`
2. 或者在 a2a_board preprocessor 中处理——但 preprocessor 只处理 inbound，不处理 agent 发出的命令

**方案：Board agent 的 SKILL 指导它用 send_mail 发 [A2A] 命令邮件到 Board 自身地址。** 这封邮件会再次进入 Rust 侧被 interceptor 处理。

```
Board agent ↔ send_mail("[A2A] unblock T1") → Rust interceptor → kanban 操作

这个设计让 Board agent 不需要特殊 API 工具，只需要 agentmail 标准工具。
```

但这是异步的——Board agent 发邮件，邮件回到 Rust 处理，然后才有结果。对于简单操作（如 unblock），用 REST API 更直接。

**结论：Board agent 需要新增一个 `a2a_exec` 工具**（HTTP 客户端），或复用 `_GatewayClient` 的能力。

---

## 发现的缺失完整清单

| # | 缺失 | 影响 | 修复 |
|---|------|------|------|
| 1 | `project_members` 表 | create 无法验证 assignee、notify 不知道通知谁 | 新增表 + PUT /api/v1/a2a/init 时写入 |
| 2 | `reviewing` 状态 | complete 后无法区分"已提交待审"和"审阅通过" | TaskStatus 增加 Reviewing 变体 |
| 3 | `promote_children()` 仅检查完成，不检查审阅状态 | 未审阅的 handoff 流入下游任务 | promote 只 promote status=done 的 parent |
| 4 | complete 状态机不完善 | running→reviewing→done 的流转不明确 | commands.rs 增加状态转换校验 |
| 5 | `output` 可 Rust 闭环 | 原设计走 Python，实际不需要 LLM | 改为简单命令，Rust 拦截 |
| 6 | Admin 仲裁回复的关联机制 | 非 [A2A] 邮件需要被 Board agent 识别为仲裁回复 | Board SKILL 加上线程关联逻辑 |
| 7 | Board agent 缺少 A2A API 调用能力 | Board agent 无法直接 unblock | 新增 `a2a_exec` 工具或 `_GatewayClient` 复用 |
| 8 | create 请求中 task_id 的引用解析 | Orchestrator 指定短名(T1)，DB 用内部ID(t_a1b2) | short_id 字段 + parents 按 short_id 或 id 引用 |
