# Base 版 DKIM / SPF / DnsHints 残留移除方案

## 可移除（无核心依赖）

### 1. DnsHints 整组

| 文件 | 内容 |
|------|------|
| `types.rs:243` | `pub dns_hints: DnsHints` — 字段，移除 |
| `types.rs:249-260` | `DnsHints` 结构体，移除 |
| `types.rs:366` | `dns_hints: DnsHints::default()` — Default impl，移除 |
| `types.rs:374-410` | `with_dns_hints()` — 死函数，移除 |
| `types.rs:416-422` | `impl DnsHints` + `relay_spf()`，移除 |

**影响**：`SystemDomainResponse` 响应体不再包含 `dns_hints` 字段。

### 2. spf_policy 配置字段

| 文件 | 内容 |
|------|------|
| `config.rs:102-104` | `pub spf_policy: String` — 从 SmtpConfig 移除 |
| `receiver.rs:233` | `self.config.smtp.spf_policy` — 硬编码 `"off"`（base 版不检查 SPF） |

## 保留（策略模式，需 trait 接口）

| 项 | 原因 |
|----|------|
| `DkimSigner` trait + `BaseDkimSigner` | sender.rs 需 trait 接口。Base 返回 None = 不签名 |
| `InboundSecurity` trait + `BaseInboundSecurity` | receiver.rs 需 trait 接口。Base 永远 pass |
| `SpfLabel` enum | InboundSecurity trait 用到 |


## 实施步骤

| 步 | 文件 | 改动量 |
|----|------|--------|
| 1 | `types.rs` — 删除 `DnsHints` + `dns_hints` 字段 + `with_dns_hints` | ~40 行 |
| 2 | `config.rs` — 删除 `spf_policy` | 2 行 |
| 3 | `receiver.rs` — 硬编码 `"off"` | 1 行 |
| 4 | 编译验证 | — |
