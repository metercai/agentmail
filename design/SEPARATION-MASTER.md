# amail-gateway — 基础版与高级版代码分离总方案

## 一、分离原则

三种机制：

| 机制 | 说明 | 适用于 |
|------|------|--------|
| **Config 分离** | base Config ≠ AdvancedConfig，各自解析同一份 TOML | 配置项 |
| **Trait 默认实现** | trait 提供 no-op 默认方法，base 继承，advanced override | 逻辑隔离 |
| **路由注入** | `create_router(domain_handler)` 允许 advanced 替换 handler | HTTP 路由 |

## 二、Config：已完成 ✅

```
config.toml (同一份文件)
├── base Config    → http/smtp/storage/webhook/retry/relay/monitoring/logging/dns/owner
└── AdvancedConfig → acme/rate_limit/dns.mx_override/relay.dkim_*/database.encryption/inbound
```

base 移除的字段：acme, rate_limit, dns.mx_override, relay.dkim_*, database.encryption, spf_policy, ptr_policy, DnsHints

## 三、DNS 提示：已完成 ✅

| 层 | Base | Advanced |
|----|------|---------|
| 路由 | `create_router(..., None)` | `create_router(..., Some(handler))` |
| Handler | `create_system_domain` (pub) | 调 base handler → enrich JSON with dns_hints |
| 数据 | — | 从 AdvancedConfig.relay 读取 relay_hostname/dkim_selector |

## 四、Inbound Security (SPF+PTR)：已完成 ✅

| 层 | Base | Advanced |
|----|------|---------|
| Trait | `check_inbound()` 默认 `Ok(())` | override，真正检查 SPF+PTR |
| 策略配置 | — | AdvancedConfig.inbound.spf_policy / ptr_policy |
| Receiver | 1 行 `self.inbound_security.check_inbound(ip,from,domain)?` | 同 |
| 注释 | "Inbound security check" | 日志含 spf/ptr |

## 五、DKIM：待实施 ⬜

### 目标
移除 base sender.rs 中的 `apply_dkim()` 方法，将逻辑移入 trait。

### 方案
在 `DkimSigner` trait 增加默认方法：

```rust
pub trait DkimSigner: Send + Sync {
    async fn sign(&self, raw: &[u8], email_id: &str) -> Option<Vec<u8>>;

    /// Apply signing. Base returns Cow::Borrowed (unsigned).
    async fn apply_sign<'a>(&self, raw: &'a [u8], email_id: &str) -> Cow<'a, [u8]> {
        match self.sign(raw, email_id).await {
            Some(s) => Cow::Owned(s),
            None => Cow::Borrowed(raw),
        }
    }
}
```

sender.rs 改动：删 `apply_dkim()`（11 行），两处调用改为：
```rust
let raw = match &self.dkim_signer {
    Some(s) => s.apply_sign(&raw, &email_id).await,
    None => Cow::Borrowed(&raw),
};
```

| 文件 | 改动 |
|------|------|
| `core/strategy.rs` | trait 加 `apply_sign()` 默认方法 |
| `core/smtp/sender.rs` | 删 `apply_dkim()`，改 2 处调用 |
| base edition | 无需改动（BaseDkimSigner::sign 返回 None） |
| advanced edition | 无需改动（AdvancedDkimSigner::sign 返回 Some） |

**影响**：base sender.rs 不再包含 "DKIM" 字样。签名逻辑完全在 advanced trait impl 中。

## 六、MX 直投：待实施 ⬜

### 目标
移除 base sender.rs 中的 `send_via_mx()` 方法（~140 行），将逻辑移入 trait。

### 方案
新增 `MxDeliverer` trait：

```rust
/// Deliver email via MX resolution. Base returns Err.
pub trait MxDeliverer: Send + Sync {
    async fn deliver_via_mx(
        &self,
        mx: &dyn MxResolver,
        email_factory: &EmailFactory,
        hostname: Option<&str>,
        dkim_signer: Option<Arc<dyn DkimSigner>>,
        from_addr: &Address,
        recipients: &[Address],
        email_body: &MultiPart,
        record: &EmailRecord,
    ) -> AppResult<()>;
}

/// Base: MX delivery not available.
pub struct BaseMxDeliverer;
impl MxDeliverer for BaseMxDeliverer {
    async fn deliver_via_mx(&self, ...) -> AppResult<()> {
        Err(AppError::Smtp("MX delivery not available in base edition".into()))
    }
}
```

sender.rs 改动：
- `SmtpRelay` 新增字段 `mx_deliverer: Arc<dyn MxDeliverer>`
- dispatch 处改为 `self.mx_deliverer.deliver_via_mx(mx.as_ref(), ..., record).await`
- 删除 `send_via_mx()` 方法（~140 行）

advanced 改动：
- `AdvancedMxDeliverer` 包含完整 MX 解析+投递逻辑（从 base sender.rs 搬 140 行）

| 文件 | 改动 |
|------|------|
| `core/strategy.rs` | 新增 `MxDeliverer` trait + `BaseMxDeliverer` |
| `core/smtp/sender.rs` | 删 `send_via_mx()` + 重构 dispatch |
| `server.rs`（base） | 注入 `BaseMxDeliverer` |
| `server.rs`（advanced） | 注入 `AdvancedMxDeliverer` |
| `advanced/strategy.rs`（advanced） | 新增 `AdvancedMxDeliverer` |

**影响**：base sender.rs 不再包含 MX 直投代码。`MxResolver` trait 保持纯粹（只负责解析）。

## 七、DKIM 在 base strategy.rs 中的痕迹

base `strategy.rs` 中 `DkimSigner` trait + `SpfLabel` enum 被保留——这是策略模式接口，不是具体实现。base 只提供 no-op impl。

需改注释：`DkimSigner` trait doc 改为通用描述，不强调 "DKIM 签名" 字面。

## 八、改动总览

| 模块 | Base 状态 | Advanced 状态 | 完成度 |
|------|----------|-------------|--------|
| Config | 无 advanced 字段 | AdvancedConfig | ✅ |
| DNS 提示 | SystemDomainResponse 无 dns_hints | 自定义 handler enrich | ✅ |
| SPF+PTR | check_inbound() 默认 no-op | Real check_inbound() | ✅ |
| DKIM | apply_sign() 默认 no-op | Real apply_sign() | ⬜ |
| MX 直投 | MxDeliverer::deliver 返回 Err | Real deliver_via_mx() | ⬜ |
| Receiver 注释 | "Inbound security check" | — | ✅ |
