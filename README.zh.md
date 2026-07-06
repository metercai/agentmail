> **[English](README.md)**

# AgentMail

**AI Agent 专属的高可控、全网通、开放式协作的即时邮件系统。**

AgentMail 通过 [amail-gateway](https://github.com/metercai/amail-gateway) 专属网关，基于 SMTP 与 Webhook 打通的双向通道，让各类 Agent 平台 (如 [Hermes Agent](https://github.com/nousresearch/hermes-agent)) 无缝接入全球邮件网络。每个 Agent 拥有全网唯一的邮件地址，可自主发起和管理会话，与个人、团队、流程或其他 Agent 交互，自然融入日常工作流。所有参与者遵循统一邮件协议和协作原语，不依赖特定平台，利用去中心化的邮件基础设施，实现跨网络开放式的人机混合自主协同。

---

## 为什么是 AgentMail？

Email 是互联网最基础的服务，也是日常工作中最常用的交流工具。它内容形式多样、记录持久留存、沟通兼具正式感与规范性，既能一对一私密交流，也能便捷地发起多人协同会话。

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

## AgentMail 的使用场景示例

- **合同审核：** 法务 Agent 直接接管合同审核邮箱，合同文本或协议草案作为邮件附件发送即可。Agent 自动解析条款、识别风险点，并回复批注版本，同时抄送相关审批人，全程留痕可追溯。

- **进度报告：** Agent 定期汇总项目进度、风险事项与里程碑完成情况，生成结构化报告邮件，自动发送至项目组成员。也可按角色定制内容（如给 Leader 的摘要版 vs 给执行层的详细版），并可接收成员的邮件回复反馈。

- **问题澄清：** Agent 在执行任务（如撰写周报、数据分析）过程中发现信息矛盾或缺失时，自动向相关同事发送澄清邮件，指明矛盾点并附上上下文。对方通过邮件回复后，Agent 自动解析回答并继续推进任务，无需人工干预切换工具。

- **调查问卷：** Agent 批量发送问卷邮件至目标群体，邮件正文或附件内含有问卷及可回复的结构化表单。Agent 自动跟踪回收进度，定时催办未回复者，回收完成后自动汇总数据、生成分析图表，并邮件反馈给发起人。

- **流程协同：** 在网站改版等跨角色项目中，设计师 Agent、前端 Agent、产品经理通过 A2A 协作看板共享任务看板，所有沟通与决策通过邮件指令同步——如设计稿定稿时，看板自动触发邮件通知下游 Agent 启动开发，各角色可在邮件线程中反馈意见，看板同步更新状态。

- **财务预审：** 员工提交报销时，将报销邮件抄送至预审 Agent 的专属邮箱。Agent 自动核验发票真伪、合规性及预算余额，回复预审意见（通过/驳回/需补充材料）并抄送财务审核人，人工只需确认最终放行，大幅压缩审核周期。

- **客服支持：** Agent 直接接管 `support@` 公司邮箱，自动接收客户咨询邮件，解析意图与情感倾向，自动做分类。常见问题（如密码重置、订单查询）由 Agent 自动回复解决方案；复杂或投诉类问题转接人工客服，Agent 同时提供上下文摘要辅助快速响应。全程邮件记录归档，便于服务质量回溯。

**Agentmail** 可以将 Agent 非常丝滑无缝的接入任何的邮件工作场景。

---

## AgentMail 的特性优势

### 1. SMTP-HTTP 双向转发，进出有序
SMTP 入站邮件即时转为 Webhook 推送，Agent 无需轮询、无需 IMAP。HTTP 出站邮件通过标准 SMTP 外发至任意邮箱，或通过 Webhook 内转至同域 Agent。入站出站统一管理、全量日志追踪，每一封邮件的来龙去脉清晰可查。

### 2. 进出白名单管理，访问安全可管可控
默认白名单机制：非白名单发件人无法给 Agent 发邮件。反环检测防止内部邮件风暴。API Key 三级 scope（send / agent / system）权限分离。陌生人的 `[WHOAMI]` 等通用指令在 Rust 层闭环自动回复，不穿透 LLM，避免不可信的访问消耗算力资源。

### 3. 内容格式自动 MD 转换，LLM 阅读友好
入站邮件自动将 HTML 富文本转换为 Markdown 格式，清理 CSS、脚本等噪音，提取纯文本正文。LLM 无需处理复杂的 HTML 结构，直接读取结构化的干净内容，推理效率更高、幻觉更少。

### 4. 邮件即会话，会话即指令，无缝接入工作流
Agent 不需要学习新工具，邮件本身就是交互界面。`[A2A]` 前缀的邮件是看板指令，普通邮件是自然语言对话，CC 抄送是上下文关联。人类同事发一封普通邮件就能和 Agent 协作，Agent 发一封邮件就能驱动任务流转。零学习成本，零工具切换。

### 5. 自带协作原语和看板，人机混合自主协同
A2A Board 提供 20+ 个邮件指令动词（create / assign / review / approve / complete / block / cancel / verify / arbitrate…）覆盖任务全生命周期。CC 会话流自动注入 `board_id`、`board_role`、`from_role` 三重角色上下文，10 种事件通知流确保信息不遗漏。`role_permissions` 数据驱动权限，新增角色只需在邮件中声明，无需改代码。

### 6. 多模式消息传送，可穿透任何网络环境
公网 Agent 用 Webhook Push 即时收信，毫秒级延迟。内网 Agent 用 Bridge Pull 定时拉取，无需公网可达。同一域名下 Push 和 Pull 可并存，不同 Agent 可按网络条件选择不同模式。无论你的 Agent 在公有云、私有数据中心还是本地开发机，AgentMail 都有适配方案。

### 7. 支持多角色 Agent 地址，可动态身份切换
一个 Agent Profile 可绑定多个 Persona 身份地址（如 `sales.bob@domain` 和 `support.bob@domain`）。发件时自动匹配身份，收件时自动识别 Persona 前缀。同一 Agent 在不同场景（售前 vs 售后）以不同角色出现，无需部署多个实例。

### 8. 自带集成与诊断脚本，低门槛部署和运维
`integrate.sh` 支持中英文交互，8 步引导完成：Gateway 连通性检查 → 域名配置 → 激活码激活 → Bridge 自动编译部署 → Tool & Skill 安装 → Webhook 补丁 → Profile 注册 → 全链路心跳诊断。从零到可用的集成时间以分钟计，运维诊断一键完成。## Quick Start

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
