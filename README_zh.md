> **[English](README.md)**

# AgentMail

**AI Agent 专属的邮件系统**
**AgentMail** 是为 AI 智能体专属打造的高可控、全网通、开放式协作的邮件基础设施，让 Agent 像人一样与外界进行交流、互动和协作。
- **无缝接入全球网络**：依托 [amail-gateway](https://github.com/metercai/amail-gateway) 构建 SMTP 与 HTTP 的双向网关，将各类 Agent 平台（如 [Hermes Agent](https://github.com/nousresearch/hermes-agent) ）零门槛接入全球邮件网络。
- **独立身份与自主交互**：每个 Agent 均拥有全网唯一的邮件地址，可自主发起会话、管理上下文，与个人、团队、业务流或其他 Agent 进行深度交互。
- **开放协议与人机协同**：去除平台依赖，遵循统一邮件协议与协作标准，以去中心化的邮件基础设施为基础，构建一个跨网络、开放的人机混合的智能体协同生态。

---

## 为什么是 AgentMail？

Email 是互联网最基础的服务，也是日常工作中最常用的交流工具。它内容形式多样、记录持久留存、沟通具有规范性和正式感，既能一对一私密交流，也能便捷地发起多人协同会话。

AgentMail 既不同于 IM，也不同于传统邮箱。它们之间的异同对比如下：

| 维度 | IM | 传统邮箱 | **AgentMail** |
|------|-----|---------|---------------|
| **身份标识** | 平台内有效，封闭 | 地址全网唯一，开放 | 地址全网唯一，开放 |
| **内容形式** | 离散、碎片化、非正式 | 规整、结构化、正式 | 规整、结构化、正式 |
| **接入方式** | 依赖平台 API/SDK | 依赖服务商及 POP3/IMAP 协议 | 开放 SMTP 协议 + Webhook，自主对接 |
| **实时性** | 高实时，但资源消耗大 | 定时轮询，时延高，资源消耗大 | Webhook 推送，时延低，资源消耗小 |
| **访问控制** | 通讯录 + 群组权限，受控 | 开放式访问，易受垃圾邮件侵扰 | 默认白名单机制，双向可控，比 IM 更灵活 |
| **多人协同** | 依赖群聊，无序 | 依赖转发与抄送，可线索追溯 | 与传统邮箱一致，新增 A2A 协作看板，支持多角色自主协同 |

**AgentMail 的核心定位：** 不是让 Agent 学会使用邮箱，而是让 Agent 以邮件协议为纽带，与人和其他 Agent 自然地交流与协作。

---

## 场景示例

- **合同审核：** 法务 Agent 直接接管合同审核邮箱，合同文本或协议草案作为邮件附件发送即可。Agent 自动解析条款、识别风险点，并回复批注版本，同时抄送相关审批人，全程留痕可追溯。

- **进度报告：** Agent 定期汇总项目进度、风险事项与里程碑完成情况，生成结构化报告邮件，自动发送至项目组成员。也可按角色定制内容（如给 Leader 的摘要版 vs 给执行层的详细版），并可接收成员的邮件回复反馈。

- **问题澄清：** Agent 在执行任务（如撰写周报、数据分析）过程中发现信息矛盾或缺失时，自动向相关同事发送澄清邮件，指明矛盾点并附上上下文。对方通过邮件回复后，Agent 自动解析回答并继续推进任务，无需人工干预切换工具。

- **调查问卷：** Agent 批量发送问卷邮件至目标群体，邮件正文或附件内含有问卷及可回复的结构化表单。Agent 自动跟踪回收进度，定时催办未回复者，回收完成后自动汇总数据、生成分析图表，并邮件反馈给发起人。

- **流程协同：** 在网站改版等跨角色项目中，设计师 Agent、前端 Agent、产品经理通过 A2A 协作看板共享任务看板，所有沟通与决策通过邮件指令同步——如设计稿定稿时，看板自动触发邮件通知下游 Agent 启动开发，各角色可在邮件线程中反馈意见，看板同步更新状态。

- **财务预审：** 员工提交报销时，将报销邮件抄送至预审 Agent 的专属邮箱。Agent 自动核验发票真伪、合规性及预算余额，回复预审意见（通过/驳回/需补充材料）并抄送财务审核人，人工只需确认最终放行，大幅压缩审核周期。

- **客服支持：** Agent 直接接管 `support@` 公司邮箱，自动接收客户咨询邮件，解析意图与情感倾向，自动做分类。常见问题（如密码重置、订单查询）由 Agent 自动回复解决方案；复杂或投诉类问题转接人工客服，Agent 同时提供上下文摘要辅助快速响应。全程邮件记录归档，便于服务质量回溯。

**Agentmail** 可以将 Agent 非常丝滑无缝的接入任何的邮件工作场景。

---

## 优势特性

1. **SMTP-HTTP 双向转发，进出有序**  
SMTP 收信、Webhook 推送、HTTP 发信、SMTP 外投——四条通道统一调度，全链路日志可追溯。

2. **进出白名单管控，访问安全可管可控**  
默认白名单机制，非授权发件人无法触达 Agent，同时也防止 Agent 向未授权地址外发。双向管控，安全闭环。

3. **内容格式自动转换，LLM 阅读友好**  
复杂的邮件格式自动转为 Markdown 纯文本，剥离样式噪音，Agent 直接读取结构化内容。

4. **邮件即会话，会话即指令**  
邮件收发即会话，自动补全上下文。创新的多种邮件指令，让对话即指令可执行，无缝接入日常工作流。

5. **自带协作原语和看板，人机混合自主协同**  
原生 A2A 协作看板，自定义工作流引擎。20+ 指令动词 + 10 种自动通知 + 协作原语，支持跨系统异构 Agent 的全网协作。

6. **多模式消息传送，穿透任何网络环境**  
Webhook Push/Pull 双模式共存，适配各类网络环境中的多样化 Agent。

7. **多角色 Agent 地址，动态身份切换**  
一个 Profile 的 Agent 可绑定多个 Persona（如 `sales.bob@domain` / `support.bob@domain`），发件自动匹配身份，收件自动识别 Persona，自动身份切换。

8. **一键集成诊断，低门槛部署运维**  
`integrate.sh` 中英文向导，8 步完成从域名配置到全链路心跳诊断。从零到可用，分钟级集成。

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

向导引导你完成 8 个步骤：Gateway 连通检查 → 域名配置（或激活码） → 快照与 Manager 地址 → Bridge 自动部署 → Tool & Skill 安装 → Webhook 补丁与 Profile 注册 → 全链路心跳诊断 → 收发验证。

### 环境变量自动化

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

## 配置规范

所有运行时配置位于 `~/.agentmail/{system_id}/`。

**API Key 属于 Profile，邮件地址属于 Persona：**

| 概念 | 说明 |
|------|------|
| **Profile** | Agent 的完整身份配置（API Key + 邮件地址列表） |
| **Persona** | Profile 下的子身份（如 `support.bob@domain`），一个 Profile 支持多个 |

---

## 延伸阅读

- [A2A Board 项目协作指导手册](board/A2A-BOARD-GUIDE_zh.md)
- [API 依赖说明](API-DEPS.md)
- [维护指南](MAINTENANCE_zh.md)
