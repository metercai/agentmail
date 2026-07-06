# [WHOAMI] 通用身份问询 — 设计方案 v5

---

## 1. 入口层：精确放行

```
SMTP 入站 / send API 出站内转
  │
  ├─ sender 在白名单？ → 正常邮件，不标记
  │
  ├─ sender 不在白名单 + subject 非通用指令
  │     → 拒绝（与现有逻辑一致）
  │
  └─ sender 不在白名单 + subject 是通用指令
        → 注入 headers，放行
          X-Mail-Stranger: true
          X-Mail-Command:  whoami   (或 verify / help ...)
```

**只有**携带识别出的通用指令的陌生人才放行。其他陌生人邮件按现有规则拒绝。安全边界清晰：白名单是"正常门"，指令则是陌生人的"临时准入令牌"。

---

## 2. Interceptor 层：StrangerInterceptor

```
interceptor 链
  │
  ├─ A2aInterceptor (p=20)
  │
  ├─ StrangerInterceptor (p=5)          ← 新增
  │     │
  │     ├─ 读取 payload["headers"]["X-Mail-Stranger"]
  │     │      ≠ "true" → PassThrough
  │     │
  │     ├─ 读取 payload["headers"]["X-Mail-Command"]
  │     │      ├─ "whoami"  → handle_whoami()
  │     │      ├─ "verify"  → handle_verify()   (预留)
  │     │      ├─ "help"    → handle_help()     (预留)
  │     │      └─ 其他      → PassThrough
  │     └─ Handled
  │
  └─ ... 其他 interceptors
```

**StrangerInterceptor 不重新查白名单。** 是否陌生人由入口层在 header 中标记。Interceptor 只读 header，信任入口判定。

---

## 3. handle_whoami() 内部逻辑

```rust
fn handle_whoami(&self, payload: &Value) -> Decision {
    let sender   = payload["from"].as_str();    // 陌生人
    let rcpt     = payload["to"][0].as_str();   // 收件人（即本 Agent）

    // 读 public_whoami
    let body = get_agent_state("public_whoami")
        .unwrap_or("Agent not configured yet.");

    // 通过正常 outbound 路径发送自动回复
    let reply_subject = format!("Re: {}", payload["subject"]);
    self.create_auto_reply(rcpt, sender, &reply_subject, &body);

    Handled  // 不穿透 LLM
}
```

---

## 4. 已知联系人 [WHOAMI]

白名单内的联系人 [WHOAMI] 与现有流程一致：

- 入口层不标记（非陌生人）
- StrangerInterceptor PassThrough
- webhook → Python preprocessor → `_whoami_prompt` → LLM
- LLM 处理后回写 `agent_state["public_whoami"]`

---

## 5. 扩展性

新增陌生人的通用指令只需两处：

1. 入口层：`detect_stranger_command()` 中新增匹配
2. StrangerInterceptor：新增 `handle_xxx()` 分支

---

## 6. 代码变更

| 文件 | 变更 |
|------|------|
| `src/core/smtp/receiver.rs` | 陌生人 + 指令检测，注入 `X-Mail-Stranger` / `X-Mail-Command` |
| `src/core/api/send.rs` | 出站内转方向：同上标记逻辑 |
| `src/core/interceptor/stranger.rs` | **新增** StrangerInterceptor (p=5) |
| `src/core/storage.rs` | get/set_agent_state() |
| `src/server.rs` | 注册 StrangerInterceptor |
| `agentmail_tools.py` | LLM 处理后回写 public_whoami |
