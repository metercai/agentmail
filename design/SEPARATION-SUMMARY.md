# base / advanced 代码分离方法汇总

## 三层机制

| 机制 | 原理 | 适用于 |
|------|------|--------|
| **Config 双解析** | 同一份 TOML，base 和 advanced 各自 serde 忽略对方字段 | 配置项 |
| **Trait 默认实现** | base 利用 trait 默认方法（no-op），advanced 重写 | 逻辑隔离 |
| **路由+扩展注入** | `create_router(handler)` + `Extension<AdvancedConfig>` | HTTP 路由 |

## 一、Config 双解析

```
config.toml
├── amail_base::Config::load()      → 解析 base 字段，忽略 advanced
└── AdvancedConfig::from_str()      → 解析 advanced 字段，忽略 base
```

**base Config**：http / smtp / storage / webhook / retry / relay / monitoring / logging / dns / owner

**AdvancedConfig**：acme / rate_limit / dns.mx_override / relay.dkim_* / database.encryption / inbound

## 二、Trait 默认实现

| Trait | Base 默认方法 | Advanced 重写 |
|-------|-------------|-------------|
| `InboundSecurity::check_inbound()` | `Ok(())` - 不检查 | 真正 SPF+PTR 验证 |
| `DkimSigner::apply_sign()` | `Cow::Borrowed` - 不签名 | `Cow::Owned` - DKIM 签名 |
| `MxDeliverer::deliver_via_mx()` | `Err(...)` - 不可用 | 完整 MX 解析+投递 |

Base sender.rs 和 receiver.rs 中无任何 SPF/PTR/DKIM/MX 具体实现——只有 trait 调用。

## 三、路由注入

```rust
// base
let router = create_router(state, router_hook, None);

// advanced
let domain_handler = post(create_domain_with_hints);
let router = create_router(state, router_hook, Some(domain_handler))
    .layer(Extension(adv_config));
```

advanced handler 调用 base 的 `create_system_domain`（pub），富化响应。

## 四、改动总览

| 功能 | 完成 | Base 迹 | Advanced 负担 |
|------|------|--------|-------------|
| Config 分离 | ✅ | 无 acme/rate_limit/dkim/spf/ptr/DnsHints | AdvancedConfig |
| DNS 提示 | ✅ | 无 | ~60 行 handler |
| SPF+PTR | ✅ | `check_inbound()` 调用 1 行 | ~30 行 + 配置 |
| DKIM | ✅ | `apply_sign()` 调用 2 行 | 签名逻辑 |
| MX 直投 | ✅ | `deliver_via_mx()` 调用 1 行 | ~140 行 |
| 注释脱敏 | ✅ | "inbound security check" / "message signing" | — |

## 五、各文件参照（base 侧）

```
gateway/src/core/
├── strategy.rs          → MxDeliverer, DkimSigner, InboundSecurity trait 定义
├── smtp/receiver.rs     → 1 行 check_inbound()  + 无 SPF/PTR 具体逻辑
├── smtp/sender.rs       → 2 行 apply_sign() + 1 行 deliver_via_mx() + 无 MX/DKIM 具体逻辑
├── api/http.rs          → create_router 接受 domain_handler 参数
├── api/types.rs         → 无 DnsHints（advanced 侧自有）
├── base/strategy.rs     → BaseDkimSigner/BaseMxDeliverer/BaseMxResolver no-op 实现
└── scheduler/entry.rs   → 接受 mx_deliverer 参数（不硬编码 Base）
