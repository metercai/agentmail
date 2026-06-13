# 域管理员权限收窄 & 集成脚本域级 key 方案

## 1. create_api_key 跨域限制

### 现状

`POST /api/v1/api-keys` 只验证 scope，不验证 domain。domain_addr="dom1.com" 的域管理员可为 `dom2.com` 创建 key。

### 方案

category validation 之后加域匹配：

```rust
// keys.rs create_api_key handler
if let Err(e) = require_domain_match(&api_key, &req.email_address) {
    return Err(e);
}
```

域管理员（裸域）只允许同域 target。系统管理员（空 email）不受限。

---

## 2. integrate.sh 域级 admin key

### 2.1 现状与问题

**问题 1**：product_code 路径中 Step 3 被跳过，但 `$AMAIL_DOMAIN` 缺失时直接 `step_fail` 崩溃，不给用户交互机会。

**问题 2**：product_code 路径桥接部署在 Step 4，此时 `$ADMIN_KEY` 为空（系统尚未激活），写入空 admin_key。

**问题 3**：所有后续自动化步骤（_auto_register_email、bridge pull）使用系统级 admin_key，权限过宽。

### 2.2 修正后的完整流程

```
Step 1:  gateway_url 发现/输入
Step 2:  认证方式 (admin_key 或 product_code)
Step 3:  域名输入
           admin_key:   查询已有域列表 → 选择或输入新域名 → POST /domains 创建
           product_code: 直接输入新域名 → 存储 $AMAIL_DOMAIN（无 $SYSTEM_ID 无法查询）
           (若 $AMAIL_DOMAIN 已从 env 传入，跳过交互；product_code 删除 step_fail)
Step 4:  配置收集 (snapshot / manager_address / webhook 模式)
           仅收集变量，不部署 bridge
Step 5:  系统激活 + 域创建 + 配置保存
           admin_key:   写入 amail_gateway.json
           product_code: activate_system(domain=$AMAIL_DOMAIN) → 提取 SYSTEM_KEY/SYSTEM_ID/DOMAIN
           此时 $ADMIN_KEY/$SYSTEM_ID/$DOMAIN 均就绪
Step 5a: 桥接部署 + 域级 key 创建
           1. 创建域级 admin key:
              POST /api/v1/api-keys {
                system_id=$SYSTEM_ID, email_address=$DOMAIN,
                scopes=["system"], category="system"
              } → DOMAIN_ADMIN_KEY
           2. 替换全局配置: $ADMIN_KEY=DOMAIN_ADMIN_KEY, amail_gateway.json, amail_bridge.toml
           3. 部署 bridge 二进制 + 写入 amail_bridge.toml (域级 key)
           4. 创建 bridge API key (域级 key)
           5. 保存 SYSTEM_KEY:
              admin_key 路径 → 不保存（用户自行持有）
              product_code 路径 → 写入 ~/.hermes/amail_system.key（不进自动化）
Step 6-10: 工具安装 + webhook patch + profile hooks + diagnostics + 测试
```

### 2.3 系统级 key 存储

| 路径 | 存储位置 | 原因 |
|------|---------|------|
| admin_key | 不保存 | 用户自行持有，env 传入 |
| product_code | `~/.hermes/amail_system.key` | 激活生成，用户未见过，需保留但不进自动化 |

`amail_system.key` 不被 `_load_gateway_config` 读取，仅备人工排查。

### 2.4 影响面

| 位置 | 当前 | 改为 |
|------|------|------|
| `amail_gateway.json` admin_key | SYSTEM_KEY | DOMAIN_KEY |
| `amail_bridge.toml` admin_key | SYSTEM_KEY | DOMAIN_KEY |
| `_auto_register_email` 调用方 | SYSTEM_KEY | DOMAIN_KEY (裸域匹配通过) |
| `_auto_activate_profile` | SYSTEM_KEY | DOMAIN_KEY (激活不校验) |
| bridge API key 创建 | SYSTEM_KEY | DOMAIN_KEY (system scope 可造 key) |

### 2.5 配额影响

域级 admin key 的 category="system"，quota 不统计 `AND category='agent'`，不消耗配额。

---

## 3. 实施顺序

| 阶段 | 内容 | 依赖 |
|------|------|------|
| 1 | `create_api_key` 加 `require_domain_match` | 无 |
| 2 | Step 3 product_code 路径删除 `step_fail`，改为交互 fallback | 无 |
| 3 | Step 4 桥接部署代码迁至 Step 5a | 无 |
| 4 | Step 5a 创建域级 key + 替换全局配置 + system key 存储 | 阶段 1,2,3 |
| 5 | 验证：域级 key → _auto_register_email → 地址注册 |
