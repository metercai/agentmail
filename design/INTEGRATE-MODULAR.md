# integrate.sh 模块化分解方案

## 目标

将 1100+ 行的单文件拆分为主脚本 + 子模块，降低复杂度，提高可维护性。

## 分解结构

```
agentmail/
├── integrate.sh          (~400 lines)  主流程编排
├── lib/
│   ├── i18n.sh           (~200 lines)  中英文字符串定义
│   ├── helpers.sh        (~40 lines)   step_begin/ok/warn/fail/info/ask_param
│   ├── deploy-bridge.sh  (~120 lines)  桥接部署 + 域级 key + bridge key
│   ├── install-tools.sh  (~40 lines)   amail_tools.py 安装
│   ├── patch-webhook.sh  (~25 lines)   webhook 预处理器 patch
│   ├── patch-profiles.sh (~90 lines)   profile hooks patch + 已有 profile 注册
│   ├── diagnostics.sh    (~20 lines)   verify_integration 诊断
│   └── send-test.sh      (~60 lines)   在线收发测试
```

## 主脚本保留内容 (~400 lines)

- `set -eo pipefail`，颜色，语言选择
- `source lib/helpers.sh`，`source lib/i18n.sh`
- Step 1: gateway_url（交互 + 探测）
- Step 2: 认证方式（admin_key / product_code）
- Step 3: 域名输入（查询 + 选择 + 创建）
- Step 4: 配置收集（snapshot + manager_address + webhook）
- Step 5: 保存配置 / 激活系统
- Step 5a: source lib/deploy-bridge.sh（域级 key + 桥接）
- Step 6: source lib/install-tools.sh
- Step 7: source lib/patch-webhook.sh
- Step 8: source lib/patch-profiles.sh
- Step 9: source lib/diagnostics.sh
- Step 10: source lib/send-test.sh
- 完成摘要

## 各子脚本接口

每个子脚本通过 env 变量接收参数，通过 `step_begin/ok/warn/fail` 输出状态：

| 脚本 | 输入 env | 输出变量 |
|------|---------|---------|
| deploy-bridge.sh | ADMIN_KEY, SYSTEM_ID, AMAIL_DOMAIN, GATEWAY_URL, WEBHOOK_HOST, WEBHOOK_MODE, USE_PRODUCT_CODE | ADMIN_KEY, SYSTEM_ADMIN_KEY |
| install-tools.sh | SCRIPT_DIR, HERMES_DIR, TOOLS_PY | — |
| patch-webhook.sh | HERMES_DIR, SCRIPT_DIR | — |
| patch-profiles.sh | HERMES_DIR, SCRIPT_DIR, GATEWAY_URL, ADMIN_KEY | — |
| diagnostics.sh | GATEWAY_URL, ADMIN_KEY, SCRIPT_DIR | — |
| send-test.sh | GATEWAY_URL, ADMIN_KEY, SYSTEM_ID, AMAIL_DOMAIN | — |

## 优势

- 主脚本从 1100 行降到 ~400 行
- 子脚本可独立测试（mock env vars + bash -n）
- 桥接部署逻辑可被 standalone 脚本复用
- 语言字符串独立管理，翻译者只需编辑 i18n.sh
- 每个子脚本功能内聚，未来修改影响范围明确

## 风险

- `source` 需要子脚本和主脚本在同一目录树下
- 子脚本数量增加，打包/分发需注意完整性
- 需要验证所有 `source` 路径在 `curl | bash` 模式下也能工作
