# 编排方案：能力发现与共识达成

## 一、背景

Orchestrator 做任务编排时，必须知道每个成员的实际能力。**能力不是人类管理员简单设定的，而是每个 agent 基于自己的 SOUL.md 和加载的 SKILL 自述的。**

编排不是 Orchestrator 一人的决策，而是团队通过评议达成共识的过程。

---

## 二、能力发现流程

### 阶段 0：初始化（Admin 提供起点）

Admin 的 init 邮件提供基本信息——这只是**发现起点**，不是最终定位：

```
To: board@postgres-mig.a2a
Subject: [A2A] init
Body:
  project: postgres-migration
  members:
    - orchestrator@hermes.a2a: orchestrator
    - researcher-a@sys-a.a2a: worker (hint: 成本分析)
    - researcher-b@sys-b.a2a: worker (hint: 性能评估)
    - synthesizer@sys-c.a2a: worker (hint: 综合报告)
    - verifier@hermes.a2a: verifier
    - admin@company.com: human
```

Board 写入 kanban DB 作为初始 `project_members` 表。

### 阶段 1：能力自述（Orchestrator 遍寻每个成员）

Orchestrator 向每个成员发送能力问询邮件：

```
From: orchestrator@hermes.a2a
To: researcher-a@sys-a.a2a
Subject: [A2A] capability-inquiry
Body:
  project: postgres-migration
  请简述：
  - 你的角色定位
  - 你加载的 SKILL（决定你能做什么）
  - 你的专长领域
  - 相关历史经验
  - 你做不了什么
```

每个成员收到邮件后，SKILL 指导它回复能力自述。**回复内容来自 agent 自身的上下文——SOUL.md 和已加载的 SKILL：**

```
From: researcher-a@sys-a.a2a
To: orchestrator@hermes.a2a
Subject: Re: [A2A] capability-inquiry
Body:
  email: researcher-a@sys-a.a2a
  role: 云成本分析师
  skills_loaded: [agentmail, data-analysis, aws-cost-tools]
  expertise:
    - AWS 服务定价模型与成本建模
    - 跨云厂商 TCO 对比分析
    - 大数据量下存储成本估算
  relevant_experience:
    - mysql-migration-2025（5TB 数据迁移 TCO 对比）
    - cloud-cost-optimization（年节省 $200k 优化方案）
  constraints:
    - 不擅长数据库性能基准测试
    - 没有安全合规审计经验
    - 仅熟悉 AWS/GCP，不熟悉阿里云
```

收到所有成员回复后，Orchestrator 汇总为**团队能力矩阵**：

```
## 团队能力矩阵

| 成员 | 角色自述 | 专长领域 | 限制 |
|------|---------|---------|------|
| researcher-a@sys-a | 云成本分析师 | AWS 成本建模,TCO 对比 | 不熟悉阿里云 |
| researcher-b@sys-b | 性能工程师 | 数据库基准测试,延迟分析 | 不擅长成本计算 |
| synthesizer@sys-c | 技术写作 | 技术报告,数据分析 | 无量化建模能力 |
| verifier@hermes.a2a | 架构审阅 | 数据库架构,迁移方案 | 不执行具体分析 |
```

### 阶段 2：编排方案撰写

Orchestrator 基于能力矩阵，为每个 task 匹配最合适的 assignee，并在方案中说明理由：

```
## 编排方案 v1

### Phase 1：调研（并行执行）

T1: AWS 成本分析
  assignee: researcher-a@sys-a   ← 理由：专长 AWS 成本建模 + 迁移 TCO 经验
  reviewer: verifier@hermes.a2a   ← 理由：需要架构审阅确认成本模型
  描述：对比 AWS Aurora / GCP Cloud SQL 在 5TB / 10k QPS 下的 3 年 TCO

T2: 性能基准测试
  assignee: researcher-b@sys-b   ← 理由：数据库基准测试专长
  reviewer: null                  ← 理由：标准化测试流程，不需审阅
  描述：运行 pgbench 模拟 500GB / 10k QPS 负载

→ Phase 1 完成后调整 Phase 2 方案

### Phase 2：综合（串行执行）

T3: 综合推荐
  assignee: synthesizer@sys-c     ← 理由：技术写作专长，汇总 T1+T2
  reviewer: verifier@hermes.a2a   ← 理由：推荐结论需架构审阅
  依赖: [T1, T2]

T4: 决策备忘录
  assignee: synthesizer@sys-c     ← 理由：续写
  reviewer: verifier@hermes.a2a   ← 理由：最终输出需 Verifier 放行
  依赖: [T3]

### 输出
output: verifier@hermes.a2a
```

### 阶段 3：团队评议（共识形成）

Orchestrator 将方案发给所有参与者：

```
From: orchestrator@hermes.a2a
To: 全体参与者
Subject: [Proposal] Postgres 迁移 — 编排方案 v1
Body:
  (上述编排方案)

  请评议：
  1. 角色定位是否准确？
  2. 任务分配是否合理？
  3. 审阅者指定是否合适？
  4. 依赖关系是否正确？

  每位成员请根据自己的经验做出判断。
```

每个参与者根据自身视角进行评议：

```
From: researcher-b@sys-b.a2a
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v1
Body:
  整体方案合理。两点建议：
  1. T1 的 reviewer 建议增加 researcher-a 做交叉检视——成本模型的数据源需要确认。
     不过 researcher-a 是 T1 的 assignee，自检不合适。
     建议 reviewer 改为 synthesizer@sys-c，他过往有成本数据核验经验。
  2. 我近期做过类似的 pgbench 测试，可以 in 2 天内完成 T2，不需要 reviewer。
```

```
From: verifier@hermes.a2a
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v1
Body:
  同意大部分安排。三个意见：
  1. T1 的 reviewer 我建议空着，researcher-a 在成本分析方面是我见过最可靠的。
     如果需要双重确认，Phase 1 完成后我整体审阅。
  2. T4 产出后我会严格审阅，如果质量不达标会打回修订。
  3. 补充建议：Phase 1 增加 T3: GCP 成本调研（并行），
     assignee: researcher-a（利用 T1 的调研成果顺便做）。
     这样 Phase 2 可以同时覆盖 AWS 和 GCP 方案。
```

### 阶段 4：修订与共识

Orchestrator 收集所有评议，修订方案，在修订版中回应每条反馈：

```
From: orchestrator@hermes.a2a
Subject: [Proposal] Postgres 迁移 — 编排方案 v2
Body:
  根据反馈修订：

  变更说明：
  - v1 T1 reviewer: verifier → 空（采纳 Verifier 建议，Phase 1 后整体审阅）
  - v1 新增 T3: GCP 成本调研（采纳 Verifier 补充建议）
    assignee: researcher-a（利用 T1 调研同步进行）
  - v2 T2 维持无 reviewer（researcher-b 自评 2 天完成，无人异议）

  请各位确认。如无异议请回复 +1。
  如有异议请说明理由。
```

收到共识后（全员 +1 或无人反对），@admin 确认：

```
From: orchestrator@hermes.a2a
To: admin@company.com
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v2
Body:
  编排方案经全体评议已达成一致。
  变更记录：
  - v1: 初始方案（4 tasks）
  - v2: 新增 T3 + 调整 reviewer（基于 Verifier 和 researcher-b 反馈）

  @admin 请确认执行。
```

```
From: admin@company.com
Subject: Re: [Proposal] Postgres 迁移 — 编排方案 v2
Body: 确认执行。
```

### 阶段 5：执行

Orchestrator 执行 `[A2A] create`，所有任务的 `assignee` 和 `reviewer` 按共识后的 v2 方案写入。

---

## 三、关键设计要点

| 环节 | 谁 | 做什么 | 输入 | 输出 |
|------|---|--------|------|------|
| 能力自述 | 每个成员 | 基于 SOUL.md + SKILLs 自述能力 | 问询邮件 | 能力声明 |
| 能力汇总 | Orchestrator | 汇总为能力矩阵 | 所有成员回复 | 能力矩阵 |
| 方案撰写 | Orchestrator | 匹配能力与任务，附理由 | 能力矩阵 + 目标 | 编排方案 v1 |
| 方案评议 | 每个成员 | 基于自身经验和判断审阅方案 | 编排方案 | 评议意见 |
| 修订共识 | Orchestrator | 收集反馈，修订，确认共识 | 评议意见 | 编排方案 vN |
| 审批 | Admin | 最终确认 | 共识后的方案 | 确认执行 |
| 执行 | Orchestrator | create 任务到 Board | 确认 | kanban tasks |

### 共识达成条件

方案达成共识的标志：
1. 所有参与者回复 `+1` 或无异议
2. 如有异议，Orchestrator 修订后再次征求意见
3. 重复直到无新增异议
4. @admin 做最终确认

### 不需要新增基础设施

| 需要的能力 | 已有机制 |
|-----------|---------|
| 发送问询邮件 | `send_mail`（agentmail toolset） |
| 接收并处理问询 | 入站 email + agent SKILL 处理 |
| 成员自述能力 | SKILL 指导 LLM 从自身上下文提取 SOUL.md + SKILLs |
| 方案邮件 + 评议线程 | 标准 email threading |
| Admin 确认 | 普通邮件回复 |
| create 执行 | `[A2A] create` |

### 新增 SKILL

`a2a-capability` SKILL（可选，供任意 agent 加载）：

```
## 能力问询处理

收到 [A2A] capability-inquiry 邮件时：
1. 从自身上下文中提取：
   - SOUL.md 中定义的角色定位
   - 已加载的 SKILL 列表
   - 过往相关经验
2. 回复结构化能力声明
```
