# A2A Board — 使用指导手册

A2A Board 是 AgentMail 内置的多角色项目协作看板系统，通过**邮件指令**驱动任务流转，支持 AI Agent 与人类在同一看板上协同工作。

---

## 1. 核心概念

| 概念 | 说明 |
|------|------|
| **Board** | 一个项目看板，有唯一的 `board_id` 和 `board_email` |
| **Board Email** | `{short_id}.a2a@{domain}` 格式的专属邮件地址 |
| **指令流** | 指令邮件（`[A2A]` 前缀），Rust 闭环处理 19 个动词 |
| **会话流** | 成员互发 + CC Board 地址，自动注入 `board_id` / `board_role` / `from_role` |
| **通知流** | 事件通知邮件，10 种自动通知类型 |

---

## 2. 创建 Board

### 方式一：`[create]` 流（推荐）

Human 直接发邮件给 Orchestrator（不需要 board 地址预先存在）：

```
To:      orchestrator@shared.domain
Subject: [create] myproject: 网站改版项目协同看板

{
  "members": [
    {"email": "orchestrator@shared.domain", "role": "orchestrator", "display_name": "PM"},
    {"email": "verifier@shared.domain",     "role": "verifier",     "display_name": "QA"},
    {"email": "worker@shared.domain",       "role": "worker",       "display_name": "Dev"}
  ]
}
```

**约束：**
- `members` 中**必须**包含 `orchestrator` 和 `verifier`（缺一不可）
- 收件人**必须**是 `members` 中声明的 `orchestrator`
- `short_id` 从标题提取：`[create] {short_id}: {描述}`
- `board_id` / `board_email` / `gateway_url` 由系统自动计算

### 方式二：`[A2A] init`（已有 board 地址后使用）

```
To:      myproject.a2a@shared.domain
Subject: [A2A] init

{
  "members": [
    {"email": "orchestrator@shared.domain", "role": "orchestrator", "display_name": "PM"},
    {"email": "worker@shared.domain",       "role": "worker",       "display_name": "Dev"}
  ],
  "role_permissions": [
    {"role": "orchestrator", "verbs": ["create","assign","review","block","cancel","edit","output","notify","members","list","show","heartbeat"]},
    {"role": "verifier",     "verbs": ["verify","approve","reject","output","list","show","heartbeat"]},
    {"role": "worker",       "verbs": ["complete","commit","heartbeat","list","show"]}
  ]
}
```

`role_permissions` 可选，缺省使用安全默认值。

---

## 3. 角色与权限

| 角色 | 默认权限 |
|------|---------|
| **orchestrator** | init, create, assign, review, block, unblock, cancel, reassign, edit, deadline, output, notify, members, config, arbitrate, comment, list, show, heartbeat, gateway_info |
| **verifier** | verify, approve, reject, output, comment, list, show, heartbeat |
| **worker** | complete, commit, heartbeat, comment, list, show |
| **human** | create, unblock, reassign, comment, list, show, heartbeat |

**权限模型（增量覆盖）：**
- 系统始终以**安全默认值**为基线（以上表为准）
- `role_permissions` 字段为**增量覆盖**：指定了 role-verb 对则覆盖该 role 的默认值，未指定的 role 保持默认
- 默认值确保 `orchestrator`/`verifier`/`worker`/`human` 四角色都有适当的权限范围
- 同一成员可拥有多个 role（在 `members` 中出现多次）

**新增 role 无需改代码：**
1. 在 `members` 中写上新的 role 名
2. 在 `role_permissions` 中声明该 role 的 verb 映射
3. 在 `~/.agentmail/a2a_board/skills/role/{role}.md` 编写角色 prompt（可选）

---

## 4. 指令流 — 19 个动词指令

所有 指令流邮件格式：`Subject: [A2A] {verb} {task_id?}`，正文为 JSON。

### 4.1 任务管理

| 动词 | 发送者 | 说明 | 示例 |
|------|--------|------|------|
| `create` | orchestrator, human | 创建任务 | `[A2A] create` |
| `assign` | orchestrator | 分配任务 | `[A2A] assign T1` |
| `review` | orchestrator | 设置审阅者 | `[A2A] review T1` |
| `complete` | worker | 完成任务 | `[A2A] complete T1` |
| `cancel` | orchestrator | 取消任务 | `[A2A] cancel T1` |
| `edit` | orchestrator | 编辑任务 | `[A2A] edit T1` |
| `deadline` | orchestrator | 设截止日期 | `[A2A] deadline T1` |
| `reassign` | orchestrator | 重新分配 | `[A2A] reassign T1` |

**create 示例：**
```json
{
  "board_id": "abc123def45678901234",
  "tasks": [
    {"title": "设计首页 Logo", "body": "需要3个方案", "assignee": "worker@domain", "reviewer": "verifier@domain"},
    {"title": "修复登录 Bug",  "body": "iOS 端 crash", "assignee": "worker@domain"}
  ]
}
```

### 4.2 审阅流程

| 动词 | 发送者 | 说明 |
|------|--------|------|
| `verify` | verifier | 验证任务 |
| `approve` | verifier | 审阅通过 |
| `reject` | verifier | 审阅驳回 |

### 4.3 阻塞管理

| 动词 | 发送者 | 说明 |
|------|--------|------|
| `block` | orchestrator | 阻塞任务 |
| `unblock` | orchestrator, human | 解除阻塞 |

### 4.4 输出与交互

| 动词 | 发送者 | 说明 |
|------|--------|------|
| `output` | verifier | 提交任务产出 |
| `comment` | 所有人 | 添加评论 |
| `arbitrate` | orchestrator, verifier | 请求仲裁 |

### 4.5 查询

| 动词 | 说明 |
|------|------|
| `list` | 列出任务 |
| `show {task_id}` | 查看任务详情 |
| `members` | 查看成员 |
| `heartbeat {task_id}` | 更新任务心跳 |
| `gateway_info` | 查看 Gateway 信息 |

---

## 5. 会话流 — 成员间自然语言讨论

会话流通过 **成员互发邮件 + CC 抄送 Board 地址** 触发：

- **发件人 (FROM)：** 必须是 Board 成员
- **收件人 (TO)：** 必须是 Board 成员
- **抄送 (CC)：** 必须包含 Board 邮件地址（`{short_id}.a2a@{domain}`）

三者同时满足时，系统自动注入三个身份字段：

| 注入字段 | 含义 | 来源 |
|----------|------|------|
| `board_id` | Board 标识 | CC 中的 `.a2a` 地址解析 |
| `board_role` | 收件人角色 | TO 地址在 `board_members` 中的 role |
| `from_role` | 发件人角色 | FROM 地址在 `board_members` 中的 role |

**会话流邮件示例：**
```
From: worker@shared.domain
To:   orchestrator@shared.domain
CC:   myproject.a2a@shared.domain
Subject: Design review feedback for T1

首页 Logo 的配色需要调整，与品牌色不一致。
```

Agent (orchestrator) 收到后，自动注入 `board_id` / `board_role` / `from_role` 和对应的 `_role_prompt`（从 role md 文件加载，找不到回退 `common.md`）。可使用以下 toolset API 与 Board 交互：

| 工具 | 说明 |
|------|------|
| `board_task_show` | 查看任务详情 |
| `board_task_list` | 列出所有任务 |
| `board_members` | 查看成员列表 |
| `board_heartbeat` | 更新任务心跳


---

## 6. 通知流 — 事件通知

10 种自动通知，在 指令流指令执行后触发：

| 通知类型 | 触发事件 | 收件人 |
|----------|---------|--------|
| `assigned` | create / assign | 被分配者 |
| `review-needed` | review | 审阅者 |
| `approved` | approve | 被分配者 |
| `rejected` | reject | 被分配者 |
| `blocked` | block | 被分配者 + 抄送全 Board |
| `unblocked` | unblock | 被分配者 |
| `cancelled` | cancel | 全 Board |
| `output` | output | 全 Board |
| `comment` | comment | 审阅者（若 assignee 评论）|
| `notify_all` | init / 手动 | 全 Board |

通知邮件通过 Gateway 的 SMTP relay 发出，路由由调度器自动选择（同域内转 webhook，外域走 SMTP）。

---

## 7. Toolset API

Agent 通过以下 4 个 API 端点与 Board 交互：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/board/:board_id/tasks` | GET | 列出任务（支持 `?status=&assignee=`） |
| `/api/v1/board/:board_id/members` | GET | 列出成员（可选 `?email=` 过滤） |
| `/api/v1/board/:board_id/roles` | GET | 角色权限表（可选 `?role=` 过滤） |
| `/api/v1/board/:board_id/task/:task_id` | GET | 查看任务详情 |
| `/api/v1/board/:board_id/task/:task_id/heartbeat` | POST | 更新心跳 |

需 `X-Api-Key` 鉴权，返回 JSON。

---

## 8. Role Prompt 文件

每个 role 对应一个 Prompt 模板文件，位于：

```
~/.agentmail/a2a_board/skills/role/{role}.md
```

安装时自动从 `agentmail/skills/role/` 复制。支持 `{{VARIABLE}}` 模板占位符：

| 变量 | 含义 |
|------|------|
| `{{BOARD_ID}}` | Board 标识 |
| `{{BOARD_ROLE}}` | 当前角色 |
| `{{AGENTMAIL_ADDRESS}}` | Agent 邮件地址 |
| `{{INQUIRY_SENDER}}` | 发件人 |
| `{{INQUIRY_SUBJECT}}` | 邮件主题 |
| `{{SOUL_MD_CONTENT}}` | Agent 的 SOUL.md 内容 |
| `{{SKILLS_LIST}}` | 当前加载的 Skills 列表 |

**fallback 机制：** `{role}.md` 不存在 → `common.md` → 空字符串。

---

## 9. 典型工作流

```
1. Human 发送 [create] 邮件 → Board 创建，orchestrator 收到初始化确认

2. Orchestrator 发送 [A2A] create → 创建任务 T1, T2
   → Worker 收到 assigned 通知（通知流）

3. Orchestrator 发送 [A2A] review → 设置 verifier 为审阅者
   → Verifier 收到 review-needed 通知

4. Verifier 发送 [A2A] approve → T1 审阅通过

5. Worker 发送普通邮件（会话流）→ 讨论 T1 的实现细节

6. Worker 发送 [A2A] complete → T1 完成
   → Orchestrator 收到 approved 通知

7. 任何一个 Agent 通过 toolset API 查询 Board 状态
```

---

## 10. 测试

```bash
# 基础 E2E 测试（board 创建 + 任务 + API）
cd amail-gateway && bash tests/category-1-core.sh

# 全动词覆盖测试（19 verb + 通知流通知）
cd amail-gateway && bash tests/category-0-a2a-verbs.sh

# Agent 集成测试（per-recipient webhook + API + 会话流）
cd amail-gateway && bash tests/category-5-agent-integration.sh
```
