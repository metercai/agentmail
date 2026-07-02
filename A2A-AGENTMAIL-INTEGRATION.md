# a2a_board — Agentmail 集成侧实施计划

> 基于 agentmail 的 A2A 项目协作看板 — Hermes agent 侧改动

---

## 概述

Agentmail 集成侧包含 5 个模块的改动，全在 `~/.hermes/` 和 `agentmail/tools/` 路径下，不涉及 Rust amail-gateway。

### 模块清单

| # | 模块 | 路径 | 工作量 | 前置 |
|---|------|------|--------|------|
| 1 | a2a_board.py preprocessor | `agentmail/tools/a2a_board.py` | 中 | 熟悉现有 preprocessor 注册模式 |
| 2 | 角色行为 prompt × 3 | `agentmail/a2a_roles/*.md` | 小 | 确定角色动作清单 |
| 3 | whoami.md prompt 模板 | `agentmail/skill/whoami.md` | 小 | 确定占位符列表 |
| 4 | a2a toolset × 4 | `tools/a2a_tools.py` | 中 | Rust API 就绪 + tool 注册机制 |
| 5 | Webhook patch 更新 | `lib/*.py`（patch 脚本） | 中 | 理解现有 patch 结构 |
| 6 | agentmail_tools.py 注册 | `tools/agentmail_tools.py` | 小 | 理解 registry 模式 |
| 7 | agentmail SKILL 更新 | `~/.hermes/skills/agentmail/SKILL.md` | 小 | 确定 A2A 相关指导内容 |

---

## 1. a2a_board.py preprocessor

### 文件路径

`agentmail/tools/a2a_board.py`

### 职责

在 webhook 预处理器链中运行。检测入站邮件的 Subject，对 A2A 相关邮件执行对应逻辑：

- 能力问询 → 读取 SOUL.md + SKILL 列表 → 填充 whoami.md → 放行给 LLM
- A2A / Proposal / Criteria / Report / Review / Confirm / Discuss 邮件 → 注入 `_a2a_session_key` 和 `_role_prompt`
- 非 A2A 邮件 → 直接 pass，不处理

### 关键依赖

```python
# 已有可用依赖
from agentmail_tools import send_mail, _GatewayClient
from tools.agentmail_tools import PREPROCESS_REGISTRY  # 注册点

# 新增工具函数
def read_soul_md(profile: str) -> str       # 读 ~/.hermes/profiles/<name>/SOUL.md
def read_skills(profile: str) -> list[str]   # 读 config.yaml 中 skills 列表
def read_role_prompt(role: str) -> str        # 读 ~/.hermes/skills/agentmail/a2a_roles/<role>.md
def fill_whoami_template(soul, skills, payload) -> str  # 替换占位符
def extract_board_id(subject, body, headers) -> str | None  # 从 Board-ID 头提取
def extract_project_id(...) -> str            # 从上下文提取 board_id（备用方案）
def detect_role(sender_email: str, board_id: str) -> str | None  # 从 board_members 查角色
def resolve_profile(agent_email: str) -> str | None  # email → profile 名
```

### 执行逻辑

```python
def a2a_board_preprocessor(payload, headers):
    subject = payload.get("subject", "").strip()
    sender = payload.get("from", "")
    target = payload.get("to", "")

    # ── Step 1: 提取 board_id（从 Board-ID 头或 Subject 或 body） ──
    board_id = extract_board_id(subject, payload.get("body", ""), headers)

    # ── Step 2: 能力问询 ──
    if "[A2A] capability-inquiry" in subject.upper():
        profile = resolve_profile(target)
        if profile:
            soul = read_soul_md(profile)
            skills = read_skills(profile)
            payload["_capability_body"] = fill_whoami_template(
                soul, skills, target, sender, subject)
            payload["_inquire_sender"] = sender
        # 放行给 LLM（不设 _skip_delivery）
        return payload

    # ── Step 3: B 流对话邮件（需要 session 复用的） ──
    a2a_prefixes = ("[A2A]", "[PROPOSAL]", "[CRITERIA]",
                    "[REPORT]", "[REVIEW]", "[DISCUSS]", "[CONFIRM]")
    if subject.upper().startswith(a2a_prefixes):
        if board_id:
            payload["_capability_body"] = fill_whoami_template(
                soul, skills, target, sender, subject)
            payload["_inquire_sender"] = sender
        else:
            # 放行给 LLM（不设 _skip_delivery）
            return payload

    # ── Step 4: 非 A2A 邮件 ──
    return payload
```

### 注册

在 `agentmail_tools.py` 文件底部追加：

```python
# a2a_board preprocessor 注册
try:
    from tools.a2a_board import a2a_board_preprocessor
    register_preprocessor("a2a_board", a2a_board_preprocessor)
except ImportError:
    pass  # a2a_board 未安装，跳过
```

### 注册时机

安装脚本 `install-tools.sh` 中执行 `cp` 和 `pip install` 后自动生效。

### 测试边界

| 场景 | 预期 |
|------|------|
| 普通邮件（无任何 A2A 前缀） | payload 原样返回，无副作用 |
| capability-inquiry + 有 profile | _capability_body 被填充，放行 LLM |
| capability-inquiry + 无 profile | payload 原样返回，agentmail SKILL 兜底 |
| [A2A] complete T1（A 流指令） | A 流已被 Rust 拦截器闭环，不会走到这里 |
| [Proposal] + 有 board_id | _a2a_session_key + _role_prompt 注入 |
| [Discuss] + 无 board_id | payload 原样返回（边界情况） |

---

## 2. 角色行为 prompt × 3

### 文件路径

```
agentmail/a2a_roles/
├── orchestrator.md
├── verifier.md
└── worker.md
```

### 生效方式

不写入 SKILL.md。preprocessor 在检测到 B 流邮件时，查 sender 在 board_members 中的角色，读取对应角色的 prompt 文件，将其内容设置为 `payload["_role_prompt"]`。Webhook handler 在构建 prompt 时拼接到 user message 尾部：

```python
role_prompt = payload.get("_role_prompt", "")
if role_prompt:
    prompt = f"{prompt}\n\n---\n{role_prompt}"
```

### 内容来源

详细角色技能点见 `A2A-DETAILED-DESIGN.md` 第十一节"角色技能矩阵"。每个 prompt 包含：

**orchestrator.md：**
- A 流可发起的指令（create/block/cancel/reassign/edit/deadline/comment/arbitrate）
- B 流可发起的对话（capability-inquiry、[Proposal]、[Report]、[Review]、任务讨论、Admin 确认）
- B 流应接收的回复（评议反馈、草案验收、Admin 确认 → 下一步）
- C 流应应对的通知（blocked → 介入协调、output → 存档）
- 规则：不自己执行 task、不跳过评议、先 comment 再 arbitrate、toolset 优先

**verifier.md：**
- A 流可发起的指令（approve/reject/output/block/comment/arbitrate）
- B 流可发起的对话（[Criteria] 验收标准、[Review]、任务讨论）
- B 流应接收的回复（评议反馈 → 修订标准）
- C 流应应对的通知（review-needed → 核心职责！output → 完成）
- 规则：对照 task body + 验收标准审阅、output 前检查流转合规、先沟通再仲裁

**worker.md：**
- A 流可发起的指令（complete/heartbeat/block/comment）
- A 流不可做的事（approve/output/create/cancel/arbitrate）
- B 流可发起的对话（[Review]、任务讨论）
- B 流应接收的回复（capability-inquiry → 回复自述、[Proposal] → 评议）
- C 流应应对的通知（assigned → 执行、rejected → 修订后重新 complete）
- 规则：遇到不可抗力先 block、complete 带 summary、长任务发 heartbeat、tool 优先

---

## 3. whoami.md prompt 模板

### 文件路径

`agentmail/skill/whoami.md`

### 占位符

| 占位符 | 预处理器填入 | 来源 |
|--------|------------|------|
| `{{AGENTMAIL_ADDRESS}}` | 接收问询的 agent 的 email | payload["to"] |
| `{{SOUL_MD_CONTENT}}` | SOUL.md 全文 | `read_soul_md(profile)` |
| `{{SKILLS_LIST}}` | 已加载 SKILL 列表 | `read_skills(profile)` |
| `{{INQUIRY_SENDER}}` | 问询者的 email | payload["from"] |
| `{{INQUIRY_SUBJECT}}` | 原邮件 Subject | payload["subject"] |

### 模板内容

```markdown
# whoami — 能力自述 prompt

## 你的身份

- **email address**: `{{AGENTMAIL_ADDRESS}}`

## 你的角色定义（SOUL.md）

```
{{SOUL_MD_CONTENT}}
```

## 你已加载的 SKILL

```
{{SKILLS_LIST}}
```

## 任务

请根据以上**真实数据**（不是你的记忆，是上面给你的数据），
以结构化格式回复能力自述。回复格式：

```
email: {{AGENTMAIL_ADDRESS}}
role: <从 SOUL.md 提取的角色定位>
skills_loaded: [<逐行列>]
expertise: [<专长领域>]
constraints: [<做不了的事>]
```

如果问询者指定了格式，优先使用对方要求的格式。

## 回复方式

使用 `send_mail()` 发送回复邮件给问询者：

- **to**: `{{INQUIRY_SENDER}}`
- **subject**: `Re: {{INQUIRY_SUBJECT}}`
- **body**: 上述能力自述

## 规则

1. 仅使用以上提供的真实数据，不要猜测你没有的 SKILL 或能力
2. constraints 比其他字段更重要——诚实列出做不到的事
3. 发送回复后结束，不需要进一步对话
```

---

## 4. a2a toolset × 4

### 文件路径

`tools/a2a_tools.py`

### 注册方式

在 `agentmail_tools.py` 中用 `registry.register()` 模式注册。

### tool 清单

```python
# tools/a2a_tools.py

def a2a_show(task_id: str) -> str:
    """查询任务详情。返回 task 的所有字段（body、status、assignee、reviewer 等）。
    比发 [A2A] show 邮件更快，无 SMTP 往返。"""
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    board_id = resolve_board_from_task(task_id)
    result = client._request("GET",
        f"/api/v1/board/{board_id}/task/{task_id}")
    return json.dumps(result, indent=2)


def a2a_list(board: str, status: str = "", assignee: str = "") -> str:
    """按条件过滤 task 列表。支持 status、assignee 过滤。
    常用于 Orchestrator 巡视（Orchestrator 定期查看 running/blocked 状态的 task）。"""
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    query = {}
    if status: query["status"] = status
    if assignee: query["assignee"] = assignee
    result = client._request("GET",
        f"/api/v1/board/{board}/tasks", params=query)
    return json.dumps(result, indent=2)


def a2a_members(board: str) -> str:
    """查询某 Board 的成员列表及角色（orchestrator / verifier / worker）。
    编排前由 Orchestrator 确认参与者，或 Verifier 检查审阅者范围。"""
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    result = client._request("GET",
        f"/api/v1/board/{board}/members")
    return json.dumps(result, indent=2)


def a2a_heartbeat(task_id: str, note: str = "") -> str:
    """发心跳更新任务时间戳。长任务（>5分钟）期间定期调用，
    让 Board/Orchestrator 知道任务仍在进行。"""
    config = _load_profile_config()
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    board_id = resolve_board_from_task(task_id)
    result = client._request("POST",
        f"/api/v1/board/{board_id}/task/{task_id}/heartbeat",
        body={"note": note})
    return json.dumps(result, indent=2)
```

### 注册代码

在 `agentmail_tools.py` 文件底部追加：

```python
# a2a toolset 注册
try:
    from tools.a2a_tools import a2a_show, a2a_list, a2a_members, a2a_heartbeat
    registry.register("a2a_show", a2a_show)
    registry.register("a2a_list", a2a_list)
    registry.register("a2a_members", a2a_members)
    registry.register("a2a_heartbeat", a2a_heartbeat)
except ImportError:
    pass
```

### 优先规则

在角色 prompt 中声明：有 toolset 的操作优先用 tool，不通过邮件：

| 操作 | tool 替代 | 理由 |
|------|----------|------|
| show task | `a2a_show(task_id)` | 零 SMTP 往返 |
| list tasks | `a2a_list(board, status, assignee)` | 零 SMTP 往返 |
| list members | `a2a_members(board)` | 零 SMTP 往返 |
| heartbeat | `a2a_heartbeat(task_id, note)` | 高频操作，tool 更快 |

---

## 5. Webhook patch 更新

### 文件位置

`agentmail/lib/*.py`（patch 脚本，当前 `uninstall_hermes.py`）

### 改动点

在 webhook handler 构建 chat_id 处（`webhook.py` 第 668 行附近），添加 `_a2a_session_key` 检测逻辑：

```python
# 现有代码：
# session_chat_id = f"webhook:{route_name}:{delivery_id}"

# 改为：
a2a_key = payload.get("_a2a_session_key")
if a2a_key:
    session_chat_id = f"webhook:{route_name}:{a2a_key}"
else:
    session_chat_id = f"webhook:{route_name}:{delivery_id}"
```

同时在 prompt 构建处（第 552 行附近）添加 `_role_prompt` 拼接：

```python
# 在 prompt 渲染和 skill 加载之间
role_prompt = payload.get("_role_prompt", "")
if role_prompt:
    prompt = f"{prompt}\n\n---\n{role_prompt}"
```

以及 `_capability_body` 处理（capability-inquiry 替代原始邮件内容）：

```python
capability_body = payload.get("_capability_body", "")
if capability_body:
    # 用填充后的 whoami.md 替代原始邮件作为 LLM 的第一句话
    prompt = capability_body
    # 注入 session key 让同一 agent 的能力问询回复共享上下文
    if "_a2a_session_key" not in payload:
        payload["_a2a_session_key"] = f"capability:{payload.get('from', 'unknown')}"
```

### patch 实现方式

在现有 `WEBHOOK_BLOCK` 系列常量中新增一个 block：

```python
# Block 4: A2A session key + role prompt injection
# Inserted AFTER preprocessor invocation, BEFORE prompt rendering
WEBHOOK_BLOCK4 = """
        # --A2A session key override (a2a_board integration) --
        a2a_key = payload.get("_a2a_session_key")
        if a2a_key:
            session_chat_id = f"webhook:{route_name}:{a2a_key}"
"""
```

### 前置条件

必须有 `payload`、`route_name`、`session_chat_id`、`delivery_id` 等变量在作用域内。需要检查 webhook.py 中这些变量的定义位置。

---

## 6. agentmail_tools.py 注册

### 文件路径

`tools/agentmail_tools.py`

### 改动点

在文件尾部追加两个注册块：

```python
# ── a2a_board preprocessor ──
try:
    from tools.a2a_board import a2a_board_preprocessor
    from gateway.platforms.webhook import register_preprocessor
    register_preprocessor("a2a_board", a2a_board_preprocessor)
except ImportError:
    pass

# ── a2a toolset ──
try:
    from tools.a2a_tools import a2a_show, a2a_list, a2a_members, a2a_heartbeat
    registry.register("a2a_show", a2a_show)
    registry.register("a2a_list", a2a_list)
    registry.register("a2a_members", a2a_members)
    registry.register("a2a_heartbeat", a2a_heartbeat)
except ImportError:
    pass
```

### try/except 模式

沿用 agentmail_tools.py 中现有 `send_welcome.py` 的 try/except 模式，确保 a2a_board 未安装时不影响现有功能。

---

## 7. agentmail SKILL 更新

### 文件路径

`~/.hermes/skills/agentmail/SKILL.md`

### 改动点

在 SKILL.md 末尾追加 A2A 能力章节，作为非 Hermes 系统的兜底方案（Hermes 系统由 preprocessor 提供实时 SOUL.md + SKILL 数据）。

新增章节内容：

```markdown
## A2A Project Collaboration (a2a_board)

当收到 Subject 为 `[A2A] capability-inquiry` 的邮件时：

1. 你是一个 agentmail 参与者。请基于你的 SOUL.md 内容（即你的角色定义）
   和已加载的 SKILL 列表，回复能力自述。
2. 能力自述格式：
   - email: 你的 agentmail 地址
   - role: 你的角色定位
   - skills_loaded: 已加载的 SKILL 列表
   - expertise: 你的专长领域
   - constraints: 你做不了的事（重要！）
3. 使用 send_mail() 回复问询者。
4. 完成后不需要进一步对话。

当收到 Subject 含 `[A2A]` 前缀的邮件时（如 `[A2A] complete T1`）：
- 这些指令由 Board 的 agentmail 地址直接处理，你不需要回复。
- 如果你被 Cc 了，只需知悉即可。

当收到 Subject 含 `[Proposal]` / `[Criteria]` / `[Report]` / `[Review]` / `[Discuss]` 的邮件时：
- 这些是成员间的协作对话，请根据你的角色参与讨论。
- 参考你的 a2a toolset（a2a_show / a2a_list / a2a_members / a2a_heartbeat）
  进行高效查询。
```

### 关键限制

非 Hermes 系统的 agent 没有 `~/.hermes/profiles/` 目录，preprocessor 无法读取 SOUL.md 和 SKILL 列表。此时降级到 SKILL.md 中的能力自述章节，由 LLM 从自己的 system prompt 中提取信息。

---

## 依赖关系

```
a2a_board.py preprocessor
  ├── 依赖：read_soul_md() → 文件系统
  ├── 依赖：read_skills() → 文件系统  
  ├── 依赖：_GatewayClient → Rust API（需 P0 就绪）
  └── 注册：agentmail_tools.py

角色 prompt × 3
  ├── 依赖：无（纯文本文件）
  └── 同时更新：a2a_board.py preprocessor 的 read_role_prompt()

whoami.md
  ├── 依赖：无（纯文本模板）
  └── 同时更新：a2a_board.py preprocessor 的 fill_whoami_template()

a2a toolset × 4
  ├── 依赖：Rust HTTP API 端点就绪（P0）
  ├── 依赖：_GatewayClient 可用
  └── 注册：agentmail_tools.py

Webhook patch
  ├── 依赖：理解 webhook.py 变量作用域
  └── 同时更新：uninstall_hermes.py 中的 patch block

agentmail SKILL
  ├── 依赖：无（纯文本追加）
  └── 生效：重启 gateway 后自动加载
```

## 实施顺序

```
Step 1: whoami.md + 角色 prompt × 3（纯文本，无依赖）
Step 2: agentmail SKILL 更新（纯文本，无依赖）
Step 3: a2a_board.py preprocessor（需理解现有注册模式）
Step 4: agentmail_tools.py 注册（同时注册 preprocessor + toolset）
Step 5: Webhook patch 更新（需 Rust P0 后的全链路测试）
Step 6: a2a toolset × 4（需 Rust API 就绪才能测试）
```
