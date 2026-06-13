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

### 2.1 两种激活路径

**admin_key 路径**：Step 2 (提供 key) → Step 3 (创建域) → Step 4 (配置) → Step 5 (保存)

**product_code 路径**：Step 2 (提供码) → Step 3 (跳过) → Step 4 (配置) → Step 5 (激活系统+创建域+保存，返回 admin_key)

**两者在 Step 5 后汇聚**——都有 `$ADMIN_KEY`（系统级）、`$SYSTEM_ID`、域信息。

### 2.2 目标

在 Step 5 后（两种路径均已完成系统激活和域创建），统一创建域级 admin key：

```
Step 5 完成 → ADMIN_KEY(系统级) + SYSTEM_ID + DOMAIN
  │
  ├── 5a: 创建域级 admin key
  │    POST /api/v1/api-keys {
  │      system_id, email_address=DOMAIN,
  │      scopes=["system"], category="system"
  │    }
  │    → DOMAIN_ADMIN_KEY
  │
  ├── 5b: 替换全局配置
  │    amail_gateway.json: admin_key = DOMAIN_ADMIN_KEY
  │    amail_bridge.toml:  admin_key = DOMAIN_ADMIN_KEY
  │    $ADMIN_KEY = DOMAIN_ADMIN_KEY (后续步骤均使用)
  │
  └── 保留 SYSTEM_KEY 在 system_admin_key 字段（仅备查）
```

### 2.3 两种路径的差异处理

**admin_key 路径**（Step 3 用户输入域）：
- Step 5a 时 `$DOMAIN` 已确定，直接创建

**product_code 路径**（Step 5 激活后提取 NEW_DOMAIN）：
- 当前代码 line 750-756 已提取 `NEW_ADMIN_KEY`、`NEW_SYSTEM_ID`、`NEW_DOMAIN`
- Step 5a 时用提取的值，`$DOMAIN=$NEW_DOMAIN`

### 2.4 影响面

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
