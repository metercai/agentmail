# [WHOAMI] 通用身份问询 — 设计方案 v4

---

## 1. 核心原则

**安全优先，入口标记，统一拦截。**

- SMTP receiver 和 send API 入口处**不做放开**，而是**检测 + 标记**
- 标记通过 headers 传递，后续 interceptor 统一处理
- 所有流入邮件（SMTP 入站 + send API 出站内转）经过同一个 interceptor 链
- 自动回复通过创建 EmailRecord → scheduler → webhook 或 SMTP，不走旁路

---

## 2. 处理流程

```
Entry Points                          Interceptor Chain
────────────                          ─────────────────

SMTP 入站 ─┐
           │
send API ──┤ (内转 inbound 方向)
           │
           ├─ 1. 检测 sender 是否在白名单
           │     ├─ NO  → 标记: X-Mail-Stranger: true
           │     └─ YES → 不标记
           │
           ├─ 2. 检测 subject 是否通用指令
           │     ├─ [WHOAMI] → 标记: X-Mail-Command: whoami
           │     ├─ [VERIFY]  → 标记: X-Mail-Command: verify  (预留)
           │     └─ 其他     → 不标记
           │
           ├─ 3. 创建 EmailRecord（含标记 headers）
           │
           ▼
    scheduler → webhook delivery (内转)
           │
           ▼
    interceptor 链
           │
    ┌──────┴──────┐
    │ A2aInterceptor (p=20)
    │ WhoamiInterceptor (p=5)
    │ ... 其他 interceptors
    └─────────────┘
           │
    WhoamiInterceptor::intercept()
           │
    ├─ subject 非 [WHOAMI] → PassThrough
    │
    ├─ sender 在白名单 → PassThrough (已知联系人，走 LLM)
    │
    └─ sender 不在白名单 (stranger)
         │
         ├─ 读取 agent_state["public_whoami"]
         ├─ 构造 outbound 自动回复 (EmailRecord)
         │     └─ create_outbound(from=recipient, to=sender, body=public_whoami)
         └─ Handled (不再触发 LLM)
```

---

## 3. 标记 headers 格式

```
X-Mail-Stranger: true                     # sender 不在任何白名单中
X-Mail-Command:  whoami                   # 通用指令类型
```

**扩展性：** 未来 `X-Mail-Command: verify` 或 `help` 等指令只需增加标记类型，interceptor 中增加对应处理分支。

---

## 4. 入口层检测

### 4.1 SMTP receiver (`src/core/smtp/receiver.rs`)

```rust
fn data(&mut self, data: &[u8]) -> Response {
    // ... 现有逻辑 ...

    // 陌生人检测：sender 不在收件人的 from-whitelist 中
    let is_stranger = !self.is_from_whitelisted(&sender, &recipient);

    // 通用指令检测
    let command = detect_stranger_command(&subject);  // [WHOAMI], [VERIFY], ...

    if is_stranger && command.is_some() {
        // 注入标记 headers，放行邮件
        self.message_headers.push(("X-Mail-Stranger", "true"));
        self.message_headers.push(("X-Mail-Command", &command.unwrap()));
    } else if is_stranger {
        // 非通用指令 + 陌生人 → 按现有规则拒绝
        return perm_fail("Sender not whitelisted");
    }
    // 继续正常流程
}
```

### 4.2 send API (`src/core/api/send.rs`)

```rust
pub async fn send_email(...) -> ... {
    // ... 现有逻辑 ...

    // 出站内转时检测（direction = inbound, delivery_type = webhook）
    // sender 不在收件人白名单 → mark as stranger
    // subject 是通用指令 → mark command type
    // 注入 merged_headers 中的 X-Mail-Stranger / X-Mail-Command
}
```

---

## 5. Interceptor 层

### WhoamiInterceptor (`src/core/interceptor/whoami.rs`)

```rust
impl InboundInterceptor for WhoamiInterceptor {
    fn name(&self) -> &str { "WhoamiInterceptor" }
    fn priority(&self) -> u32 { 5 }

    async fn intercept(&self, record, payload) -> Decision {
        let headers = payload["headers"].as_object();
        let is_stranger = header_eq(headers, "x-mail-stranger", "true");
        let command = header_str(headers, "x-mail-command");

        // 只处理 stranger 通用指令
        if !is_stranger || command != Some("whoami") {
            return PassThrough;
        }

        // 读取 public_whoami
        let body = match get_agent_state("public_whoami") {
            Some(v) => v,
            None => "Agent not configured yet. Please try again later.".into(),
        };

        // 自动回复：sender ← recipient
        let reply_to = payload["from"].as_str();
        let reply_from = payload["to"][0].as_str();
        self.create_auto_reply(reply_from, reply_to, "Re: [WHOAMI]", &body).await;

        Handled  // 不穿透 LLM
    }
}
```

---

## 6. 自动回复路径

```
WhoamiInterceptor::create_auto_reply()
  │
  └─ EmailFactory::create_outbound(from, to, subject, body, headers)
       │
       ▼
  EmailRecord (direction=outbound, delivery_type=webhook or smtp)
       │
       ▼
  scheduler → deliver_webhook() or deliver_smtp()
```

正常走 outbound 通道，不旁路。

---

## 7. 已知联系人 [WHOAMI]

sender 在白名单 → WhoamiInterceptor PassThrough → 现有流程不变：

```
webhook → Python preprocessor → [WHOAMI] 检测 → _whoami_prompt → LLM
```

LLM 处理后，通过 `add_conversation_turn` 钩子 → 回写 `agent_state["public_whoami"]`。

---

## 8. public_whoami 生成

| 时机 | 触发 |
|------|------|
| Agent 启动 | Hermes 加载时调用 `set_agent_state("public_whoami", ...)` |
| 联系人 [WHOAMI] | LLM 处理完 → `add_conversation_turn` 钩子回写 |

---

## 9. 代码变更清单

| 文件 | 变更 |
|------|------|
| `src/core/smtp/receiver.rs` | 陌生人 + 通用指令检测，注入 X-Mail-* headers |
| `src/core/api/send.rs` | 出站内转方向：陌生人 + 通用指令检测，注入 headers |
| `src/core/interceptor/whoami.rs` | **新增** WhoamiInterceptor (p=5) |
| `src/core/storage.rs` | get/set agent_state API |
| `src/server.rs` | 注册 WhoamiInterceptor |
| `agentmail_tools.py` | `add_conversation_turn` 钩子回写 public_whoami |
| `agentmail/lib/` | 启动时 set_agent_state("public_whoami") |
