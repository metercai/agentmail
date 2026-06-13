# Bridge 安全管理 & 性能优化方案

## 1. 配额分析：为什么 bridge key 会占用 max_addresses

### 1.1 api_keys 表结构

```
CREATE TABLE api_keys (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id     TEXT NOT NULL,
    domain_addr   TEXT NOT NULL,
    key_hash      TEXT NOT NULL UNIQUE,
    scopes        TEXT NOT NULL DEFAULT '["send"]',
    category      TEXT NOT NULL DEFAULT 'system',
    ...
    UNIQUE(system_id, domain_addr)
);
```

一行 = 一个邮箱地址 = 一个配额槽位。`UNIQUE(system_id, domain_addr)` 保证同一系统下每个地址唯一。

### 1.2 当前各 key 类型

| key 类型 | category | 创建路径 | 是否过 check_key_quota |
|----------|----------|---------|----------------------|
| admin key | "platform" | `server.rs setup_admin_key()` → 直接 `factory.create_api_key()` | **否**（bootstrap 绕过） |
| agent key | "agent" | `POST /api/v1/api-keys` → `check_key_quota()` | 是 |
| （未来）bridge key | "bridge" | `POST /api/v1/api-keys` → `check_key_quota()` | 是 |

### 1.3 check_key_quota 统计口径

```sql
SELECT COUNT(*) FROM api_keys WHERE system_id = ?1
```

**不过滤 category。** admin key 用 `system_id="admin"`，不在用户系统 ID 中，所以不计入用户系统的配额。

但 bridge key 用 `system_id="base-xxx"`，和 agent key 同系统，计入同一个 `max_addresses` 计数器。这就是 bridge key 会消耗地址配额的原因。

### 1.4 解决方案

**方案 A**：`count_api_keys_by_system_id` 增加 `category` 排除条件：

```sql
SELECT COUNT(*) FROM api_keys WHERE system_id = ?1 AND category != 'bridge'
```

bridge key 不占 `max_addresses`。简单 1 行改动。但无法独立限制 bridge key 数量。

**方案 B**：新增 `max_bridge_keys` 配额字段 + 独立计数器：

```sql
SELECT COUNT(*) FROM api_keys WHERE system_id = ?1 AND category = 'bridge'
```

bridge key 和 address 各自限额。更细粒度，但改动面大。

**推荐方案 A**。bridge 是基础设施组件，不应该计费。

---

## 2. 多 bridge 独立 API key

### 2.1 现状

```
system_id = base-xxx
  ├─ bridge-A ──── admin_key = "abc123..."  (system scope, 共享)
  ├─ bridge-B ──── admin_key = "abc123..."  (同一把 key)
  └─ agent-alice ─ api_key  = "xxx..."       (独立)
```

问题：一把 key 泄露 → 全部 bridge 失陷，无法单独吊销。

### 2.2 改进

```
system_id = base-xxx
  ├─ bridge-A ──── api_key_001  (scope: bridge, category: bridge, 不计 max_addresses)
  ├─ bridge-B ──── api_key_002  (scope: bridge, category: bridge)
  └─ agent-alice ─ api_key_xxx  (scope: agent)
```

### 2.3 实施改动

| 模块 | 改动 |
|------|------|
| `integrate.sh` | bridge 部署时调 `POST /api/v1/api-keys {domain_addr:"bridge-xxx", scopes:["bridge"], category:"bridge"}` |
| `amail_bridge.toml` | `[pull] admin_key` → `[pull] api_key` |
| `bridge pull.rs` | `X-Api-Key: state.config.pull.api_key`（字段名改） |
| `advanced storage.rs` | `count_api_keys_by_system_id` 加 `AND category != 'bridge'`（方案 A） |
| gateway 无改动 | `pending/ack` 已接受 bridge scope |

---

## 3. Pull 大 email 列表性能优化

### 3.1 现状

```json
POST /api/v1/admin/pending
{"limit": 50, "emails": ["a1@x.com", "a2@x.com", ..., "a999@x.com"]}
```

问题：1000 地址 → 30KB JSON/次, SQLite 最多 999 绑定参数。

### 3.2 方案 B：移除 email 过滤

bridge 不传 `emails` → gateway 返回该系统所有 pending → bridge 本地用 `router.lookup()` 过滤 → 匹配的才 ACK → 不匹配的留在队列被 TTL 清理。

| 改动 | 文件 |
|------|------|
| gateway 接受空 emails 参数 | `http.rs list_pending_deliveries` 处理 `emails:[]` 情况 |
| bridge 移除 emails 过滤 | `pull.rs fetch_pending()` 删除 `emails` 构建 |
| bridge 本地过滤 | `pull.rs` 对拉取结果调 `router.lookup()` |

### 3.3 方案 A（如果需要）：域名过滤

bridge 从 route table 提取唯一域名 → `["x.com", "y.com"]` → gateway 用 `domain_addr LIKE '%@x.com'` 过滤。

---

## 4. 实施顺序

| 阶段 | 内容 | 风险 |
|------|------|------|
| Phase 1 | 移除 email 过滤（方案 B） | 低，gateway 2 行 + bridge 5 行 |
| Phase 2 | 独立 bridge key + 配额豁免（方案 A） | 中，涉及 integrate.sh 和配额逻辑 |
| Phase 3 | 域名过滤（方案 A，按需） | 低，仅当方案 B 不够时启用 |
