# Phase 2: amail_tools.py — _auto_register_email + _auto_activate_profile

## 文件: `agentmail/tools/amail_tools.py`

### 1. 删除 `_is_local_url()` 函数（如果有）

不再需要——`webhook_host=""` 已由 integrate.sh 表达本机 gateway。

### 2. 删除 `delivery_mode` 所有引用

```bash
grep -n 'delivery_mode' tools/amail_tools.py
# 确认所有匹配行均删除
```

### 3. 删除 `bridge_url` 所有引用

```bash
grep -n 'bridge_url' tools/amail_tools.py
# 删除包括:
#   - _load_gateway_config() 中的 legacy migration 行 (line 452-454)
#   - _inject_profile_config() 中的 "bridge_url": config.get("bridge_url","") 行
```

### 4. 重写 `_auto_register_email` — webhook_url 构造

```python
def _auto_register_email(name: str, profile_dir: str, config: dict) -> None:
    # ... 前置逻辑不变 ...

    wh_port = wh_config["port"]

    webhook_host = config.get("webhook_host", "")
    if not webhook_host:
        # integrate.sh 已判定 gateway 本机 → 直连 Hermes
        webhook_url = f"http://127.0.0.1:{wh_port}/webhooks/amail-inbound"
    else:
        # 远程 gateway → 调 bridge API
        # 协议: hostname 含 '.' → https, 纯 IP → http
        if re.match(r'^\d+\.\d+\.\d+\.\d+:', webhook_host):
            bridge_base = f"http://{webhook_host}"
        else:
            bridge_base = f"https://{webhook_host}"

        try:
            r = requests.post(
                f"{bridge_base}/api/v1/routes",
                json={
                    "email": email,
                    "host": "127.0.0.1",
                    "port": wh_port,
                },
                timeout=5,
            )
            if r.status_code != 200:
                logger.error("[amail_gateway] Bridge route creation failed: %s",
                             r.status_code)
                return
            data = r.json()
            webhook_url = data.get("webhook_url", "")
            logger.info("[amail_gateway] Bridge returned webhook_url=%s", webhook_url)
        except Exception as e:
            logger.error("[amail_gateway] Bridge unreachable: %s", e)
            return

    # 提交到 gateway
    result = client.register_email(
        system_id=config["system_id"],
        mx_domain=config["domain"],
        email=email,
        webhook_url=webhook_url,   # pull="" push="http://..."
        webhook_secret=webhook_secret,
        manager_address=manager_address,
        generate_code=True,
    )

    # 写入 amail.json
    _inject_profile_config(profile_dir, {
        "email": email,
        "gateway_url": config.get("gateway_url", gateway_url),
        "domain": config["domain"],
        "system_id": config["system_id"],
        "manager_address": manager_address,
        "save_raw_snapshots": config.get("save_raw_snapshots", False),
        "webhook_host": config.get("webhook_host", "127.0.0.1"),
        "_wh_port": wh_port,            # ← 新增，供 _auto_activate_profile 检测
    })
```

### 5. `_auto_activate_profile` — 新增端口变更检测

在现有激活逻辑 **完成后**（`api_key` 已保存），追加：

```python
def _auto_activate_profile(profile_dir: str, config: dict) -> None:
    # ... 现有激活逻辑不变 ...

    # ── 端口变更检测 (远程 gateway 才需要) ──
    webhook_host = config.get("webhook_host", "")
    if not webhook_host:
        return  # 本机 gateway, 无 bridge

    wh_config = _ensure_profile_webhook(profile_dir)
    if not wh_config:
        return

    current_port = wh_config["port"]
    last_port = prof.get("_wh_port", 0)
    if current_port == last_port:
        return  # 端口未变

    # 协议判断
    if re.match(r'^\d+\.\d+\.\d+\.\d+:', webhook_host):
        bridge_base = f"http://{webhook_host}"
    else:
        bridge_base = f"https://{webhook_host}"

    try:
        r = requests.post(
            f"{bridge_base}/api/v1/routes",
            json={
                "email": prof["email"],
                "host": "127.0.0.1",
                "port": current_port,
            },
            timeout=5,
        )
        if r.status_code == 200:
            prof["_wh_port"] = current_port
            # 需要重新读入 amail.json，追加 _wh_port
            config_path = Path(profile_dir) / "amail.json"
            with open(config_path, "w") as f:
                json.dump(prof, f, indent=2)
            logger.info("[amail_gateway] Bridge route updated: port %s → %s",
                        last_port, current_port)
    except Exception as e:
        logger.warning("[amail_gateway] Bridge route refresh failed: %s", e)
```

### 6. `_inject_profile_config` — 删 `bridge_url`

```python
# 删这行:
"bridge_url": config.get("bridge_url", ""),
```

## 检测方法

```bash
cd /home/ubuntu/agentmail

# 语法/导入检查
python3 -c "import ast; ast.parse(open('tools/amail_tools.py').read()); print('Parse OK')"
python3 -c "import sys; sys.path.insert(0, 'tools'); import amail_tools; print('Import OK')"

# 确认无残留
grep -rn 'bridge_url\|delivery_mode' tools/amail_tools.py | grep -v '#\|"'
# 预期: 空 (无引用)

# 集成脚本诊断
./integrate.sh  # 手动运行到 Step 9，确认所有诊断项通过
```
