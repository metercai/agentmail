# Phase 4 & 5: 文档更新 + 全流程验证

## Phase 4: 文档更新

### 4a: 更新集成文档

**文件**：`agentmail/hermes-amail-integration.md`、`agentmail/hermes-amail-integration-zh.md`

改动项：
- `delivery_mode` 字段说明 → 删除
- `bridge_url` 字段说明 → 删除
- `AMAIL_BRIDGE_URL` 环境变量 → 删除
- Step 4 更新为合并后流程（需同步中英文）
- Step 5.5 删除
- `amail_gateway.json` 配置表 → 删过期字段，增 `hostname` 说明
- `amail_bridge.toml` 配置表 → 更新为 `addr` + `hostname` + `mode`

### 4b: 检测方法

```bash
cd /home/ubuntu/agentmail

# 确认无残留
grep -rn 'delivery_mode' hermes-amail-integration*.md || echo "delivery_mode clean"
grep -rn 'bridge_url' hermes-amail-integration*.md || echo "bridge_url clean"
```

---

## Phase 5: 全流程验证

### 5a: 编译验证

```bash
# bridge
cd /home/ubuntu/amail-bridge
cargo build --release 2>&1 | tail -3
echo "bridge build: $?"

# gateway
cd /home/ubuntu/amail-gateway
cargo build --lib 2>&1 | tail -3
echo "gateway build: $?"

# advanced
cargo build --release 2>&1 | tail -3
echo "advanced build: $?"
strings ./target/release/amail-advanced | grep -c delivery_mode
# 预期: 0
```

### 5b: 可用性测试

```bash
cd /home/ubuntu/amail-gateway
./tests/availability_test.sh
# 预期: 全部 PASS
# 如果因删 delivery_mode 导致 4.2/4.5 测试需调整，见下文
```

`availability_test.sh` 可能需要的调整：

1. `delivery_mode` 字段相关的测试 case 中：
   - 4.2a-4.2c 测试 `create_system_domain` → 删 delivery_mode 字段
   - 4.5a-4.5c 测试 `register_address` → 删 delivery_mode 字段
2. 8.10a-d probe-webhook 测试 → 保留不变

### 5c: 集成脚本端到端

```bash
cd /home/ubuntu/agentmail

# 干净环境: 删除已有配置
rm -f ~/.hermes/amail_gateway.json ~/.hermes/amail_bridge.toml

# 运行集成脚本 (Step 1 → Step 10)
./integrate.sh

# 验证点:
# Step 4: 选择 [3] bridge → 检测 IP → 部署 bridge → 启动
# Step 5: 写入 amail_gateway.json (确认无 delivery_mode)
# Step 8: 注册 profile (确认调 bridge API)
# Step 9: 诊断全部通过
# Step 10: 发送测试通过

# 二次运行 (幂等)
./integrate.sh
# 确认: 已有值作为默认值，不重复部署
```

### 5d: 端到端邮件流

```bash
# 1. 确认 bridge 在运行
curl http://127.0.0.1:38081/health

# 2. 确认 route 已注册
curl -s http://127.0.0.1:38081/api/v1/routes | python3 -m json.tool

# 3. 向 gateway 发送测试邮件
# (通过 SMTP 或 API — 取决于 gateway 部署)
```

### 5e: 确认列表

| 检查项 | 命令/方法 |
|--------|---------|
| bridge 编译 | `cargo build --release` |
| gateway 编译 | `cargo build --lib` |
| advanced 编译 | `cargo build --release` + `strings \| grep delivery_mode` = 0 |
| 可用性测试 | `./tests/availability_test.sh` 全 PASS |
| integrate.sh 语法 | `bash -n` |
| integrate.sh 完整运行 | 手动 Step 1-10 |
| integrate.sh 二次幂等 | 再次运行 |
| 文档无残留 | `grep -rn delivery_mode\|bridge_url docs/` |
| bridge route API | `curl POST /api/v1/routes` 返回 `{"status":"ok","webhook_url":"..."}` |
| pull 模式返回空 | `curl POST` with pull config → `{"webhook_url":""}` |
| _auto_activate_profile 端口刷新 | 改 config.yaml port + 重启 agent |
