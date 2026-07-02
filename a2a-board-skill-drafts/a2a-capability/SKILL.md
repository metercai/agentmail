---
name: a2a-capability
description: Universal capability-inquiry handler — respond to Orchestrator's discovery requests with self-described capabilities from SOUL.md and loaded SKILLs.
version: 1.0.0
author: a2a_board
metadata:
  hermes:
    tags: [a2a, capability, discovery]
    requires_toolsets: [agentmail]
---

# A2A Capability

这是一个通用 SKILL，适合任意 agent 加载（不限于 Worker/Orchestrator/Verifier）。它的唯一用途是处理来自 Orchestrator 的 `[A2A] capability-inquiry` 邮件。

---

## 行为

### 收到 [A2A] capability-inquiry 邮件

```
From: orchestrator@hermes.a2a
Subject: [A2A] capability-inquiry
Body:
  project: postgres-migration
  请描述你的能力范围和专长
```

处理流程：

```
1. 确认发送者是已知的 Orchestrator（通过 contact_profile() 确认）
2. 从自身上下文中提取：
   
   a. 角色定位 —— SOUL.md 定义的角色
      如果找不到 SOUL.md，用默认描述
   
   b. 加载的 SKILL 列表 —— 当前会话中已加载的所有 skill 名称
      具体位置：您可以看到自己的 system prompt 中 "Available skills:" 列表
   
   c. 专长领域 —— 基于已加载 skill 推断
      从 skill 名称和描述中提取您擅长的领域
   
   d. 历史经验 —— 从 email_summary() 中查找相关项目
      搜索过往项目中您参与过的类似任务
   
   e. 限制 —— 您确定自己不能做的
      诚实描述，不要勉强接受不擅长的任务

3. 回复结构化邮件
```

---

## 回复格式模板

```
Subject: Re: [A2A] capability-inquiry

email: researcher-a@sys-a.a2a
role: <从 SOUL.md 提取的角色定位>

skills_loaded:
  - agentmail
  - data-analysis
  - aws-cost

expertise:
  - AWS 服务定价模型与成本建模
  - 跨云厂商 TCO 对比分析
  - 大数据量下的存储成本估算

relevant_experience:
  - mysql-migration-2025（5TB 数据迁移 TCO 对比）
  - cloud-cost-optimization（年节省 200k 优化方案）

constraints:
  - 不擅长数据库性能基准测试
  - 没有安全合规审计经验
  - 不熟悉阿里云
```

---

## 关键约束

- **诚实自述**——不要夸大能力，不要接受不擅长的任务。项目质量依赖于每位成员的诚实评估。
- **专长基于已加载 SKILL**——你只能做你的 SKILL 支持的事。如果某个 SKILL 没加载，就说不会。
- **限制要明确写出**——这是帮助 Orchestrator 做正确分配的最重要信息。
- **不需要验证发送者身份**——Orchestrator 的身份由项目共识保证。如有疑问，可通过 `contact_profile()` 查询发送者的 `relationship` 字段。

---

## 使用场景

每个项目成员加载此 SKILL 即可参与能力发现：

```yaml
# 任意 profile 的 config.yaml
skills:
  - agentmail
  - a2a-capability
  # 其他业务 SKILL...
```

不需要要成为 Worker/Verifier/Orchestrator。只需要 agentmail + a2a-capability，就能在项目编排阶段提供能力自述。
