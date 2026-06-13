# Config 结构体拆分方案：base 开源 vs advanced 闭源

## 目标

base 版（amail-gateway）的 Config 只包含 base 运行的字段。
advanced 版（amail-advanced）扩展 base Config，添加专用字段。

## 拆分清单

### 从 base 移除 → 移入 advanced

| 段 | 移除字段 | 原因 |
|---|---------|------|
| `[acme]` | 整个段 | ACME 自动证书，base 无此功能 |
| `[rate_limit]` | 整个段 | base 版 RateLimitChecker 是 no-op |
| `[database].encryption` | encryption | base 版硬编码 true |
| `[dns].mx_override` | mx_override | base 版 MX resolver 返回错误 |
| `[relay].dkim_selector` | dkim_selector | base 版不签名 |
| `[relay].dkim_private_key_path` | dkim_private_key_path | base 版不签名 |

### 保留在 base

| 段 | 保留字段 | 原因 |
|---|---------|------|
| `[smtp].hostname` | hostname | SMTP banner，base 功能 |
| `[smtp].spf_policy` | spf_policy | receiver.rs 读取（虽 no-op） |
| `[smtp].ptr_policy` | ptr_policy | 同上 |
| `[http].hostname` | hostname | API 端点日志 URL |
| `[dns].delivery_window_secs` | delivery_window_secs | 调度器使用 |
| `[relay].smtp_server` | 全部保留 | base 需要上游 SMTP |

### AdvancedConfig 新结构

```rust
// amail-advanced/src/advanced/config.rs
pub struct AdvancedConfig {
    pub acme: AdvancedAcmeConfig,
    pub rate_limit: AdvancedRateLimitConfig,
    pub dns: AdvancedDnsConfig,
    pub relay: AdvancedRelayConfig,
    pub database: AdvancedDatabaseConfig,
}
```

### 加载方式

```rust
// advanced/src/main.rs
let raw = std::fs::read_to_string("config.toml")?;
let config: amail_base::Config = toml::from_str(&raw)?;     // 未知字段忽略
let advanced: AdvancedConfig = toml::from_str(&raw)?;        // 同上
```

## 涉及文件

| 文件 | 改动 |
|------|------|
| `gateway/src/core/config.rs` | 删除 3 个 struct，6 个字段 |
| `gateway/src/core/smtp/receiver.rs` | 无（spf/ptr 保留） |
| `gateway/src/core/api/http.rs` | dkim_selector 硬编码 "mail" |
| `gateway/src/server.rs` | 无（base 已用 Base* no-op） |
| `advanced/src/advanced/config.rs` | 新建：AdvancedConfig |
| `advanced/src/advanced/mod.rs` | 添加 config 模块 |
| `advanced/src/main.rs` | 加载双 Config |
| `advanced/src/server.rs` | 接收 AdvancedConfig 参数 |
| `gateway/config.example.toml` | 删除 pure-advanced 段 |
