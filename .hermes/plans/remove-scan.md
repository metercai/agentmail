# 删除所有扫描逻辑，用 system_id 直接定位

## 原则
`~/.agentmail/system-{id}/` 存多个系统。所有调用方必须通过以下方式之一获得 system_id：
- 参数传递（集成脚本、CLI 工具）
- `HERMES_PROFILE_DIR/.agentmail` 指针（webhook 运行时）

禁止扫描 `~/.agentmail/system-*/`。

## 改动清单

### A. `_load_gateway_config()` → 加 system_id 参数
文件：`tools/amail_tools.py`

```python
def _load_gateway_config(system_id: str = "") -> Optional[dict]:
```

- system_id 非空 → 直接读 `~/.agentmail/system-{sid}/amail_gateway.json`
- system_id 为空 → 通过 `HERMES_PROFILE_DIR/.agentmail` 指针获取 system_id，再定位
- 指针也不存在 → 报错，不返回 None

调用方责任：确保调用前要么传 system_id，要么设好 HERMES_PROFILE_DIR。

### B. `_load_profile_config()` → 已走指针，不经扫描
当前 Priority 3 扫描 `system-*/amail.json` 删除。

### C. `_agentmail_dir()` → 靠指针，不经扫描
删除扫描回退，只走：
1. `AGENTMAIL_HOME` 环境变量
2. `HERMES_PROFILE_DIR/.agentmail` 指针
3. 回退 `~/.agentmail/default`（无扫描）

### D. `deploy_bridge.py` 第172行 → 传 system_id
`_save_gateway_config()` 的参数里有 `system_id`，
改为直接 `_gateway_config_path(system_id)`。

### E. `integrate.sh` → 传 system_id
`_find_gw_cfg()` 改为：
```bash
_find_gw_cfg() { echo "$HOME/.agentmail/system-$SYSTEM_ID/amail_gateway.json"; }
```

### F. `check_status.py` → 迁移到新路径
- `_find_gw_config()` 改为接受 system_id 参数
- `--system-id` CLI 参数
- 配置文件路径全部改为 `~/.agentmail/{system_id}/`

### G. 运行时函数（preprocess_mail_payload、_log_ping_event）
这些运行在 webhook 内，`HERMES_PROFILE_DIR` 被 Hermes 设置。
指针文件 `{profile_dir}/.agentmail` 可用。不走扫描。

## 调用方传递关系

```
集成脚本 (knows system_id)
  ├→ setup.py (system_id 参数)
  ├→ deploy_bridge.py (system_id 参数)
  ├→ _auto_register_email (system_id 参数)
  ├→ register_profiles.py (system_id 参数)
  └→ check_status.py (--system-id 参数 或 HERMES_PROFILE_DIR/.agentmail 指针)

Hermes gateway (sets HERMES_PROFILE_DIR)
  ├→ preprocess_mail_payload → _load_gateway_config, _load_profile_config
  ├→ _log_ping_event → 通过 HERMES_PROFILE_DIR/.agentmail 指针
  ├→ send_mail → _load_profile_config
  └→ _log_amail → _agentmail_dir
    全部通过 HERMES_PROFILE_DIR/.agentmail 指针获取 system_id
```

## 不需要改的
`_inject_profile_config()` — 已通过 profile_dir + config 里的 system_id 直接定位。无扫描。
`trigger_profile_hooks()` — 有 profile_dir 参数，指针可用。无扫描。
