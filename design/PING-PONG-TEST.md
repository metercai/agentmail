# amail Ping-Pong End-to-End Test — 设计方案

## 一、概述

在 amail 全链路中注入一个受控的测试邮件（ping），走完整条链路后在末端截获并返回（pong），
通过日志验证每个环节是否正常。不调用 LLM，不产生外部邮件，不影响业务数据。

## 二、架构图谱

```
┌─────────────────────────────────────────────────────────────────────┐
│  check_status --ping                                                │
│    SMTP 发 ping                         读 amail.log → 验证 ✅     │
└──────────────────┬──────────────────────────────────────┬───────────┘
                   │ subject="__amail_ping__:{uuid}"        │
                   ▼                                        │
┌─────────────────────────────────────┐                     │
│ ❶ amail-gateway (SMTP receiver)    │                     │
│  ├─ MAIL FROM:{b64_key}={mgr}@auth │ 日志: mailfrom      │
│  ├─ RCPT TO: agent_email           │ 日志: rcpt_to       │
│  ├─ 反循环保护: OK (sender=qq.com) │                     │
│  └─ create_inbound() + trigger_tx  │ 日志: email_received│
└──────────────────┬──────────────────┘                     │
                   ▼                                       │
┌─────────────────────────────────────┐                     │
│ ❷ amail-bridge (pull → push)       │                     │
│  ├─ POST /api/v1/admin/pending     │ 日志: bridge 侧     │
│  └─ POST /webhooks/amail-inbound   │                     │
└──────────────────┬──────────────────┘                     │
                   ▼                                       │
┌──────────────────────────────────────────────────────┐    │
│ ❸ Hermes webhook.py — 拦截点A (asyncio.create_task前) │    │
│                                                       │    │
│  if subject.startswith("__amail_ping__:"):            │    │
│    ├─ send_mail() HTTP API → gateway 出站             │    │
│    │  from=agent_email                                │    │
│    │  to=manager_email                                │    │
│    │  subject="__amail_pong__:{uuid}"                 │    │
│    │  body=event_json (含 prompt+skill 渲染结果)       │    │
│    ├─ 写 amail.log: dir=ping_intercepted              │    │
│    └─ 返回 HTTP 200, 不调 agent                       │    │
│                                                       │    │
│  if subject.startswith("__amail_pong__:"):            │    │
│    ├─ 写 amail.log: dir=pong_returned                 │    │
│    └─ 返回 HTTP 200, 不调 agent                       │    │
└──────────────────┬────────────────────────────────────┘    │
                   │                                         │
                   ▼                                         │
┌─────────────────────────────────────┐                      │
│ ❹ amail-gateway API → 创建出站记录  │                      │
│    scheduler → SmtpRelay.send_email │                      │
└──────────────────┬──────────────────┘                      │
                   ▼                                         │
┌──────────────────────────────────────────┐                 │
│ ❺ SmtpRelay — 拦截点B (sender.rs)        │                 │
│                                           │                 │
│  if subject=="__amail_pong__:{uuid}" &&   │                 │
│     recipients 被 loopback 过滤 → 空:     │                 │
│                                           │                 │
│    ├─ email_factory.create_inbound()      │                 │
│    │  互换 from/to → 新入站邮件           │                 │
│    │  from=新收件人, to=原始发件人         │                 │
│    │  subject="__amail_pong__:{uuid}"     │                 │
│    ├─ trigger_tx 通知调度器               │                 │
│    ├─ 日志: pong_intercepted              │                 │
│    └─ 返回 Ok, 不发送外部 SMTP            │                 │
└──────────────────┬──────────────────────────┘              │
                   ▼                                         │
┌─────────────────────────────────────┐                      │
│ ❻ scheduler → pending → bridge →   │                      │
│    webhook (回到 ❸, 走 pong 分支)    │                      │
└─────────────────────────────────────┘                      │
                   │                                         │
                   ▼                                         │
            amail.log 出现两条记录:                           │
            {"dir":"ping_intercepted","ping_id":"..."}        │
            {"dir":"pong_returned","ping_id":"..."}           │
            ── check_status 读取 → ✅                         │
```

## 三、邮件类型定义

| 邮件 | subject | direction | 作用 |
|---|---|---|---|
| Ping | `__amail_ping__:{uuid}` | SMTP 入站 → gateway → bridge → webhook | 测试入站链路 |
| Pong | `__amail_pong__:{uuid}` | webhook → API → gateway → SmtpRelay(拦截) → create_inbound → webhook | 测试出站 API + SMTP 环路 |

## 四、各环节改动明细

### 4.1 Rust: SmtpRelay（sender.rs）

**改动 A：增加 trigger_tx 字段**

```rust
pub struct SmtpRelay {
    transport: SmtpTransportMode,
    email_factory: Arc<EmailFactory>,
    dkim_signer: Option<Arc<dyn MessageSigner>>,
    trigger_tx: mpsc::Sender<String>,    // ← 新增
}
```

**改动 B：from_config() 增加 trigger_tx 参数**

```rust
pub fn from_config(
    config: &RelayConfig,
    email_factory: Arc<EmailFactory>,
    hostname: Option<&str>,
    dkim_signer: Option<Arc<dyn MessageSigner>>,
    mx_deliverer: Option<Arc<dyn MxDeliverer>>,
    trigger_tx: mpsc::Sender<String>,    // ← 新增
) -> AppResult<Self> {
    // ... 原有逻辑 ...
    Ok(SmtpRelay { transport, email_factory, dkim_signer, trigger_tx })
}
```

**改动 C：send_email() 拦截逻辑**

在 `filter_external_recipients` 之后、发送之前插入：

```rust
// ── [P0] Ping-pong interception ────────────────────────────
// Detect pong email whose external recipients have been
// filtered by loopback prevention → redirect as inbound.
let pong_prefix = "__amail_pong__:";
if record.subject.starts_with(pong_prefix)
    && external_recipients.is_empty()
    && !record.recipients_parsed().to.is_empty()
{
    let new_id = Uuid::new_v4().to_string();
    let new_subject = record.subject.clone();
    let new_body = record.body.clone();

    // Determine new sender: from pong's recipients (the original
    // manager address encoded in the SMTP envelope)
    let recipients = record.recipients_parsed();
    let raw_to = recipients.to.first()
        .cloned().unwrap_or_default();

    // Determine new recipient: from pong's From header (agent)
    let headers = record.headers_parsed();
    let raw_from = headers.get("from")
        .and_then(|v| v.as_str())
        .and_then(|s| {
            // Extract email from "Name <email>" or bare "email"
            if let Some(pos) = s.rfind('<') {
                let end = s.rfind('>').unwrap_or(s.len());
                Some(s[pos+1..end].trim().to_string())
            } else if s.contains('@') {
                Some(s.trim().to_string())
            } else { None }
        })
        .unwrap_or_else(|| record.sender.clone());

    info!(
        operation = "pong_intercepted",
        email_id = %record.id,
        from = %raw_to,
        to = %raw_from,
        subject = %new_subject,
        "Pong intercepted — redirecting as inbound email"
    );

    let headers_json = serde_json::Value::Object(headers.clone()).to_string();
    self.email_factory.create_inbound(
        &new_id, _tenant_id,
        &raw_to, &raw_from,
        &new_subject, &new_body,
        None, None, Some(&headers_json),
        0,
    ).await?;

    let _ = self.trigger_tx.try_send(new_id.clone());
    return Ok(());
}
```

### 4.2 Rust: scheduler/entry.rs — 传入 trigger_tx

```rust
let smtp_relay = SmtpRelay::from_config(
    &config.relay,
    Arc::new(email_factory.clone()),
    config.smtp.hostname.as_deref(),
    dkim_signer,
    mx_deliverer,
    trigger_tx.clone(),    // ← 新增
)?;
```

### 4.3 Rust: sender.rs — 补充日志字段

在现有日志点追加 sender/recipient/subject：

| 位置 | 现有 | 追加 |
|---|---|---|
| sender.rs:252 `smtp_delivery_success` | `email_id`, `status_code` | +`sender`=`%record.sender`, +`recipient`=`%record.recipients`, +`subject`=`%record.subject` |
| sender.rs:256 `smtp_delivery_failed` | `email_id`, `error` | 同上 |
| sender.rs:282 `loopback_skip` | `recipient` | +`email_id`=`%record.id`, +`subject`=`%record.subject` |

### 4.4 Rust: receiver.rs — 补充 RCPT TO 日志

| 位置 | 现有 | 追加 |
|---|---|---|
| receiver.rs:368 `rcpt_to` | `system_id` | +`recipient`, +`sender` |
| receiver.rs:658 `email_received` | `sender`, `subject`, count | +recipient 列表（`recipients = %recipients_json`） |

### 4.5 Python: webhook.py — 拦截点A

在 `asyncio.create_task(self.handle_message(event))`（line 658）之前插入：

```python
# ── Ping-pong interception ────────────────────────────────
subject = (payload.get("subject") or "").strip()
ping_id = None

if subject.startswith("__amail_ping__:"):
    ping_id = subject.split(":", 1)[1].strip()
    if not ping_id:
        logger.warning("[ping] Malformed ping subject: %s", subject)
    else:
        try:
            # Send pong via send_mail (HTTP API → outbound path)
            from amail_tools import send_mail
            pong_body = json.dumps({
                "ping_id": ping_id,
                "event": {
                    "prompt": prompt,
                    "route": route_name,
                    "delivery_id": delivery_id,
                    "skills": skills,
                }
            }, indent=2)
            pong_result = send_mail(
                to=payload.get("from", ""),
                subject=f"__amail_pong__:{ping_id}",
                body=pong_body,
            )
            pong_status = "ok" if pong_result.get("success") else pong_result.get("error", "?")
        except Exception as e:
            pong_status = str(e)
            logger.error("[ping] send_mail failed: %s", e)

        # Log to amail.log
        _log_amail_event("ping_intercepted", ping_id, {
            "from": payload.get("from"),
            "to": payload.get("to"),
            "pong_status": pong_status,
        })
        return web.json_response({
            "pong": ping_id, "status": "pong_sent",
        })

elif subject.startswith("__amail_pong__:"):
    ping_id = subject.split(":", 1)[1].strip()
    if ping_id:
        _log_amail_event("pong_returned", ping_id, {
            "from": payload.get("from"),
            "to": payload.get("to"),
        })
    return web.json_response({
        "pong": ping_id, "status": "pong_returned",
    })
```

辅助函数：

```python
def _log_amail_event(dir_: str, ping_id: str, extra: dict):
    """Append a JSON line to ~/.hermes/amail.log for ping-pong tracking."""
    import json, os
    from datetime import datetime, timezone
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "dir": dir_,
        "ping_id": ping_id,
        **extra,
    }
    log_path = os.path.expanduser("~/.hermes/amail.log")
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
```

### 4.6 Python: check_status.py — 新增 `--ping` 模式

```python
if "--ping" in sys.argv:
    sys.exit(_run_ping_test())


def _run_ping_test() -> int:
    """Send a ping email via SMTP and verify the pong returns."""
    import uuid, time, json, socket, base64
    from pathlib import Path

    config_path = Path.home() / ".hermes" / "amail_gateway.json"
    if not config_path.exists():
        print("✗ amail_gateway.json not found")
        return 1

    cfg = json.loads(config_path.read_text())
    gw_url = cfg.get("gateway_url", "")
    ak = cfg.get("admin_key", "")
    agent_email = cfg.get("domain", "")
    manager = cfg.get("manager_address", "")

    if not all([gw_url, ak, agent_email, manager]):
        print("✗ Missing required config fields")
        return 1

    ping_id = uuid.uuid4().hex[:12]
    host = gw_url.replace("https://", "").replace("http://", "").split("/")[0]

    # Send ping via SMTP auth (same mechanism as send_welcome.py)
    key_bytes = bytes.fromhex(ak)
    b64_key = base64.b64encode(key_bytes).decode().rstrip("=")
    encoded_manager = manager.replace("@", "=")
    auth_from = f"{b64_key}={encoded_manager}@auth.local"

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.connect((host, 25))
        s.recv(4096)
        def cmd(c):
            s.sendall(f"{c}\r\n".encode())
            return s.recv(4096).decode().strip()

        cmd("EHLO amail-ping-test")
        resp = cmd(f"MAIL FROM:<{auth_from}>")
        assert resp.startswith("250"), f"MAIL FROM failed: {resp}"
        resp = cmd(f"RCPT TO:<{agent_email}>")
        assert resp.startswith("250"), f"RCPT TO failed: {resp}"
        resp = cmd("DATA")
        assert resp.startswith("354"), f"DATA failed: {resp}"

        body = f"From: {manager}\nTo: {agent_email}\nSubject: __amail_ping__:{ping_id}\n\nPing test message\n."
        s.sendall(body.replace("\n", "\r\n").encode() + b"\r\n.\r\n")
        resp = s.recv(4096).decode().strip()
        s.sendall(b"QUIT\r\n")
        s.close()
        assert resp.startswith("250"), f"DATA end failed: {resp}"
        print(f"  Ping sent: __amail_ping__:{ping_id}")
    except Exception as e:
        print(f"✗ SMTP send failed: {e}")
        return 1

    # Poll amail.log for pong_returned
    amail_log = Path.home() / ".hermes" / "amail.log"
    deadline = time.time() + 60
    found_ping = found_pong = False

    while time.time() < deadline:
        if amail_log.exists():
            for line in reversed(amail_log.read_text().splitlines()):
                if ping_id not in line:
                    continue
                try:
                    entry = json.loads(line)
                    d = entry.get("dir", "")
                    if d == "ping_intercepted":
                        found_ping = True
                    if d == "pong_returned":
                        found_pong = True
                except Exception:
                    pass
        if found_ping and found_pong:
            break
        time.sleep(3)

    if found_ping and found_pong:
        print(f"  ✓ Ping intercepted ({found_ping})")
        print(f"  ✓ Pong returned ({found_pong})")
        print(f"  ✓ Full pipeline verified — ping_id={ping_id}")
        return 0
    elif found_ping:
        print(f"  ✓ Ping intercepted, but pong not returned within 60s")
        return 1
    else:
        print(f"  ✗ No ping or pong detected within 60s")
        return 1
```

## 五、实施步骤

| 步骤 | 文件 | 内容 | 行数 | 依赖 |
|---|---|---|---|---|
| 1 | `sender.rs` | SmtpRelay: +trigger_tx 字段 +from_config 参数 | ~5 | — |
| 2 | `entry.rs` | SmtpRelay::from_config 调用传入 trigger_tx | ~1 | 步骤1 |
| 3 | `sender.rs` | send_email(): 拦截点B + create_inbound + trigger | ~40 | 步骤1 |
| 4 | `sender.rs` | 补充 smtp_delivery_success/failed/loopback_skip 日志字段 | ~6 | — |
| 5 | `receiver.rs` | 补充 rcpt_to/email_received 日志字段（recipient 列表） | ~4 | — |
| 6 | cargo build --release | 编译 Rust 端 | — | 步骤1-5 |
| 7 | 重启 bridge | 部署新 binary | — | 步骤6 |
| 8 | `webhook.py` | 拦截点A: ping 检测 → send_mail + log | ~40 | — |
| 9 | `check_status.py` | `--ping` 模式: SMTP 发 ping + 轮询检测 | ~80 | — |
| 10 | 端到端测试 | `python3 lib/check_status.py --ping` | — | 步骤6-9 |

## 六、测试结果验证方式

执行 `python3 lib/check_status.py --ping` 后：

```
Ping sent: __amail_ping__:a1b2c3d4e5f6
  ✓ Ping intercepted
  ✓ Pong returned
  ✓ Full pipeline verified — ping_id=a1b2c3d4e5f6
```

对应的 amail.log 会新增：

```json
{"ts":"...","dir":"ping_intercepted","ping_id":"a1b2c3d4e5f6","from":"925457@qq.com","to":"tow@amail.token.tm","pong_status":"ok"}
{"ts":"...","dir":"pong_returned","ping_id":"a1b2c3d4e5f6","from":"925457@qq.com","to":"tow@amail.token.tm"}
```

对应的 bridge 日志会新增一条 `pong_intercepted` 记录，包含 from/to/subject。
