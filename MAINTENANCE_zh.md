# AgentMail 维护手册

---

## 目录

1. [本地存储](#1-本地存储)
2. [日志](#2-日志)
3. [check_status 诊断](#3-check_status-诊断)
4. [amail-bridge 桥接服务](#4-amail-bridge-桥接服务)
5. [Hermes Gateway](#5-hermes-gateway)
6. [常见故障处理](#6-常见故障处理)

---

## 1. 本地存储

### 目录结构

```
~/.agentmail/
├── {system_id}/
│   ├── agentmail_gateway.json     # 网关连接配置（gateway_url, admin_key, system_id, domain）
│   ├── agentmail.json              # 根 profile 的 agent 配置（email, api_key）
│   └── profiles/
│       └── {name}/
│           └── agentmail.json      # 命名 profile 的 agent 配置（含 persona 邮件地址）
├── .system_raw_key/
│   └── {system_id}_admin.key  # 系统 admin_key 原始值（仅集成时写入）
├── amail-bridge.log            # bridge 日志
├── amail_bridge.toml           # bridge 配置文件
├── amail_routes.toml           # bridge 路由表
├── bin/
│   └── amail-bridge            # bridge 二进制文件
├── bridge.pid                  # bridge 进程 PID
├── {email_hash}/
│   └── agentmail.log           # agent 处理日志（每 email 独立文件）
│   └── raw_email/              # 原始邮件快照（save_raw_snapshots=true 时）
```

### 关键文件说明

| 文件 | 内容 | 写入时机 |
|------|------|----------|
| `agentmail_gateway.json` | gateway_url, admin_key, system_id, domain, system_name, save_raw_snapshots, manager_address, webhook_host | Step 4 `setup_system.py` |
| `agentmail.json`（根） | email, api_key, gateway_url, domain, system_id, manager_address | `_auto_register_email()` + `_auto_activate_profile()` |
| `profiles/{name}/agentmail.json` | 同上 + persona 前缀的 email | 同上 |
| `amail_bridge.toml` | mode, addr/pull 配置 | `deploy_bridge.py` |

### 路径迁移

所有配置统一在 `~/.agentmail/{system_id}/` 下。旧版 `~/.hermes/` 下的 `agentmail.json`、`agentmail_gateway.json` 不再使用。如有旧文件，手动清理。

---

## 2. 日志

### 日志文件

| 文件 | 内容 | 位置 |
|------|------|------|
| **agentmail.log** | 邮件处理流水线日志（ping/pong、inbound/outbound、预处理） | `~/.agentmail/{email_hash}/agentmail.log` |
| **amail-bridge.log** | bridge 运行日志（拉取、转发、路由、健康检查） | `~/.agentmail/amail-bridge.log` |
| **gateway.log** | Hermes gateway 日志（每个 profile 独立） | `~/.hermes/gateway.log`（根 profile）或 `~/.hermes/profiles/{name}/gateway.log` |

### agentmail.log 格式

每行一个 JSON 对象：

```json
{"ts":"2026-06-26T07:18:41Z","dir":"ping_intercepted","ping_id":"54deaff9cacc","from":"925457@qq.com","to":["mike@amail.token.tm"]}
```

`dir` 字段取值：
- `ping_intercepted` — webhook 收到 ping 邮件
- `pong_sent` — pong 已通过 send_mail 发送
- `pong_returned` — pong 邮件回环到 webhook 被识别
- `inbound` — 普通入站邮件

### 日志轮转

日志文件无自动轮转。建议通过 logrotate 或定时任务管理：

```bash
# logrotate 配置示例 /etc/logrotate.d/agentmail
~/.agentmail/*/agentmail.log {
    daily
    rotate 7
    compress
    missingok
}
~/.agentmail/amail-bridge.log {
    daily
    rotate 7
    compress
    missingok
}
```

---

## 3. check_status 诊断

### 运行诊断

```bash
# 完整管道诊断
python3 lib/check_status.py

# 带修复建议
python3 lib/check_status.py --verbose

# JSON 输出
python3 lib/check_status.py --json

# 端到端心跳测试
python3 lib/check_status.py --ping
```

### 4 层检查

| 层级 | 检查项 | 说明 |
|------|--------|------|
| **Level 1: gateway** | 健康检查 / whoami / 域名列表 | 验证 amail-gateway 连通性和权限 |
| **Level 2: bridge** | 进程存活 / 待投递查询 / 日志活动 | 验证 bridge 运行和拉取路径 |
| **Level 3: agent-gw** | webhook 端口可达 / 路由配置 | 验证 Hermes gateway 就绪 |
| **Level 4: profile** | 配置文件存在 / email 有效 | 验证 agent profile 配置完整 |

### ping/pong 测试

```bash
python3 lib/check_status.py --ping
```

通过 SMTP 发送 ping 邮件 → gateway → bridge → webhook → 识别为 ping → 自动回复 pong（通过 gateway API）→ pong 作为 inbound 回环 → webhook 识别 → 写入 `pong_returned` 日志。

预期输出：
```
  Ping sent: __agentmail_ping__:a1b2c3d4e5f6
  +  1.2s    Webhook Receive (ping)         ✓
  +  2.9s    Pong Sent (send_mail)          ✓
  +  5.1s    Webhook Return (pong)          ✓
  ⏱  Total round-trip: 5.1s
  ✓ Full pipeline verified — ping_id=a1b2c3d4e5f6
```

---

## 4. amail-bridge 桥接服务

### 进程管理

```bash
# 查看运行状态
ps aux | grep amail-bridge
cat ~/.agentmail/bridge.pid

# 重新启动
kill $(cat ~/.agentmail/bridge.pid)
python3 lib/deploy_bridge.py

# 查看日志
tail -f ~/.agentmail/amail-bridge.log
```

### 配置文件

`~/.agentmail/amail_bridge.toml`：

```toml
mode = "pull"

[pull]
amail_url = "https://amail.token.tm"
admin_key = "sk-bridge-xxx"
system_id = "system-xxxx"
poll_interval_sec = 5

[health]
check_interval_sec = 60
fail_threshold = 3
connect_timeout_sec = 3
```

### 路由管理

`~/.agentmail/amail_routes.toml` 或通过 bridge API 管理。

### 双模式

| 模式 | 适用场景 | 说明 |
|------|----------|------|
| `pull` | Hermes 在内网，gateway 在外网 | bridge 定期拉取待投递邮件 |
| `push` | Hermes 与 gateway 在同一网络 | gateway 直接推送 webhook（无需 bridge） |

---

## 5. Hermes Gateway

### 进程管理

```bash
# 启动根 profile gateway
hermes gateway run --accept-hooks --replace

# 启动命名 profile gateway
hermes -p {name} gateway run --accept-hooks --replace

# 查看运行状态
hermes gateway status

# 查看端口
grep -A2 'webhook:' ~/.hermes/config.yaml
grep -A2 'webhook:' ~/.hermes/profiles/{name}/config.yaml
```

### 多 profile 网关

每个命名 profile 运行独立的 Hermes gateway 进程，使用独立端口和独立 webhook 路由。多 profile 网关由 `lib/hermes_gateway.sh` 统一管理：

```bash
bash lib/hermes_gateway.sh
```

### 健康检查

```bash
curl http://127.0.0.1:{port}/health
```

根 profile 默认端口 8644，命名 profile 从 8645 起顺序分配。

---

## 6. 常见故障处理

### ping 测试卡在 "pong not returned"

**原因：** pong 邮件未回环到 webhook。通常是 API key 与 email 不匹配导致 `send_mail` 失败。

**检查：**
```bash
grep pong_status ~/.agentmail/*/agentmail.log
# 如果看到 "Send failed: Sender mismatch" → key 所属 email 与 config 不一致
```

**修复：** 检查 `~/.agentmail/{system_id}/agentmail.json` 的 email 和 api_key 是否匹配。根 profile 的 key 不能是 persona 的 key。

### bridge 无法拉取邮件

**检查：**
```bash
# bridge 是否运行
ps aux | grep amail-bridge

# pull 配置
cat ~/.agentmail/amail_bridge.toml

# 网关连通性
curl https://amail.token.tm/health

# bridge 日志最近错误
tail -20 ~/.agentmail/amail-bridge.log
```

### gateway 无法启动

**检查：**
```bash
# webhook 端口被占用
ss -tlnp | grep 8644

# 配置语法
hermes gateway run --dry-run

# 日志
cat ~/.hermes/gateway.log
```

### 重新集成

```bash
# 完全清理（保留 ~/.agentmail/）
bash uninstall.sh

# 重新集成
bash integrate.sh
```

`integrate.sh` 是幂等的——重复运行会自动跳过已完成步骤。

### API key 更新

如果网关侧 key 轮转或失效：

```bash
# 方法 1：清空 agentmail.json 的 activation_code 和 api_key，让 agent 下次启动时重新激活
# 方法 2：直接用新 key 替换 agentmail.json 中的 api_key
# 方法 3：重新运行 integrate.sh
```
