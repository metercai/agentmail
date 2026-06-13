# sender.rs — DKIM + MX 直投代码分析

## 当前状态

`SmtpRelay` 结构体混合了三种职责：

```rust
// 行 26-33
pub struct SmtpRelay {
    transport: SmtpTransportMode,         // Relay | Direct(MxResolver)
    email_factory: Arc<EmailFactory>,
    dkim_signer: Option<Arc<dyn DkimSigner>>,  // 高级功能
    hostname: Option<String>,
}
```

| 功能 | 行数 | Base 行为 | Advanced 行为 |
|------|------|----------|-------------|
| DKIM `apply_dkim()` | 366-376 (11 行) | dkim_signer=None → 不签 | dkim_signer=Some → 签名 |
| MX `send_via_mx()` | 210-350 (~140 行) | 从不执行（BaseMxResolver 返回 Err） | 真正 MX 解析 |
| MX dispatch | 121-122 | unreachable | 到达 |
| Relay `send_via_relay()` | 153-210 (~57 行) | 正常运行 | 正常运行 |

## 策略模式已有隔离

```
mod...[truncated]
## 结论：不建议物理移除

MX 直投和 DKIM 大块代码存在于 base sender.rs 中，但它们**已经被 trait 隔离**：

- `BaseMxResolver.resolve()` → 永远返回错误 → `send_via_mx()` 永远不执行
- `BaseDkimSigner.sign()` → 永远返回 None → `apply_dkim()` 跳过签名，返回原文

物理移除的成本：
1. 需要把 `SmtpRelay` 拆成 base 和 advanced 两个版本
2. 需要把构造函数、dispatch 逻辑全部复制/重构
3. 需要更改 5+ 调用点（`entry.rs`、`server.rs` 等）

物理移除的收益：代码少 ~150 行，但增加两个版本的维护复杂度。

**建议**：保留现状。策略模式已经完成了逻辑隔离，base edition 的二进制产物中包含 `send_via_mx` 和 `apply_dkim` 代码段但运行时永不触及。
