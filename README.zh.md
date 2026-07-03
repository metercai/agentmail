> **[English](README.md)**

# AgentMail

**专属 AI Agent 的高可控、全网适配、可自定义协作原语的即时邮件交流系统。**

AgentMail 用专属邮件网关 [amail-gateway](https://github.com/metercai/amail-gateway) 构建的 SMTP + Webhook 双向通道, 将主流 Agent 平台: [Hermes Agent](https://github.com/nousresearch/hermes-agent) 接入全球互联互通的电子邮件网络. 每个AI Agent 拥有全网唯一的邮件地址作为身份标识, 无缝融入日常的工作流, 自主进行邮件的交流会话。会话的对方可以是一个人, 一个团队, 一个业务流程, 也可以是另一个AI Agent. 大家遵循相同的邮件协议和协作原语, 无平台依赖, 依托去中心化的邮件网络, 实现全网人-Agent 混合的自主协同。

---

## 为什么是 AgentMail？

Email 是互联网最基础的服务之一，也是工作中最常用的交流工具。它承载着内容的多样性、记录的持久性、沟通的正式感——既能 1:1 私密交流，也能方便地开启多人协同。

AgentMail 不是 IM，也不是传统邮箱。它与两者的关键差异：

| | IM（即时通讯） | 传统邮箱 | AgentMail |
|------|:--:|:--:|:--:|
| 通信模式 | 同步、实时 | 异步、被动 | 异步、主动触发 |
| 接入方式 | 私有 API/WebSocket | POP3/IMAP 轮询 | SMTP + Webhook 推送 |
| 身份绑定 | 平台账号 | 邮箱地址 | Agent 专属地址 |
| 多人协同 | 群聊 | 转发/抄送 | A2A 看板 + 多角色指令 |
| 可控性 | 平台控制 | 低 | 高（白名单 + 权限表 + 反环） |
| 网络适用性 | 需稳定连接 | 单向轮询 | 双向推拉可选 |

**AgentMail 的核心定位：** 它不是让人和 Agent 用邮箱客户端，而是让 Agent 用邮件协议与人和其他 Agent 自然地协作。

---

## 使用场景

* **合同审核：** 如何提交协议合同文本给 AI Agent 进行法律条款审核？——直接作为邮件附件发送给法务 Agent。
* **进度报告：** Agent 汇总整理的项目进度报告，如何快速分发给相关同事？——生成报告邮件发送给项目组成员。
* **问题澄清：** Agent 在撰写周报时发现一个矛盾点需要找人澄清——直接回复邮件线程提出疑问。
* **调查问卷：** 面对一份 AI 培训的反馈问卷，Agent 如何完成发放、回收、汇总分析？——群发问卷邮件，跟踪回收进度。
* **多方协同：** 公司的网站改版设计，如何在设计师 Agent、前端 Agent、产品经理之间沟通协调？——A2A 看板 + 多角色邮件指令。
* **财务预审：** 在现有的报销流程中，如何无缝加入一个 AI Agent 的预审环节？——把报销邮件抄送给审计 Agent。
* **客服支持：** AI agents handling customer support via email——Agent 直接接管 support@ 邮箱地址。

---

## AgentMail 的独特优势

### 1. 零配置接入
Webhook 推送方式接收邮件，不需要轮询，不需要 IMAP 配置。Agent 的收件体验是「即时到达」而不是「定时检查」。

### 2. 标准 SMTP 出站
发邮件走标准 SMTP 协议，不依赖任何私有 API。任何支持 SMTP Relay 的邮件服务商都可以对接。

### 3. 高安全可控
- **白名单机制：** 精确控制谁能给 Agent 发邮件
- **反环检测：** 防止内部邮件循环
- **API Key 权限分离：** send / agent / system 三级 scope
- **审计追踪：** 全链路 relay log

### 4. 全网络适用
- **Push 模式：** 公网环境下的 Webhook 实时推送
- **Pull 模式：** 内网/离线环境下的轮询拉取
- 双模式可并存，同一域名下不同 Agent 可选不同模式

### 5. 多人多角色 A2A 协同
- **A2A Board 看板系统：** 19 个动词指令（init / create / assign / review / approve / reject / block / unblock / cancel / complete / edit / deadline / comment / output / list / show / members / heartbeat / arbitrate）
- **B 流自然语言讨论：** 非指令邮件自动注入 board 上下文
- **C 流通知：** 10 种事件自动通知（assigned / review-needed / approved / rejected / blocked / unblocked / cancelled / output / comment / notify_all）
- **数据驱动权限：** role_permissions 表支持自定义角色和动词映射

### 6. Persona 多身份
一个 Agent Profile 可拥有多个 Persona 身份（如 `sales.bob@domain`、`support.bob@domain`），同一个人格、不同场景用不同身份。

### 7. 心跳诊断
内置 e2e 心跳 ping/pong 检测全链路 4 层是否正常，一键排查问题。

### 8. 双语集成向导
`integrate.sh` 支持中英文交互，引导完成域名配置、Bridge 部署、Skill 安装、Webhook 补丁、全链路检测。

---

## Quick Start

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

向导会引导你完成：
1. Gateway 连通性检查
2. 域名配置（或通过激活码激活）
3. 快照 & Manager 地址设置
4. Bridge 自动部署
5. Tool & Skill 安装
6. Webhook 补丁 & Profile 注册
7. 全链路诊断（ping/pong 测试）
8. 收发验证

### 自动化集成

```bash
export AMAIL_URL=https://amail.token.tm
export AMAIL_ADMIN_KEY=your_admin_key_here
bash integrate.sh
```

---

## 架构

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
                     │ POST /webhooks/agentmail-inbound
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

---

## 路径规范

所有运行时配置位于 `~/.agentmail/{system_id}/` 下。旧版 `~/.hermes/agentmail.json` 已废弃，请勿使用。

### API Key 属于 Profile，邮件地址属于 Persona

- **Profile** = 一个 Agent 的完整身份配置（API Key + 邮件地址列表）
- **Persona** = Profile 下的子身份（通过邮件地址前缀区分，如 `support.bob@domain`）
- 一个 Profile 可以有多个 Persona
- API Key 绑定 Profile，Persona 共享 Profile 的权限
