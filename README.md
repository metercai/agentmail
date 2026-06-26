# AgentMail

**Real-time, human-like email communication for AI agents — with humans or other agents.**

**让 AI 智能体像人一样收发邮件——与人类或其他智能体实时通信。**

---

AgentMail wires [amail-gateway](https://github.com/metercai/amail-gateway) into
[Hermes Agent](https://github.com/nousresearch/hermes-agent), giving your AI
agent the ability to send and receive email through standard SMTP — no POP3/IMAP,
no polling, no mailbox configuration.

AgentMail 将 [amail-gateway](https://github.com/metercai/amail-gateway) 集成到
[Hermes Agent](https://github.com/nousresearch/hermes-agent) 中，让您的 AI 智能体
能够通过标准 SMTP 收发邮件——无需 POP3/IMAP、无需轮询、无需配置邮箱。

---

## Use Cases / 适用场景

| English | 中文 |
|---------|------|
| AI agents handling customer support via email | 智能体通过邮件处理客户支持 |
| Multi-agent collaboration over email threads | 多个智能体通过邮件线程协作 |
| Automated reporting and notification delivery | 自动化报告和通知投递 |
| Human-in-the-loop approval workflows | 人工审批的工作流 |
| Integration with existing email-based business processes | 与现有邮件业务流程集成 |
| Agent-to-agent (A2A) communication via SMTP | 智能体间通过 SMTP 通信 |

## Features / 特色

- **Zero-config inbound** — webhook-based, no polling, no IMAP
  **零配置入站** — 基于 webhook，无需轮询，无需 IMAP
- **Standard SMTP outbound** — no proprietary API, works with any SMTP relay
  **标准 SMTP 出站** — 非私有 API，适用于任何 SMTP 中继
- **End-to-end heartbeat** — built-in ping/pong test verifies the full pipeline
  **端到端心跳** — 内置 ping/pong 测试验证全链路
- **Persona support** — one agent, multiple email identities
  **多身份支持** — 一个智能体，多个邮件身份
- **Hook-based lifecycle** — auto-register/deregister on profile creation/deletion
  **钩子生命周期** — profile 创建/删除时自动注册/注销
- **Bilingual integration wizard** — interactive `integrate.sh` with EN/ZH support
  **双语集成向导** — 交互式 `integrate.sh`，支持中英文
- **Pipeline diagnostics** — `check_status.py` verifies all 4 layers in one command
  **管道诊断** — `check_status.py` 一键验证全部 4 层

## Quick Start / 快速安装

### Prerequisites / 前置条件

- [amail-gateway](https://github.com/metercai/amail-gateway) (running)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) (installed)
- [amail-bridge](https://github.com/metercai/amail-bridge) (auto-deployed by script)
- Python 3.10+

### One-command integration / 一键集成

```bash
git clone https://github.com/metercai/agentmail.git
cd agentmail
bash integrate.sh
```

The wizard will guide you through:
1. Gateway connectivity check
2. Domain configuration (or activation via product code)
3. Snapshot & manager address setup
4. Bridge auto-deployment
5. Tool & skill installation
6. Webhook patching & profile registration
7. Full pipeline diagnostics with ping/pong test
8. Send/receive verification

向导将引导您完成：
1. 网关连通性检查
2. 域名配置（或通过激活码）
3. 快照和管理员邮箱设置
4. 桥接服务自动部署
5. 工具和技能安装
6. Webhook 补丁和 profile 注册
7. 全链路诊断（含 ping/pong 测试）
8. 收发验证

### Manual steps / 分步执行

```bash
# Environment variables for automation
export AMAIL_URL=https://amail.token.tm
export AMAIL_ADMIN_KEY=your_admin_key_here

# Run integration step by step
bash integrate.sh
```

## Architecture / 架构

```
                         amail-gateway
                    (external SMTP gateway)
                            │
                     ┌──────┴──────┐
                     │             │
              ┌──────┴──────┐     SMTP
              │ amail-bridge│     (outbound)
              │ (pull/push) │
              └──────┬──────┘
                     │ POST /webhooks/amail-inbound
              ┌──────┴──────┐
              │ Hermes Agent│
              │  (webhook)  │
              └──────┬──────┘
                     │ LLM + send_mail()
                     │
              ┌──────┴──────┐
              │ amail-gateway│
              │ (outbound)  │
              └─────────────┘
```

## Usage Notes / 使用注意事项

### Path convention / 路径约定

All runtime config lives under `~/.agentmail/{system_id}/`. The legacy
`~/.hermes/amail.json` is no longer used — do not rely on it.

所有运行时配置位于 `~/.agentmail/{system_id}/` 下。旧版 `~/.hermes/amail.json`
已不再使用，请勿依赖。

### Persona keys are isolated / 身份密钥隔离

Each email persona (e.g. `support.agent@domain`) has its own API key.
Root config `~/.agentmail/{system_id}/amail.json` holds only the base email's
key — persona keys live in `profiles/{name}/amail.json`. Activation of a
persona does NOT overwrite the root key.

每个邮件身份（如 `support.agent@domain`）拥有独立的 API key。根配置
`~/.agentmail/{system_id}/amail.json` 仅保存基础邮箱的 key——身份密钥
保存在 `profiles/{name}/amail.json`。激活身份不会覆盖根 key。

### No backward-compat fallback / 无向后兼容回退

All tools and scripts read config from `~/.agentmail/{system_id}/` paths only.
If you have older deployments with files under `~/.hermes/`, migrate them.

所有工具和脚本仅从 `~/.agentmail/{system_id}/` 路径读取配置。如果您有
旧版部署文件在 `~/.hermes/` 下，请迁移它们。

### Re-running integration / 重新集成

`integrate.sh` is idempotent — re-running detects existing config and skips
completed steps. Use `uninstall.sh` to fully clean up before a fresh start.

`integrate.sh` 是幂等的——重复运行会检测已有配置并跳过已完成步骤。
使用 `uninstall.sh` 完全清理后再重新集成。

### Ping/pong test / 心跳测试

```bash
python3 lib/check_status.py --ping
```

Sends a ping email through the full pipeline (SMTP → gateway → bridge → webhook)
and expects a pong response. Verifies all links without invoking the LLM.

通过完整管道发送 ping 邮件 (SMTP → gateway → bridge → webhook) 并预期
pong 响应。在不调用 LLM 的情况下验证所有链路。

## Project Structure / 项目结构

```
├── integrate.sh              # Main integration wizard (EN/ZH)
├── lib/
│   ├── helpers.sh            # UI helpers (step_*, info, ask_param)
│   ├── i18n.sh               # Bilingual strings
│   ├── check_status.py       # Pipeline diagnostics + ping/pong
│   ├── deploy_bridge.py      # Bridge download & deployment
│   ├── register_profiles.py  # Profile email registration
│   ├── send_welcome.py       # Send/receive test
│   ├── activate_system.py    # Product code activation
│   └── hermes_gateway.sh     # Multi-profile gateway management
├── tools/
│   └── amail_tools.py        # Hermes Agent runtime tools
├── patches/
│   ├── apply_webhook_patch.py
│   └── apply_profiles_patch.py
├── skill/                    # Hermes skill definitions
├── tests/                    # Integration tests
└── references/               # Design docs & architecture guides
```

## Related Projects / 相关项目

- [amail-gateway](https://github.com/metercai/amail-gateway) — SMTP email gateway for AI agents
- [amail-bridge](https://github.com/metercai/amail-bridge) — NAT traversal bridge for webhook delivery
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — Personal AI agent framework
