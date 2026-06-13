# sender.rs — DKIM + MX 代码拆分分析

## DKIM：可移 ✅ / MX：不可移 ❌

### DKIM（apply_dkim，11 行）

当前：
```rust
async fn apply_dkim(&self, raw, email_id) -> Cow {
    match &self.dkim_signer {
        Some(s) => match s.sign(raw, email_id).await {
            Some(signed) => Cow::Owned(signed),
            None => Cow::Borrowed(raw),
        },
        None => Cow::Borrowed(raw),
    }
}
```

改造：加默认方法到 `DkimSigner` trait：

```rust
pub trait DkimSigner {
    async fn sign(&self, ...) -> Option<Vec<u8>>;

    async fn apply_sign(&self, raw: &[u8], email_id: &str) -> Cow<'_, [u8]> {
        match self.sign(raw, email_id).await {
            Some(s) => Cow::Owned(s),  // advanced
            None    => Cow::Borrowed(raw),  // base
        }
    }
}
```

sender.rs 中 `apply_dkim()` 删除，两处调用点改为：
```rust
let raw = match &self.dkim_signer {
    Some(s) => s.apply_sign(&raw, &id).await,
    None => Cow::Borrowed(&raw),
};
```

改动量：trait + 1 方法 + sender 改 2 行 + 删 11 行。

---

### MX（send_via_mx，140 行）：不可移 ❌

`send_via_mx()` 依赖 sender 自身 3 个字段：

```
self.email_factory     → Arc<EmailFactory>
self.hostname          → Option<String>
self.apply_dkim()      → DKIM 方法
```

要移入 `MxResolver` trait，必须把这 3 个依赖也传进去，trait 签名为：

```rust
trait MxResolver {
    async fn send_via_mx(
        &self,
        email_factory: &EmailFactory,
        hostname: Option<&str>,
        dkim_signer: Option<Arc<dyn DkimSigner>>,
        from_addr: &Address,
        recipients: &[Address],
        email_body: &MultiPart,
        record: &EmailRecord,
    ) -> AppResult<()>;
}
```

trait 被 sender 专用类型污染，违背策略模式初衷。

**结论**：MX 保持现状。策略模式已隔离——`BaseMxResolver.resolve()` 返回 Err，`send_via_mx()` 永不执行。和 `check_inbound()` 同理，运行时行为完全由 trait impl 决定。
