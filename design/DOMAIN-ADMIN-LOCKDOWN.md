# 域管理员权限收窄 & 集成脚本域级 key 方案

## 1. create_api_key 跨域限制

### 现状

`POST /api/v1/api-keys` 只验证 scope（`platform/system/agent_admin`），不验证 domain。domain_addr="dom1.com" 的管理员可为 `dom2.com` 创建 key。

### 方案

在 category validation 之后，`create_api_key` 添加域匹配：

```rust
// keys.rs create_api_key handler, after category validation
if let Err(e) = require_domain_match(&api_key, &req.email_address) {
    return Err(e);
}
```

如果 creation key 是域管理员（裸域），`require_domain_match` 只允许同域 target。系统管理员（空 email）不受限。

## 2. integrate.sh 域级 admin key

### 2.1 现状

```
integrate.sh:
  Step 2 → $ADMIN_KEY (system admin, empty email, scope=system)
  Step 3 → 创建裸域 dom1.com
  Step 5 → amail_gateway.json: { admin_key: SYSTEM_KEY }
  Step 8 → _auto_register_email 读取 admin_key → 调 register_email
  bridge → amail_bridge.toml admin_key: SYSTEM_KEY
```

问题：
- 一次集成只管理一个域，不需要全系统权限
- 泄露影响所有域
- create_api_key 跨域限制生效后，SYSTEM_KEY 不受限（empty email bypass），但如果是域级 key 则受限——与 design 矛盾

### 2.2 目标

```
integrate.sh:
  Step 2 → $ADMIN_KEY (system admin 或 product code)
  Step 3 → 创建裸域 dom1.com
  Step 3a → 创建域级 admin key (NEW)
             POST /api/v1/api-keys {
               system_id, email_address="dom1.com",
               scopes=["system"], category="system"
             }
  Step 5 → amail_gateway.json: { admin_key: DOMAIN_KEY }
  Step 8 → _auto_register_email 读取 DOMAIN_KEY → 调 register_email
  bridge → amail_bridge.toml admin_key: DOMAIN_KEY
```

### 2.3 影响面

| 位置 | 当前 | 改为 | 影响 |
|------|------|------|------|
| `amail_gateway.json` | admin_key = SYSTEM_KEY | admin_key = DOMAIN_KEY | _auto_register_email 自动切换 |
| `amail_bridge.toml` | admin_key = SYSTEM_KEY | admin_key = DOMAIN_KEY | bridge pull 用域级 key |
| bridge API key 创建 | 用 SYSTEM_KEY 调 POST api-keys | 用 DOMAIN_KEY 调 | 可创建（system scope 可造 key） |
| `integrate.sh` diagnostics | 用 SYSTEM_KEY | 用 DOMAIN_KEY | whoami 返回 domain_addr="dom1.com" |
| `_auto_register_email` | 用 SYSTEM_KEY 调 register_email | 用 DOMAIN_KEY | require_domain_match 裸域匹配通过 ✅ |
| `_auto_activate_profile` | 用 SYSTEM_KEY 调 activate_address | 用 DOMAIN_KEY | 激活地址不校验 admin key ✅ |

### 2.4 配额影响

域级 admin key 的 category="system"，quota 不统计（`AND category='agent'`）。不增加配额消耗。

### 2.5 保留 SYSTEM_KEY

`integrate.sh` 在创建域级 key 成功后，可将 SYSTEM_KEY 保留在 `amail_gateway.json` 的 `system_admin_key` 字段作为备用——仅供人工排查使用，不参与自动化流程。

## 3. 实施顺序

| 阶段 | 内容 | 依赖 |
|------|------|------|
| 1 | `create_api_key` 加 `require_domain_match` | 无 |
| 2 | `integrate.sh` Step 3a 创建域级 key + 替换全局 admin_key | 阶段 1 |
| 3 | 验证：域级 key → _auto_register_email → 地址注册 |
