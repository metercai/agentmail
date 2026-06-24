# Agentmail 数据目录迁移方案

> 评审用。评审通过后逐步实施。

## 一、目标目录结构

```
~/.agentmail/                                   ← 数据根目录（Hermes 管控之外）
├── .system_raw_key/                            ← 系统原始 admin key
│   └── system-{id}_admin.key
├── amail_bridge.toml                           ← bridge 配置
├── amail_routes.toml                           ← bridge 路由
├── amail-bridge.log                            ← bridge 日志
│
├── {agent_addr@domain}/                        ← 每个 agent 一个子目录
│   ├── agentmail.log                           ← per-profile 处理日志（原 amail.log）
│   └── {yyyymm}/                               ← 按月份归档
│       ├── in-{message_id}.json                ← 入站原始邮件快照
│       ├── out-{message_id}.json               ← 出站原始邮件快照
│       └── ping-{ping_id}.json                 ← ping-pong 事件快照
│
└── ...更多 agent/
```

## 二、迁移映射（当前 → 目标）

| 当前路径 | 目标路径 | 文件用途 |
|---|---|---|
| `~/.hermes/amail.log` | `~/.agentmail/{agent}/agentmail.log` | amail 处理日志 |
| `~/.hermes/raw_email/{addr}/{yyyymm}/*.json` | `~/.agentmail/{agent}/{yyyymm}/*.json` | 原始邮件快照 |
| `~/.hermes/amail_bridge.toml` | `~/.agentmail/amail_bridge.toml` | bridge 配置 |
| `~/.hermes/amail-bridge.log` | `~/.agentmail/amail-bridge.log` | bridge 日志 |
| `~/.hermes/amail_routes.toml` | `~/.agentmail/amail_routes.toml` | bridge 路由 |
| `agentmail/.system_raw_key/{id}_admin.key` | `~/.agentmail/.system_raw_key/{id}_admin.key` | 系统原始 key |

## 三、{agent} 子目录

### 命名规则

邮箱地址中 `@` 替换为 `_`，例如：

```
tow@amail.token.tm  →  tow_amail.token.tm
support.tow@domain  →  support.tow_domain
```

### 获取方式

由 `AGENTMAIL_HOME` 环境变量传入，Hermes 进程调用 `amail_tools.py` 前设置：

```python
def _agentmail_dir() -> Path:
    env = os.environ.get("AGENTMAIL_HOME", "")
    if env:
        return Path(env)
    # fallback（仅限非 webhook 场景）
    return Path.home() / ".agentmail" / "default"
```

## 四、各文件具体改动

### 4.1 `amail_tools.py`

| 函数 | 当前 | 改为 |
|---|---|---|
| `_raw_email_dir()` | `Path(HERMES_PROFILE_DIR)/"raw_email"` | `_agentmail_dir()` |
| `_log_amail()` | `Path.home()/".hermes"/"amail.log"` | `_agentmail_dir()/"agentmail.log"` |

`_save_inbound_snapshot` / `_save_outbound_snapshot` 中：

```python
# 当前
snapshot_dir = _raw_email_dir() / safe_addr / yyyymm

# 改为
snapshot_dir = _agentmail_dir() / yyyymm
```

### 4.2 `check_status.py`

| 常量 | 当前值 | 改为 |
|---|---|---|
| `AMAIL_LOG` | `HERMES_HOME/"amail.log"` | 从 `--agent` 参数获取路径 |
| `BRIDGE_CFG` | `HERMES_HOME/"amail_bridge.toml"` | `Path.home()/".agentmail"/"amail_bridge.toml"` |
| `BRIDGE_LOG` | `HERMES_HOME/"amail-bridge.log"` | 同上 |
| `ROUTES_FILE` | `HERMES_HOME/"amail_routes.toml"` | 同上 |
| `raw_dir` | `Path.home()/".hermes"/"raw_email"` | `agent_dir/"{yyyymm}"` |

新增 `--agent` 参数：

```
check_status.py --agent tow@amail.token.tm
check_status.py --ping --agent tow@amail.token.tm
```

### 4.3 `deploy_bridge.py`

```python
# 当前
home = os.path.expanduser("~/.hermes")
bridge_cfg = os.path.join(home, "amail_bridge.toml")
log_path = os.path.expanduser("~/.hermes/amail-bridge.log")

# 改为
home = os.path.expanduser("~/.agentmail")
bridge_cfg = os.path.join(home, "amail_bridge.toml")
log_path = os.path.join(home, "amail-bridge.log")
```

### 4.4 `send_welcome.py`

```python
# 当前
log_path = os.path.expanduser("~/.hermes/amail.log")
# 改为
log_path = os.path.join(os.environ.get("AGENTMAIL_HOME", ""), "agentmail.log")
```

如果 `AGENTMAIL_HOME` 未设置（直接脚本执行场景），fallback 到 `~/.agentmail/default/agentmail.log`。

### 4.5 `apply_webhook_patch.py`

patch 内容中的日志路径更新：

```python
# patch 中 _log_amail_event 的路径
_log_path = _os.environ.get("AGENTMAIL_HOME", "") 
if not _log_path:
    _log_path = str(_os.path.expanduser("~/.agentmail/default"))
_log_path = _os.path.join(_log_path, "agentmail.log")
```

### 4.6 `integrate.sh`

#### 系统 raw key 保存

```bash
# 当前（line 280-281）
mkdir -p "$SCRIPT_DIR/.system_raw_key"
echo "$ADMIN_KEY" > "$SCRIPT_DIR/.system_raw_key/${SYSTEM_ID}_admin.key"

# 改为
mkdir -p "$HOME/.agentmail/.system_raw_key"
echo "$ADMIN_KEY" > "$HOME/.agentmail/.system_raw_key/${SYSTEM_ID}_admin.key"
```

#### Bridge 配置路径

`deploy_bridge.py` 改为向 `~/.agentmail/` 写配置后，`integrate.sh` 中 bridge 启动命令也要更新：

```bash
# 启动 bridge 的地方
/home/ubuntu/amail-bridge/target/release/amail-bridge \
  -c /home/ubuntu/.agentmail/amail_bridge.toml
```

### 4.7 桥接启动（gateway/webhook 脚本）

`setup_gateway.py` 中启动 bridge 的命令行参数需要更新 `-c` 指向 `~/.agentmail/amail_bridge.toml`。

## 五、影响范围

| 领域 | 改什么 |
|---|---|
| Python 数据层 | `amail_tools.py` (3 处函数) |
| 诊断工具 | `check_status.py` (~10 处路径 + `--agent` 参数) |
| 部署脚本 | `deploy_bridge.py` (3 处路径) |
| 欢迎邮件 | `send_welcome.py` (1 处日志路径) |
| webhook 补丁 | `apply_webhook_patch.py` (1 处日志路径) |
| 集成脚本 | `integrate.sh` (system_raw_key + bridge `-c`) |
| 桥接启动 | 各处 `-c` 参数指向的 toml 路径 |

## 六、实施顺序

```
Phase 1: 改 amail_tools.py（数据层，不影响启动）
Phase 2: 改 deploy_bridge.py + 关联启动脚本（写入新路径）
Phase 3: 改 check_status.py + send_welcome.py + webhook patch（读取新路径）
Phase 4: 改 integrate.sh（system_raw_key 保存路径）
Phase 5: 迁移现有数据（~/.hermes/amail.log → ~/.agentmail/）
Phase 6: 全量测试
```
