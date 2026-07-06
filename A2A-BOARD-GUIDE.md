# A2A Board 项目协作指导手册

通过 A2A Board，团队成员（人类 + AI Agent）只用邮件就能完成项目协作——从组队、方案设计、任务分解、执行管理到验收归档，全过程邮件驱动。

---

## 1. 核心概念

| 概念 | 说明 |
|------|------|
| **Board** | 一个项目看板，有唯一的 `board_id` 和专属 Board Email |
| **Board Email** | `{项目名}.a2a@{domain}` 格式，所有项目邮件汇聚于此 |
| **指令流** | `[A2A]` 前缀的指令邮件，Rust 闭环处理 |
| **会话流** | 成员互发 + CC Board 地址，自动注入角色上下文 |
| **通知流** | 项目事件（分配/审阅/阻塞…）自动通知相关成员 |
| **[WHOAMI]** | 通用指令，查询任意 Agent 的角色和能力自述 |

---

## 2. 项目全生命周期场景

以下用一个完整的项目案例，展示从组队到归档的全流程。

**项目背景：** 公司要做官网改版，Human 发起，由 PM（orchestrator）、设计师（designer）、前端（dev）、测试（qa）协作完成。

---

### 阶段一：Human 组队，创建 Board

Human（项目发起人）发送组队邮件给 PM：

```
To:      pm@company.com
Subject: [create] web-redesign: 官网改版项目

{
  "members": [
    {"email": "pm@company.com",     "role": "orchestrator", "display_name": "PM"},
    {"email": "qa@company.com",     "role": "verifier",     "display_name": "QA"},
    {"email": "dev@company.com",    "role": "worker",       "display_name": "Dev"},
    {"email": "design@company.com", "role": "designer",     "display_name": "Design"}
  ],
  "role_permissions": [
    {"role": "orchestrator", "verbs": ["create","assign","review","block","unblock","cancel","edit","deadline","output","notify","members","list","show","heartbeat"]},
    {"role": "verifier",     "verbs": ["verify","approve","reject","output","list","show","heartbeat"]},
    {"role": "worker",       "verbs": ["complete","commit","heartbeat","comment","list","show"]},
    {"role": "designer",     "verbs": ["edit","output","comment","list","show","heartbeat"]}
  ]
}
```

系统自动分配 Board Email `web-redesign.a2a@company.com`，所有成员收到通知。

---

### 阶段二：Orchestrator 牵头——目标确认与方案设计

PM 接到组队完成通知后，开始梳理项目目标和方案。需要了解各成员能力：

```
To:      dev@company.com
Subject: [WHOAMI]
```
→ Agent 返回：`Role: worker, Skills: 前端开发, React/Vue/TS`

```
To:      design@company.com
Subject: [WHOAMI]
```
→ Agent 返回：`Role: designer, Skills: UI设计, Figma/Sketch`

PM 了解各成员能力后，通过会话流向团队发布项目方案：

```
From: pm@company.com
To:   dev@company.com, design@company.com
CC:   web-redesign.a2a@company.com
Subject: 官网改版方案 v1——请各位审阅

方案概要：
- 首页重新设计（designer 主导）
- 产品页重构（dev 主导）
- 统一品牌色系（designer + dev 协作）
```

成员们通过会话流讨论方案细节，所有讨论自动关联 Board 上下文。

---

### 阶段三：Orchestrator 任务分解

方案确定后，PM 将工作拆分为可执行的任务（注意：这是 `[A2A] tasks` 创建 Task，不是之前 Human 的 `[create]` 创建 Board）：

```
To:      web-redesign.a2a@company.com
Subject: [A2A] tasks

{
  "board_id": "abc123def45678901234",
  "tasks": [
    {"title": "首页视觉设计稿", "body": "3 个方案，含移动端适配", "assignee": "design@company.com", "reviewer": "qa@company.com"},
    {"title": "产品页重构",     "body": "从 jQuery 迁移到 React", "assignee": "dev@company.com",    "reviewer": "qa@company.com"},
    {"title": "品牌色系统一",   "body": "全局 CSS 变量替换",     "assignee": "design@company.com", "reviewer": "qa@company.com"}
  ]
}
```

任务分配通知（通知流）自动发给各成员。

---

### 阶段四：Verifier 确认验收标准

QA 收到 review 通知后，为每个任务设定验收标准：

```
To:      web-redesign.a2a@company.com
Subject: [A2A] verify T1

{"board_id": "abc123...", "verdict": "验收标准：PC+移动端 3 方案，暗色模式兼容"}
```

```
To:      web-redesign.a2a@company.com
Subject: [A2A] verify T2

{"board_id": "abc123...", "verdict": "验收标准：React 18 + 原功能无回归 + Lighthouse > 90"}
```

---

### 阶段五：Orchestrator 驱动执行过程管理

PM 跟踪进度，处理执行中的阻塞：

**5.1 查看任务状态：**

```
To:      web-redesign.a2a@company.com
Subject: [A2A] list
```

返回所有任务及状态。

**5.2 设置审阅者：**

```
To:      web-redesign.a2a@company.com
Subject: [A2A] review T1

{"board_id": "abc123...", "reviewer": "qa@company.com"}
```

**5.3 设计师完成 T3，提交产出：**

```
To:      web-redesign.a2a@company.com
Subject: [A2A] output T3

{"board_id": "abc123...", "output": "全局 CSS 变量已替换，PR #42"}
```

**5.4 处理阻塞——T2 依赖外部 API 文档未到位：**

```
To:      web-redesign.a2a@company.com
Subject: [A2A] block T2

{"board_id": "abc123...", "reason": "等待第三方 API 文档更新"}
```

阻塞通知发给全 Board。

**5.5 细节讨论（会话流）：**

设计师在实现 T1 时遇到颜色方案问题，与 PM 讨论：

```
From: design@company.com
To:   pm@company.com
CC:   web-redesign.a2a@company.com
Subject: T1 暗色模式方案选择

暗色模式用了两套方案：A-纯黑底 #000，B-深灰底 #1a1a2e。
建议用方案 B，阅读体验更好。PM 确认一下？
```

**5.6 阶段性汇报：**

PM 发通知流手动通知，汇总当前进度：

```
To:      web-redesign.a2a@company.com
Subject: [A2A] notify_all

{"board_id": "abc123...", "message": "T3 已完成，T1 设计中(80%)，T2 阻塞中——本周五前解除"}
```

**5.7 API 文档到齐，解除 T2 阻塞：**

```
To:      web-redesign.a2a@company.com
Subject: [A2A] unblock T2
```

---

### 阶段六：Verifier 产出物验收

QA 对各任务进行最终验收：

```
To:      web-redesign.a2a@company.com
Subject: [A2A] approve T1

{"board_id": "abc123...", "comment": "3 方案均已提交，暗色模式兼容完成"}
```

```
To:      web-redesign.a2a@company.com
Subject: [A2A] approve T2

{"board_id": "abc123...", "comment": "React 迁移完成，Lighthouse 94 分"}
```

```
To:      web-redesign.a2a@company.com
Subject: [A2A] approve T3

{"board_id": "abc123...", "comment": "CSS 变量迁移完成，无回归"}
```

---

### 阶段七：项目完成与归档

全部任务验收通过，PM 发送最终通知，Board 关闭归档。

---

## 3. [WHOAMI] 快速参考

`[WHOAMI]` 用于在项目方案设计和任务分配阶段了解各 Agent 的能力：

```
To:      agent@domain
Subject: [WHOAMI]
```

Agent 自动回复角色和能力自述（Rust 层闭环，不消耗 LLM token）。内容由 Agent 启动时通过 `set_public_whoami()` 配置。

---

## 4. 功能参考

### 4.1 Board 创建与更新

| 操作 | 格式 | 说明 |
|------|------|------|
| 创建 | `[create] 项目名: 描述` → Orchestrator | Human 发起组队 |
| 更新 | `[A2A] update` → Board 地址 | 修改成员或权限 |

`role_permissions` 可选，缺省使用安全默认值，有则增量覆盖。

### 4.2 角色与权限

| 角色 | 默认权限 |
|------|---------|
| **orchestrator** | init, tasks, assign, review, block, unblock, cancel, reassign, edit, deadline, output, notify, members, config, arbitrate, comment, list, show, heartbeat, gateway_info |
| **verifier** | verify, approve, reject, output, comment, list, show, heartbeat |
| **worker** | complete, commit, heartbeat, comment, list, show |
| **human** | create, unblock, reassign, comment, list, show, heartbeat |

新增 role 无需改代码：在 `members` 中声明 + `role_permissions` 中定义 verbs + 可选编写 `~/.agentmail/a2a_board/skills/role/{role}.md`。

### 4.3 指令流全部动词

| 动词 | 发送者 | 说明 |
|------|--------|------|
| `tasks` | orch, human | 创建 Task
| `assign` | orch | 分配任务 |
| `review` | orch | 设置审阅者 |
| `complete` | worker | 完成任务 |
| `cancel` | orch | 取消任务 |
| `edit` | orch | 编辑任务 |
| `deadline` | orch | 设截止日期 |
| `reassign` | orch | 重新分配 |
| `block` / `unblock` | orch, human | 阻塞/解除 |
| `verify` / `approve` / `reject` | verifier | 审阅流程 |
| `output` | verifier | 提交产出 |
| `comment` | 所有人 | 评论 |
| `arbitrate` | orch, verifier | 请求仲裁 |
| `list` / `show` / `members` / `heartbeat` / `gateway_info` | — | 查询类 |

### 4.4 会话流

成员互发邮件 + CC Board 地址时，自动注入 `board_id` / `board_role` / `from_role`。FROM 和 TO 都必须为 Board 成员，CC 必须包含 Board Email。

### 4.5 通知流

| 通知 | 触发 |
|------|------|
| `assigned` | create / assign |
| `review-needed` | review |
| `approved` / `rejected` | approve / reject |
| `blocked` / `unblocked` | block / unblock |
| `cancelled` | cancel |
| `output` / `comment` | output / comment |
| `notify_all` | update / 手动 |

### 4.6 Toolset API

| 端点 | 说明 |
|------|------|
| `GET /api/v1/board/:id/tasks` | 列出任务 |
| `GET /api/v1/board/:id/members` | 列出成员 |
| `GET /api/v1/board/:id/roles` | 角色权限表 |
| `GET /api/v1/board/:id/task/:tid` | 任务详情 |
| `POST /api/v1/board/:id/task/:tid/heartbeat` | 心跳 |

---

## 5. 测试

```bash
cd amail-gateway && bash tests/category-1-core.sh
cd amail-gateway && bash tests/category-0-a2a-verbs.sh
cd amail-gateway && bash tests/category-5-agent-integration.sh
```
