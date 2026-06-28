# AgentMail

**让 AI 智能体像人一样收发邮件——与人类或其他智能体实时通信。**

AgentMail 将 [amail-gateway](https://github.com/metercai/amail-gateway) 集成到
[Hermes Agent](https://github.com/nousresearch/hermes-agent) 中，让您的 AI 智能体
能够通过标准 SMTP 收发邮件——无需 POP3/IMAP、无需轮询、无需配置邮箱。

---

## 适用场景

- 智能体通过邮件处理客户支持
- 多个智能体通过邮件线程协作
- 自动化报告和通知投递
- 人工审批的工作流
- 与现有邮件业务流程集成
- 智能体间通过 SMTP 通信

## 特色

- **零配置入站** — 基于 webhook，无需轮询，无需 IMAP
- **标准 SMTP 出站** — 非私有 API，适用于任何 SMTP 中继
- **端到端心跳** — 内置 ping/pong 测试验证全链路
- **多身份支持** — 一个 agent profile，通过 persona 前缀支持多个邮件身份
- **钩子生命周期** — profile 创建/删除时自动注册/注销
- **双语集成向导** — 交互式 `integrate.sh`，支持中英文
- **管道诊断** — `check_status.py` 一键验证全部 4 层

## 快速安装

### 前置条件

- [amail-gateway](https://github.com/metercai/amail-gateway)（已运行）
- [Hermes Agent](https://github.com/nousresearch/hermes-agent)（已安装）
- [amail-bridge](https://github.com/metercai/amail-bridge)（脚本自动部署）
- Python 3.10+

### 一键集成

```bash
git clone https://github.com/metercai/agentmail.git
cd agentmail
bash integrate.sh
```

向导将引导您完成：
1. 网关连通性检查
2. 域名配置（或通过激活码完成系统激活）
3. 快照和管理员邮箱设置
4. 桥接服务自动部署
5. 工具和技能安装
6. Webhook 补丁和 profile 注册
7. 全链路诊断（含 ping/pong 测试）
8. 收发验证

### 自动化集成

```bash
export AMAIL_URL=https://amail.token.tm
export AMAIL_ADMIN_KEY=your_admin_key_here
bash integrate.sh
```

## 架构

```
                         amail-gateway
                    (外部 SMTP 网关)
                            │
                     ┌──────┴──────┐
                     │             │
              ┌──────┴──────┐     SMTP
              │ amail-bridge│     (出站)
              │ (拉取/推送) │
              └──────┬──────┘
                     │ POST /webhooks/agentmail-inbound
              ┌──────┴──────┐
              │ Hermes Agent│
              │  (webhook)  │
              └──────┬──────┘
                     │ LLM + send_mail()
                     │
              ┌──────┴──────┐
              │ amail-gateway│
              │ (出站)      │
              └─────────────┘
```

## 使用注意事项

### 路径约定

所有运行时配置位于 `~/.agentmail/{system_id}/` 下。旧版 `~/.hermes/agentmail.json`
已不再使用，请勿依赖。

### API key 归属于 profile，邮件地址可细分到 persona

每个 Hermes profile（如 `default`、`ql-biopharm`）拥有独立的 API key。
根配置 `~/.agentmail/{system_id}/agentmail.json` 保存基础 profile 的 key。
命名 profile 的 key 保存在 `profiles/{name}/agentmail.json` 中。

邮件地址可以带有 **persona 前缀**：`support.agent@domain` 路由到 profile
`agent`，persona 为 `support`。智能体据此采用正确的身份回复邮件。
但 API key 绑定的是 profile，不是 persona。

激活命名 profile **不会**覆盖根 profile 的 key。

### 无向后兼容回退

所有工具和脚本仅从 `~/.agentmail/{system_id}/` 路径读取配置。如果您有
旧版部署文件在 `~/.hermes/` 下，请迁移它们。

### 重新集成

`integrate.sh` 是幂等的——重复运行会检测已有配置并跳过已完成步骤。
使用 `uninstall.sh` 完全清理后再重新集成。

### 心跳测试

```bash
python3 lib/check_status.py --ping
```

通过完整管道发送 ping 邮件 (SMTP → gateway → bridge → webhook) 并预期
pong 响应。在不调用 LLM 的情况下验证所有链路。

## 项目结构

```
├── integrate.sh              # 集成向导主脚本（支持中英文）
├── lib/
│   ├── helpers.sh            # UI 辅助函数 (step_*, info, ask_param)
│   ├── i18n.sh               # 中英文字符串
│   ├── check_status.py       # 管道诊断 + ping/pong
│   ├── deploy_bridge.py      # 桥接服务下载与部署
│   ├── register_profiles.py  # Profile 邮件注册
│   ├── send_welcome.py       # 发送/接收测试
│   ├── activate_system.py    # 产品激活码激活
│   └── hermes_gateway.sh     # 多 profile 网关管理
├── tools/
│   └── agentmail_tools.py        # Hermes Agent 运行时工具
├── patches/
│   ├── apply_webhook_patch.py
│   └── apply_profiles_patch.py
├── skill/                    # Hermes 技能定义
├── tests/                    # 集成测试
└── references/               # 设计文档与架构指南
```

## 相关项目

- [amail-gateway](https://github.com/metercai/amail-gateway) — AI 智能体 SMTP 邮件网关
- [amail-bridge](https://github.com/metercai/amail-bridge) — NAT 穿透 webhook 桥接
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — 个人 AI 智能体框架
