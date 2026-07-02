## 澄清事项

### 1. 多项目隔离：一项目一 DB 优于单 DB

| 维度 | 单 DB（project_id 区隔） | 一项目一 DB |
|------|------------------------|------------|
| 锁竞争 | 所有项目共享 SQLite 写锁，并行项目越多越严重 | 项目间无锁竞争 |
| 隔离性 | 一个项目的 schema migration 影响到全体 | 可逐个项目升级 |
| 故障影响 | 一个项目的异常写入可能导致整个 DB 损坏 | 故障隔离在单个项目内 |
| 归档 | DELETE/UPDATE 清理，不可逆 | 移走文件即可，可随时恢复 |
| 跨项目查询 | 易于实现：`WHERE project_id = ...` | 需要打开多个 DB |
| 管理复杂度 | 1 个文件 | N 个文件 |

**结论：一项目一 DB。** A2A 场景下项目间几乎不需要交叉查询，隔离性和归档便利性远重要于跨项目查询。

路径约定：`~/.a2a/projects/<project-id>/kanban.db`

```rust
fn a2a_db_path(project_id: &str) -> PathBuf {
    PathBuf::from(format!("~/.a2a/projects/{}/kanban.db", project_id))
}
```

`project_id` 在 `init` 时指定，所有后续 command 的 `project_id` 参数用于查找对应的 DB 文件。

### 2. 命令可扩展性 — 已解决 ✅

`POST /api/v1/a2a/command` 通用路由 + `role_permissions` 数据驱动表已覆盖。新增 verb 只需 `commands.rs` 加 match arm + handler，不改路由、不改授权机制。

### 3. 自动归档

Rust 侧新增一个轻量级定时器（复用 `core/scheduler`），周期检查：

```rust
// a2a/archiver.rs
pub fn archive_loop(a2a_db_root: &Path) {
    // 遍历 ~/.a2a/projects/*/kanban.db
    // 对每个 DB:
    //   1. 查询 projects 表 where status='active'
    //   2. 检查该项目的 output 任务是否 done 超过 7 天
    //   3. 是 → SET status='archived'
    //   4. 可选：移走到冷存储目录
}
```

归档触发器：

```
项目 output 完成 → Rust 记录 completed_at
                    ↓
定时器（每天一次）：
  → completed_at > 7天前
  → SET status = 'archived'
  → 通知全体成员："项目已归档"
```

已归档项目的 command 请求返回 `403 project archived`。

### 4. API Key Scope

复用 `"agent"` scope。`handle_command` 入口：

```rust
require_scope(&api_key, "agent")?;
```

之后 `authorize()` 查 `project_members` 表做项目级的二次校验。不需要新增 scope。

---

## 补充新问题

### Q1: Verifier 审阅范围

**Verifier 只审阅最终产出物，中间产出物由上下游 Worker 自洽。**

理由：

| 审阅模型 | 优点 | 缺点 |
|---------|------|------|
| **Verifier 审阅每个任务** | 质量最高 | 成为瓶颈。T1 做好等 Verifier 审完 T3 才能开始——串行化 |
| **Verifier 只审最终产出** | 并行度高，T1/T2/T3 可同时进行 | 中间 handoff 质量靠 Worker 自律 |
| **按需审阅（推荐）** | 灵活 | 需要项目配置 |

**推荐方案：按需审阅（`review-model: pipeline` / `final_only`）。**

```
review-model: pipeline（默认）
  → Worker 的 complete(status=review-required) 进入 reviewing 状态
  → 谁审阅？由 task 的 reviewer 字段指定（默认为 Verifier）
  → approve 之后才能 promote

review-model: final_only
  → Worker 的 complete 直接 done，跳过 reviewing 状态
  → promote 直接发生
  → 仅 project output 任务需要 Verifier 审阅
```

**`pipeline` 模式下的审阅者指派：**

每个 task 可以指定 reviewer（默认为项目的 Verifier）。如果项目有多个审阅者，可以通过 `reviewer` 字段分配：

```
task: T1
  assignee: research-a@sys-a
  reviewer: reviewer-arch@sys-a    ← 架构审阅者
task: T2
  assignee: research-b@sys-b
  reviewer: reviewer-db@sys-b      ← 数据库审阅者
task: T4 (project output)
  assignee: synthesizer@sys-c
  reviewer: verifier@hermes.a2a    ← 项目 Verifier 审阅最终输出
```

`commands.rs` 中的审阅者分派逻辑：

```rust
fn handle_complete(&self, cmd: &A2aCommand) -> Result<CommandResult> {
    let task = self.db.get_task(&cmd.task_id)?;
    let needs_review = cmd.param("status") == Some("review-required");

    if needs_review {
        let reviewer = task.reviewer.as_deref()
            .unwrap_or(task.project_verifier);  // 默认为项目 Verifier
        self.db.set_status(&task.id, "reviewing")?;
        self.notify.review_needed(&task, &reviewer)?;
    } else {
        self.db.set_status(&task.id, "done")?;
        self.maybe_promote(&task)?;
    }
    Ok(...)
}
```

数据库扩展：

```sql
ALTER TABLE tasks ADD COLUMN reviewer TEXT REFERENCES project_members(email);
```

### Q2: 通知发送机制

**Rust 侧通知不通过 `core/smtp`，而是通过 `EmailFactory` 插入 `email_records` 表 → 自动进入 SMTP 中继通道。**

```
Rust 侧（A2A interceptor 处理 complete/block/output 后）：
  
  commands::handle_complete()
    → notify::review_needed(task, verifier)
      → EmailFactory::build_and_send(...)  // 构建邮件记录
        → INSERT INTO email_records (...)   // 入 email 表
        → SMTP relay 自动处理发送            // 复用现有出站链路

Python 侧（a2a_board preprocessor 处理 create/arbitrate 后）：

  _handle_create()
    → send_mail(to=worker, subject=...)     // agentmail 工具
      → HTTP POST /api/v1/send              // 调用 Rust API
        → Rust send handler
          → EmailFactory::build_and_send(...)
            → INSERT INTO email_records → SMTP relay
```

**两条路径最终汇合在 `EmailFactory`，享受相同的 SPF/DKIM/relay 处理。**

`a2a/notify.rs` 的实现：

```rust
// a2a/notify.rs — 正确实现
impl A2aNotifier {
    fn review_needed(&self, task: &Task, reviewer: &str) -> Result {
        let email = EmailOutbound {
            to: vec![reviewer.to_string()],
            subject: format!("[A2A] review-needed {}: {}", task.short_id, task.title),
            body: format!(
                "task_id: {}\ncompleted_by: {}\nsummary: {}",
                task.id, task.assignee, task.summary.as_deref().unwrap_or("")
            ),
            // ... 复用 EmailFactory 的邮件构建
        };
        self.email_factory.send_outbound(email)?;
        Ok(())
    }
}
```

---

## 汇总到方案文档的修改

以上 6 项（1 单/多 DB、2 确认、3 归档、4 scope、Q1 审阅范围、Q2 通知机制）需写入 `A2A-SOLUTION.md` 对应章节。
