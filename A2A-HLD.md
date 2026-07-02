# A2A项目看板系统 — 概要设计

> 基于 agentmail 的开放跨系统 A2A 项目协作看板（a2a_board）

---

## 一、背景与目标

### 解决的问题

多个 agent 分布在不同的 Hermes 实例或非 Hermes 系统上，需要协作完成一个项目。每个 agent 有 agentmail 地址作为身份标识，通过邮件通信。需要一套**看板（board）**来组织、分配、追踪和验收工作——看板是协作能落实下来的具体产物和表现。

### 核心约束

1. **纯邮件通信** — 所有交互基于 agentmail，人类管理员使用普通邮件客户端
2. **Board 是忠实的记录者** — Board 有专属 agentmail 地址，它是看板数据的宿主。Board 不是 agent，不需要 LLM，直接在 amail-gateway 上通过 Rust 层处理邮件指令并回复
3. **Orchestrator 负责驱动力** — 分解→提议→评议→共识→执行→巡视→回收
4. **Verifier 闸门** — 最终输出的唯一放行口，需按验收标准审查，同时检查中间产物是否按编排方案流转
5. **仅 Orchestrator 和 Verifier 可提请管理员仲裁**
6. **能力自述而非外部指定** — 每个 agent 基于自身上下文（SOUL.md + 已加载 SKILL）定义自己的角色和能力
7. **编排是团队共识而非一人决策** — 通过评议达成集体共识
8. **非中心化** — 不同 agent 可能隶属不同的 amail-gateway 系统，但 Board 的 agentmail 地址固定，锁定数据存储所在的 gateway

---

## 二、参与方与角色

```
Project Team
├── Human Admin        (普通邮箱)
│   └── 确认编排方案、仲裁争议
├── Orchestrator       (agentmail 地址)
│   └── 能力发现→编排提议→巡视→回收→可提请仲裁
├── Verifier(s)        (agentmail 地址，可多人，各有专长)
│   └── 按验收标准审阅交付物→检查中间产物流转合规→
│       可提请仲裁→最终输出放行
├── Worker(s)          (agentmail 地址，可多人)
│   └── 能力自述→执行任务→完成/阻挡
├── Board              (agentmail 地址，宿主于特定 amail-gateway)
│   └── 记录状态→查询反馈→状态通知→gateway 信息提供
│       不需要 LLM，Rust 直接处理
└── Other Participants (agentmail 地址)
    └── 评议编排方案
```

### Board 角色详解

Board 是项目看板的核心实体，拥有专属 agentmail 地址（如 `board@postgres-mig.a2a`）。

**Board 是什么：**
- 有专属 agentmail 地址，可接收和回复邮件
- 不是 Hermes agent，不需要 agent session 和 LLM
- 宿主在特定的 amail-gateway 上（该 gateway 的存储路径下保存 board.db）
- 所有项目状态记录和查询反馈由 Board 的 agentmail 地址完成

**Board 能做什么：**
- 记录任务状态变化（complete/block/heartbeat 等）
- 查询并回复任务或成员信息（show/list/members）
- 提供自身 gateway 信息（gateway-info）
- 校验并执行最终输出（output）
- 发送状态变化通知给相关方

**Board 的地址用于锁定数据存储所在的 gateway：** 所有参与者向 Board 地址发送指令邮件，SMTP 路由保证邮件到达该网关。其他参与者通过 `[A2A] gateway-info` 获取该 gateway 的 HTTP URL，此后可直接通过 REST API 查询 board 数据。

---

## 三、通信模型

### 邮件类型

| 类型 | Subject 格式 | 说明 |
|------|-------------|------|
| 指令 | `[A2A] <verb> [<task-id>]` | 发给 Board，Rust/Python 处理 |
| 通知 | `[A2A] <event> <task-id>` | Board 发出的状态变化通知 |
| 能力问询 | `[A2A] capability-inquiry` | Orchestrator 向成员发出的自述请求 |
| 编排提议 | `[Proposal] <项目名> 方案 v<N>` | Orchestrator 发给全体的评议邮件 |
| 仲裁请求 | `[A2A] arbitrate` | 提请 Admin 裁决 |
| 仲裁回复 | `Re: [A2A] arbitrate` | Admin 的回复 |
| Gateway 查询 | `[A2A] gateway-info` | 查询 Board 所在 gateway 的 HTTP URL |
| 日常对话 | 无特殊前缀 | 普通 agentmail 对话 |

### 邮件流向

```
A: 成员 → Board（指令邮件）
   所有 [A2A] verb 指令 → Board 处理并直接回复
   Rust 闭环（16 个 verb）或 Python preprocessor（3 个 verb）
   无 LLM 参与

B: 成员 ↔ 成员（对话邮件）
   [A2A] capability-inquiry / [Proposal] 评议 / 日常讨论
   经过 agent session，LLM 处理
   Cc: Board 存档但 Board 不处理

C: Board → 成员（通知邮件）
   状态变化通知（assigned / review-needed / unblocked / output 等）
   Rust notify 模块自动发送，纯机械通知，无 LLM 参与
```

---

## 四、业务流程

### 完整编排流程

```
Phase 0: 项目初始化
  Admin → Board: [A2A] init（成员列表）
  Board: 写入 board.db + 通知全体

Phase 1: 能力发现
  Orchestrator → 每个成员: [A2A] capability-inquiry
  各成员回复能力自述（基于 SOUL.md + 已加载 SKILL）
  Orchestrator 汇总为能力矩阵

Phase 2: 编排共识
  Orchestrator 撰写方案 v1（附 assignee/reviewer 理由）
  → [Proposal] 发给全体参与者
  → 参与者评议 → Orchestrator 修订
  → 重复直到无异议 → @admin 确认

Phase 3: 执行
  Orchestrator → Board: [A2A] create
  Board: 创建 task + 通知 assignees

Phase 4: 协作流转
  Worker → Board: [A2A] complete → Rust 闭环 + 通知
  Verifier → Board: [A2A] approve/reject → Rust 更新状态
  Orchestrator 巡视（a2a toolset 或 [A2A] list）

Phase 5: 完成
  Verifier → Board: [A2A] output
  Board: 校验中间产物合规 + 通知全员
  7 天后自动归档
```

### B流对话类型

B流（成员间对话）是项目协作的核心，包含以下正式化对话类型：

| 对话类型 | 发起方 | 参与方 | 目的 |
|---------|--------|--------|------|
| B1: 能力问询 | Orchestrator | 每个人 | 编排前置：了解成员能力范围 |
| B2: 编排方案评议 | Orchestrator | 全体 | 对任务分解和分配达成共识 |
| B3: 验收标准确认 | Verifier | 全体 | 对最终产出物的检验标准达成共识 |
| B4: 阶段汇报 | 任意成员(通常是阶段负责人) | 全体 | 阶段性进展总结与调整 |
| B5: 互评 | 任意成员 | 指定对象 | 针对具体任务或协作质量的评价 |
| B6: 任务讨论 | 任意成员 | 相关人员 | 针对某个 task 的执行细节讨论 |
| B7: Admin 确认 | Orchestrator | Admin | 编排方案/验收标准的最终审批 |

所有 B 流对话通过标准邮件线程进行，Cc: Board 存档。Board 不处理这些邮件的内容，只记录事件日志。

### 能力发现（B1）

Orchestrator 向每个项目成员发送 `[A2A] capability-inquiry`。成员回复能力自述：
- 角色定位（来自 SOUL.md）
- 加载的 SKILL 列表
- 专长领域
- 相关历史经验
- 限制/做不了什么

处理流程：
1. Preprocessor 检测到 capability-inquiry 邮件
2. 读取目标 agent 的 SOUL.md 和 SKILL 列表（文件 I/O）
3. 填充 whoami.md 模板的 4 个占位符（agentmail 地址、SOUL.md 全文、SKILL 列表、问询者地址）
4. 放行给 agent session（不设 _skip_delivery）
5. LLM 看到填充后的 whoami.md，按要求格式（或默认格式）组装能力声明
6. LLM 调用 send_mail() 回复问询者
7. Session 结束

非 Hermes 系统的 agent（没有 ~/.hermes/profiles/ 目录）无 SOUL.md 可读，降级到 agentmail SKILL 中的能力自述章节由 LLM 自解析。

### 编排共识（B2）

编排不是一人决策，而是团队达成共识的过程：
1. Orchestrator 基于能力矩阵撰写方案 v1（每个 task 附 assignee 理由）
2. [Proposal] 发给全体参与者
3. 每个参与者根据自己的经验和判断评议
4. Orchestrator 收集反馈、修订方案
5. 重复直到无新增异议
6. @admin 最终确认后执行

### 验收标准确认（B3）

编排方案被 Admin 确认后，Verifier 基于方案中的 task 分解和最终产出物描述，发起验收标准确认：

1. Verifier 撰写验收标准草案（基于编排方案的 output task 描述）
2. [Criteria] 发给全体参与者
3. 参与者回复：标准是否清晰、可执行、无遗漏
4. Verifier 修订
5. 重复直到达成共识
6. 标准写入 board.db（作为 output task 的 metadata）

验收标准写入后，Verifier 在最终 output 时对照此标准逐项检验。

### 阶段汇报（B4）

项目按编排方案分 Phase 执行。每个 Phase 完成后，Orchestrator 或 Human Admin 发起阶段汇报（Worker 不发起阶段汇报，Worker 通过 `[A2A] complete`、`[A2A] heartbeat` 或 B5/B6 讨论来表达进度）：

```
Subject: [Report] Phase 1: 调研阶段 — 完成汇报
Cc: board@project.a2a

Phase 1 完成情况：
  T1: 成本分析 ✅ (researcher-a)
  T2: 性能测试 ✅ (researcher-b)
  T3: GCP 成本调研 ✅ (researcher-a)
 审阅记录: 3/3 通过

遇到问题:
  - AWS 账单数据延迟 2 天，已协调

Phase 2 准备:
  - 预计按时开始
  - 建议 T4 增加安全评估项（待评议）
```

Orchestrator 或 Verifier 回复确认或提出调整建议。

### 互评（B5）

项目进行中或完成后，成员间可以发起互评：

```
Subject: [Review] 关于 T1 执行质量的评价
To: orchestrator@hermes.a2a
Cc: board@project.a2a

评价对象: researcher-a
任务: T1 成本分析
评价: 数据建模扎实，文档清晰。建议：下次可以提前标注数据源假设。
```

互评记录存入 task_events，用于后续项目的成员能力参考。

### 任务讨论（B6）

针对特定 task 的执行细节讨论：

```
Subject: T2 pgbench 参数讨论
To: researcher-b@sys-b
Cc: board@project.a2a

T2 的 pgbench 模拟负载，
建议调整 scale factor 到 1000 以覆盖 5TB 场景。
你认为呢？
```

讨论过程自动由 email threading 维护，email_summary() 可查询。

### Admin 确认（B7）

编排方案和验收标准在团队达成共识后，需要 Admin 做最终确认。Admin 的确认需要 Board 记录在案，项目才可进入可执行状态。

编排方案确认的邮件格式：

```
To: admin@company.com
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v3

编排方案经全体评议已达成一致，@admin 请确认执行。
```

Admin 回复 "确认执行" → 邮件同时到达 Orchestrator（To）和 Board（Cc）。

**Board 侧：** Rust A2aInterceptor 检测到 Cc 中的确认邮件，记录 `task_events: admin_confirmed`，更新 `plan_confirmed_at`。

**Orchestrator/Verifier 侧：** LLM 识别确认，Orchestrator 执行 [A2A] create，Verifier 启动验收标准确认。

```
编排方案确认前: project 可查询但不可执行
编排方案确认后: project.plan_confirmed_at ≠ null → 可执行 create
验收标准确认后: project.criteria_confirmed_at ≠ null → Verifier 可做 output 前校验
output 后: project.status = "completed"
7 天后: project.status = "archived"
```

---

## 五、总体架构

### 系统分层

```
┌──────────────────────────────────────────────────────┐
│               Communication Layer                     │
│           email / SMTP（所有交互通过邮件）              │
│  Human Admin / Orchestrator / Verifier / Worker       │
└────────────────────┬─────────────────────────────────┘
                     │ SMTP
┌────────────────────▼─────────────────────────────────┐
│            Board Data Layer (Rust amail-gateway)      │
│                                                       │
│  board.db ← 状态机执行、数据持久化                     │
│  A2aInterceptor ← [A2A] 指令邮件处理（16 verb 闭环）  │
│  HTTP API ← REST 查询接口                            │
│  notify ← 邮件通知（EmailFactory → SMTP）             │
│                                                       │
│  Board 不是 agent，不需要 LLM                          │
└────────────────────┬─────────────────────────────────┘
                     │ webhook (复杂命令)
┌────────────────────▼─────────────────────────────────┐
│          Logic Processing Layer (Python Hermes)       │
│                                                       │
│  webhook.py ← 接收复杂命令（create/arbitrate/init）   │
│  a2a_board.py preprocessor ← 处理特殊逻辑             │
│  agent session ← LLM 推理（日常对话/[Proposal]评议）  │
│  tools + SKILLs ← agent 能力扩展                      │
└──────────────────────────────────────────────────────┘
```

### 非中心化架构

```
多个 amail-gateway 系统：
  amail-gateway A                    amail-gateway B
  ├─ Hermes agent 1                  ├─ Hermes agent 3
  ├─ 自定义 agent 2                  └─ LLM API agent 4
  └─ ...

Board 的 agentmail 地址固定（如 board@project.a2a）
  → SMTP 路由锁定数据存储所在的 gateway
  → [A2A] gateway-info 获取该 gateway 的 HTTP URL
  → 之后可通过 REST API 直接访问 board 数据
```

### 各组件职责

| 组件 | 位置 | 功能 |
|------|------|------|
| Rust A2aInterceptor | `board/interceptor.rs` | 处理 [A2A] 指令邮件，简单命令闭环 |
| Rust Command Handler | `board/commands.rs` | 所有 verb 的业务逻辑 + 授权 + output 校验 |
| Rust API | `board/handlers.rs` | HTTP REST 接口 |
| Rust DB | `board/db.rs` | board.db 的 CRUD 操作 |
| Rust Notify | `board/notify.rs` | EmailFactory 发送邮件通知 |
| Rust Archiver | `board/archiver.rs` | 完成 7 天后自动归档 |
| Python Preprocessor | `a2a_board.py` | 处理 B 流邮件（能力问询（填充 whoami.md 数据给 LLM 格式化回复） + [Proposal] 评议注入 session 和角色 prompt） |
| Python Tools | `a2a_tools.py` | a2a toolset（高频查询优化） |
| Agentmail SKILL | `agentmail/SKILL.md` | 通用邮件处理 + 能力自述章节 |
| Role Prompts | `agentmail/a2a_roles/` | 角色行为纯文本 prompt（orchestrator/verifier/worker） |

---

## 六、关键设计概念

### 两套信息体系

| 维度 | 个人认知（per-agent） | 集体共识（board DB） |
|------|---------------------|---------------------|
| 存储 | `agent_state[agent_addr]` | `board.db` 项目文件 |
| 写入者 | agent 自身 | 全体参与者通过共识流程 |
| 视角 | 主观、个性化 | 客观、可验证 |
| 内容 | "我对 researcher-a 的印象" | "T1 已完成，T2 被退回" |
| 同步 | 通过邮件自然流动 | — |

### 审阅机制

审阅基于 task 的 `reviewer` 字段（email），不是项目级配置。`reviewer` 可以是任意项目成员，不限于 Verifier：有 reviewer → complete 进入 `reviewing` 状态；无 reviewer → complete 直接 `done` 并 promote。

### Verifier 审查标准

| 审查维度 | 检查内容 |
|---------|---------|
| 任务完成度 | 所有 task 状态是否为 done |
| 流转合规 | 中间产物是否按编排方案依赖关系流转 |
| 审阅记录 | 被审阅的 task 是否有 approve 事件 |
| 交付物质量 | task summary 和 metadata 是否完整 |

前三个维度由 Rust output handler 代码级校验，第四个维度由 Verifier 的角色 prompt 指导 LLM 判断。

### Session 复用

所有发给 Board 的 `[A2A]` 指令邮件不需要 session 复用（Rust 拦截器直接处理，不走 webhook）。需要 session 复用的只有复杂命令（create/arbitrate/init）和日常对话，通过 `_a2a_session_key` 实现。

---

## 七、非功能需求

- **数据隔离**：每项目一个独立 board.db 文件
- **自动归档**：output 完成 7 天后自动归档，不支持恢复
- **跨项目依赖**：不支持，前置条件在项目启动前必须解决
- **通知一致性**：Rust 和 Python 两条通知路径汇合在 EmailFactory，共享 SPF/DKIM/relay
