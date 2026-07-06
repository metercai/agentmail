# [WHOAMI] 通用身份问询 — 设计方案 v3

---

## 1. 执行阶段澄清

**interceptor 运行在 webhook 投递阶段，不在 SMTP 入站阶段：**

```
SMTP receiver (收邮件，写 EmailRecord)
        │
        ▼
   scheduler 调度
        │
        ├─ webhook delivery → interceptor 链 → Python preprocessor
        └─ SMTP relay (外投)
```

陌生人 [WHOAMI] 不应走到 webhook 阶段——应在 **SMTP receiver 层闭环**。

---

## 2. 陌生人 [WHOAMI] 处理（SMTP receiver 层闭环）

```
SMTP session
  │
  ├─ rcpt() ← 收件人在本地 ✓
  │
  ├─ mail_from() 
  │   ├─ sender 在白名单 → known = true
  │   └─ sender 不在白名单 → known = false → 标记为 stranger
  │
  ├─ data() ← 收到完整邮件体
  │   │
  │   ├─ 检查 subject
  │   │   ├─ 以 [WHOAMI] 开头，stranger = true
  │   │   │   ├─ 查 agent_state["public_whoami"]
  │   │   │   │   ├─ 存在 → 构造 SMTP 自动回复 → ok()
  │   │   │   │   └─ 不存在 → "Agent not configured yet" → ok()
  │   │   │   └─ 不写 EmailRecord，不穿透 LLM
  │   │   │
  │   │   ├─ 其他通用指令（[VERIFY], [HELP]...）→ 预留扩展点
  │   │   │
  │   │   └─ 非通用指令 + stranger → 按现有 whitelist 规则拒绝
  │   │
  │   └─ 非 [WHOAMI] + known → 正常创建 EmailRecord
  │
  └─ 正常流程
```

**关键点：** 陌生人 [WHOAMI] 在 SMTP receiver 的 `data()` 阶段直接处理并返回，不创建 EmailRecord，不到达 scheduler/interceptor/webhook/Python 任何后续环节。

---

## 3. 入站/出站统一

陌生人检测统一在**入站侧**的 SMTP receiver 处理：

```
出站 send API (Agent A)               入站 SMTP (Agent B 的 gateway)
─────────────────────               ─────────────────────────────
  创建 EmailRecord                      接收 SMTP 连接
  → scheduler 投递                      → rcpt() ✓
  → SMTP relay → Agent B's gateway      → mail_from() 判断 stranger
                                        → data() 检测 [WHOAMI]
                                        → SMTP 自动回复 public_whoami
```

无论邮件来自 send API 还是外部 SMTP，到达 Agent B 的 gateway 时都经过同一个 SMTP receiver。**陌生人检测只需在 SMTP receiver 一处实现。**

---

## 4. 已知联系人 [WHOAMI]（现有流程不变）

```
SMTP receiver → 创建 EmailRecord → scheduler webhook →
interceptor → Python preprocessor → [WHOAMI] 检测 →
_whoami_prompt 注入 → LLM 生成回复 → 顺便更新 agent_state["public_whoami"]
```

---

## 5. public_whoami 生成时机

| 时机 | 触发 | 实现 |
|------|------|------|
| Agent 启动 | Hermes profile 加载 | Agent 调用 set_agent_state("public_whoami", ...) |
| 联系人 [WHOAMI] | LLM 处理后 | add_conversation_turn 钩子 → 回写 agent_state |

无定时刷新。

---

## 6. 陌生人回复模板

```
Subject: Re: [WHOAMI]
Body:
  Role: {role}
  Available tools: {tools_list}
  Version: agentmail/1.0
  Contact: Send email to verify your identity for full access.
```

- 不含邮箱地址、真实姓名
- 不含 board_id
- 引导对方完成身份验证

---

## 7. 陌生人分支扩展性

```rust
// src/core/smtp/receiver.rs
fn handle_stranger_command(&self, cmd: &str, sender: &str, rcpt: &str, body: &str) -> Response {
    match cmd.to_uppercase().as_str() {
        "[WHOAMI]" => self.reply_public_whoami(sender, rcpt),
        // 预留:
        // "[VERIFY]" => self.handle_stranger_verify(sender, rcpt, body),
        // "[HELP]"   => self.reply_help(sender, rcpt),
        _ => Ok(())
    }
}
```

---

## 8. 代码变更清单

| 文件 | 变更 |
|------|------|
| `src/core/smtp/receiver.rs` | 新增 `handle_stranger_command()`，检测 [WHOAMI] + 自动回复 |
| `src/core/storage.rs` | 新增 `get_agent_state()` / `set_agent_state()` 公共 API |
| `agentmail_tools.py` | 新增 `set_agent_state()` tool；联系人 [WHOAMI] 后回写 |
| `agentmail_tools.py` | 添加 `add_conversation_turn` 钩子，在 LLM 处理后更新 public_whoami |
| `agentmail/lib/` | 安装脚本在启动时调用 set_agent_state 初始化 public_whoami |
