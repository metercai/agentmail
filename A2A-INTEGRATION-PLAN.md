# a2a_board — Agentmail 集成方案

> 基于 agentmail 的 A2A 项目协作看板集成改动

---

## 概述

在已有 amail 集成基础上，新增 6 处改动以支持 a2a_board 协作流程。所有改动在 agentmail 项目目录内完成，不涉及 Rust amail-gateway 侧。

## 改动清单

| # | 改动 | 文件 | 行数 | 类型 |
|---|------|------|------|------|
| 1 | 删 `skills: ["agentmail"]` | `~/.hermes/webhook_subscriptions.json` | 删 3 行 | 配置 |
| 2 | 新增 WEBHOOK_BLOCK3（消费 prompt 字段） | `lib/uninstall_hermes.py` + `patches/apply_webhook_patch.py` | ~15 行 | 补丁 |
| 3 | 新增角色 prompt 文件 × 4 | `skill/role/*.md` | 4 个文件 | 模板 |
| 4 | 扩充 `preprocess_mail_payload` | `tools/agentmail_tools.py` | ~40 行 | 逻辑 |
| 5 | 新增工具函数 | `tools/agentmail_tools.py` | ~4 个函数 | 逻辑 |
| 6 | 新增 a2a toolset × 4 | `tools/agentmail_tools.py` | ~4 个 tool | 注册 |

---

## 改动详情

### 1. 删 skills

```json
// 改动前
{
  "agentmail-inbound": {
    "preprocess": "agentmail_gateway",
    "prompt": "",
    "skills": ["agentmail"],
    "deliver": "log"
  }
}

// 改动后
{
  "agentmail-inbound": {
    "preprocess": "agentmail_gateway",
    "prompt": "",
    "deliver": "log"
  }
}
```

理由：agentmail SKILL 已通过 profile 加载到 system prompt，user message 中再次加载重复浪费 token。

---

### 2. 新增 Patch 6 / WEBHOOK_BLOCK5

#### apply_webhook_patch.py — Patch 6

插入在 `session_chat_id = f"webhook:{route_name}:{delivery_id}"` 之后（L616）、`# Store delivery info` 之前：

```python
# ── Patch 6: consume preprocessor prompt fields (a2a_board) ──
# Inserted AFTER session_chat_id, BEFORE # Store delivery info
PATCH6_MARKER = '        session_chat_id = f"webhook:{route_name}:{delivery_id}"'
PATCH6_BLOCK = '''\n        # ── a2a_board: consume preprocessor prompt fields ──
        _wp = payload.get("_whoami_prompt")
        if _wp:
            prompt = prompt + "\\n\\n---\\n" + _wp
        _rp = payload.get("_role_prompt")
        if _rp:
            prompt = prompt + "\\n\\n---\\n" + _rp
        _sk = payload.get("_a2a_session_key")
        if _sk:
            session_chat_id = f"webhook:{route_name}:{_sk}"
\n'''
# 替换逻辑（与现有 Patch 3/5 相同模式）
content = content.replace(PATCH6_MARKER, PATCH6_MARKER + PATCH6_BLOCK, 1)
```

同时更新 `WEBHOOK_ANCHOR_MAP`：新增 `"field_consumer": N` 定位，用于后续版本适应。

#### uninstall_hermes.py — WEBHOOK_BLOCK5

```python
# Block 6: a2a_board prompt field consumer
# Inserted AFTER session_chat_id, BEFORE "# Store delivery info"
WEBHOOK_BLOCK5 = """        # ── a2a_board: consume preprocessor prompt fields ──
        _wp = payload.get("_whoami_prompt")
        if _wp:
            prompt = prompt + "\n\n---\n" + _wp
        _rp = payload.get("_role_prompt")
        if _rp:
            prompt = prompt + "\n\n---\n" + _rp
        _sk = payload.get("_a2a_session_key")
        if _sk:
            session_chat_id = f"webhook:{route_name}:{_sk}"
"""
```

unpatch 列表按生产执行顺序排列（新增 WEBHOOK_BLOCK3，原 BLOCK3→4、BLOCK4→5）：

```python
for name, block in [
    ("PREPROCESS_REGISTRY",        WEBHOOK_BLOCK1),
    ("preprocessor invocation",    WEBHOOK_BLOCK2),
    ("a2a_board prompt fields",    WEBHOOK_BLOCK3),   # ← 新增
    ("ping-pong interception",     WEBHOOK_BLOCK4),   # ← 原 BLOCK3
    ("_log_ping_event",            WEBHOOK_BLOCK5),   # ← 原 BLOCK4
]:
```

注意：`Callable` 从 typing import 中移除（已有 `re.subn` 第 5 步）保持不变，新增的 `Callable` 由 Patch 1 负责打上。

#### 生产代码精确执行顺序

```
L480:  BLOCK2 — preprocessor 调用（设 _whoami_prompt / _role_prompt / _a2a_session_key）
L493:  _render_prompt("", payload) → JSON dump → prompt
L499:  (skills 已删，跳过)
L616:  session_chat_id = f"webhook:{route}:{delivery_id}"
L617:  BLOCK5 — 消费三个字段（追加 prompt / 覆盖 session_chat_id）  ← 新增
L618:  # Store delivery info...（使用修改后的 session_chat_id）
L640:  MessageEvent(text=prompt, ...)（使用修改后的 prompt 和 session_chat_id）
L658:  BLOCK3 — ping-pong 拦截（最后一步，进 agent session 前的拦截点）
L694:  asyncio.create_task(self.handle_message(event)) → agent session
```

```python
WEBHOOK_BLOCK5 = """
        # ── a2a_board: consume preprocessor prompt fields ──
        _wp = payload.get("_whoami_prompt")
        if _wp:
            prompt = prompt + "\\n\\n---\\n" + _wp
        _rp = payload.get("_role_prompt")
        if _rp:
            prompt = prompt + "\\n\\n---\\n" + _rp
        _sk = payload.get("_a2a_session_key")
        if _sk:
            session_chat_id = f"webhook:{route_name}:{_sk}"
"""
```

三个字段说明：

| 字段 | 语义 | 谁设 | BLOCK5 行为 |
|------|------|------|------------|
| `_whoami_prompt` | 追加身份声明 | 任何 preprocessor | `prompt += "\n\n---\n" + 内容` |
| `_role_prompt` | 追加角色行为指导 | 任何 preprocessor | `prompt += "\n\n---\n" + 内容` |
| `_a2a_session_key` | 覆盖 session chat_id | 任何 preprocessor | `session_chat_id = f"webhook:{route}:{key}"` |

BLOCK5 不关心字段是谁设的、为什么设。只检查存在性并执行对应动作。

---

### 3. 角色 prompt 文件

#### 文件结构

```
agentmail/
├── skill/
│   ├── SKILL.md
│   ├── DESCRIPTION.md
│   ├── whoami.md
│   └── role/
│       ├── whoami.md           ← 身份声明模板
│       ├── orchestrator.md     ← 编排者行为指导
│       ├── verifier.md         ← 验证者行为指导
│       └── worker.md           ← 执行者行为指导
└── tools/
    └── agentmail_tools.py
```

安装时随 SKILL 一起复制到 profile：`~/.hermes/skills/agentmail/role/*.md`

#### 占位符

所有 `.md` 文件通过 `fill_template()` 统一替换：

```
{{AGENTMAIL_ADDRESS}}     — agent 的 email
{{BOARD_ID}}              — 看板 ID（空字符串则无）
{{BOARD_ROLE}}            — 角色名（空字符串则无）
{{INQUIRY_SENDER}}        — 问询者的 email
{{INQUIRY_SUBJECT}}       — 原邮件 Subject
{{SOUL_MD_CONTENT}}       — SOUL.md 全文
{{SKILLS_LIST}}           — 已加载 SKILL 列表
```

#### whoami.md 模板

```
## 身份声明

你的 email: {{AGENTMAIL_ADDRESS}}

你的 SOUL.md:
{{SOUL_MD_CONTENT}}

你已加载的 SKILL:
{{SKILLS_LIST}}

收到来自 {{INQUIRY_SENDER}} 的问询（主题: {{INQUIRY_SUBJECT}}）。

请使用 `send_mail()` 回复你的能力自述，格式：
email: <你的地址>
role: <角色>
skills_loaded: [<列表>]
expertise: [<专长>]
constraints: [<做不到的事>]
```

#### orchestrator.md 模板

```
## Orchestrator 角色

看板: {{BOARD_ID}}
你的 email: {{AGENTMAIL_ADDRESS}}

### 可发起（→ Board）
- [A2A] create — 按共识方案创建 task
- [A2A] block / unblock — 阻挡/解除
- [A2A] cancel — 取消 task
- [A2A] reassign / edit / deadline — 管理 task
- [A2A] comment / arbitrate — 备注或提请仲裁

### 可发起（→ 成员）
- [Proposal] 编排方案 — 发起评议
- [Report] 阶段汇报 — 阶段完成后总结
- [WhoAmI] — 询问成员能力

### 应对（← 通知）
- blocked → 介入协调
- 其他 → 知悉

### 规则
- 有 toolset 的操作优先用 tool（a2a_show / a2a_list / a2a_members）
- 不跳过评议直接 create
- 先 comment 沟通，沟通无效再 arbitrate
```

#### verifier.md 模板

```
## Verifier 角色

看板: {{BOARD_ID}}
你的 email: {{AGENTMAIL_ADDRESS}}

### 可发起（→ Board）
- [A2A] approve / reject — 审阅被指派的 task
- [A2A] output — 最终放行（对照验收标准）
- [A2A] block / comment / arbitrate

### 可发起（→ 成员）
- [Criteria] 验收标准 — 发起验收标准确认

### 应对（← 通知）
- review-needed → 核心职责！审阅！
- output → 项目完成

### 规则
- 仅审阅被指派的 task（reviewer 字段包含你的 email）
- output 前检查：所有 task done、流转合规
- 有 toolset 优先用 tool
```

#### worker.md 模板

```
## Worker 角色

看板: {{BOARD_ID}}
你的 email: {{AGENTMAIL_ADDRESS}}

### 可发起（→ Board）
- [A2A] complete — 完成任务，带 summary
- [A2A] heartbeat — 长任务更新进度（优先用 a2a_heartbeat tool）
- [A2A] block — 遇到阻挡
- [A2A] comment

### ❌ 不可做
- approve / reject / output / create / cancel / arbitrate

### 应对（← 通知）
- assigned → 查看任务详情开始执行
- rejected → 修订后重新 complete
- blocked / unblocked / cancelled → 按要求行动

### 规则
- complete 时带 summary
- 长任务用 a2a_heartbeat() 发心跳，不要发邮件
- 有 toolset 优先用 tool
```

---

### 4. 扩充 preprocess_mail_payload

在 `tools/agentmail_tools.py` 中，对现有 `preprocess_mail_payload` 函数新增三段逻辑。

```python
def preprocess_mail_payload(payload, headers):
    # ── 保持现有 amail 预处理全部不变 ──
    ...

    # ── [New] WhoAmI 问询 ──
    subject = (payload.get("subject") or "").strip()
    if subject.upper().startswith("[WHOAMI]"):
        ctx = build_ctx(payload, headers)
        whoami_raw = _read_role_file("whoami")
        payload["_whoami_prompt"] = fill_template(whoami_raw, ctx)
        return payload  # 身份问询不需要后续角色/board 处理

    # ── [New] Board 上下文（由 Rust A2aInterceptor 注入 _board_id/_board_role）──
    board_id = payload.get("_board_id")
    board_role = payload.get("_board_role")
    if board_id and board_role:
        ctx = build_ctx(payload, headers)
        role_raw = _read_role_file(board_role)
        payload["_role_prompt"] = fill_template(role_raw, ctx)
        sender = payload.get("from", "")
        payload["_a2a_session_key"] = f"a2a:{board_id}:{sender}"

    return payload
```

---

### 5. 新增工具函数

```python
def fill_template(text: str, ctx: dict) -> str:
    """替换 {{KEY}} 占位符。ctx 的 key 为大写字母。"""
    for key, val in ctx.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def build_ctx(payload, headers) -> dict:
    """构造模板上下文。"""
    return {
        "AGENTMAIL_ADDRESS": _resolve_agent_email(),
        "BOARD_ID": payload.get("_board_id", ""),
        "BOARD_ROLE": payload.get("_board_role", ""),
        "INQUIRY_SENDER": payload.get("from", ""),
        "INQUIRY_SUBJECT": payload.get("subject", ""),
        "SOUL_MD_CONTENT": _read_soul_md(),
        "SKILLS_LIST": ", ".join(_read_skills()),
    }


def _read_role_file(name: str) -> str:
    """读 skill/role/<name>.md。优先从当前 SKILL 目录定位。"""
    # 搜索路径: ~/.hermes/skills/agentmail/role/ + 项目 skill/role/
    ...


def _read_soul_md() -> str:
    """读 profile 目录下的 SOUL.md。"""
    ...


def _read_skills() -> list[str]:
    """读 profile config.yaml 中的 skills 列表。"""
    ...


def _resolve_agent_email() -> str:
    """从 profile config 获取 email。"""
    ...
```

---

### 6. a2a toolset × 4

在 `tools/agentmail_tools.py` 尾部注册：

```python
# ── a2a toolset ──
try:
    from tools.agentmail_tools import (  # 自身引用
        _GatewayClient, _load_profile_config
    )
    import json

    def a2a_show(task_id: str) -> str:
        """查询任务详情。"""
        cfg = _load_profile_config()
        client = _GatewayClient(cfg["gateway_url"], cfg["api_key"])
        board_id = _resolve_board(task_id)
        r = client._request("GET",
            f"/api/v1/board/{board_id}/task/{task_id}")
        return json.dumps(r, indent=2)

    def a2a_list(board: str, status="", assignee="") -> str:
        """按条件过滤 task 列表。"""
        cfg = _load_profile_config()
        client = _GatewayClient(cfg["gateway_url"], cfg["api_key"])
        q = {}
        if status: q["status"] = status
        if assignee: q["assignee"] = assignee
        r = client._request("GET",
            f"/api/v1/board/{board}/tasks", params=q)
        return json.dumps(r, indent=2)

    def a2a_members(board: str) -> str:
        """查询成员列表。"""
        cfg = _load_profile_config()
        client = _GatewayClient(cfg["gateway_url"], cfg["api_key"])
        r = client._request("GET",
            f"/api/v1/board/{board}/members")
        return json.dumps(r, indent=2)

    def a2a_heartbeat(task_id: str, note="") -> str:
        """发心跳。"""
        cfg = _load_profile_config()
        client = _GatewayClient(cfg["gateway_url"], cfg["api_key"])
        board_id = _resolve_board(task_id)
        r = client._request("POST",
            f"/api/v1/board/{board_id}/task/{task_id}/heartbeat",
            body={"note": note})
        return json.dumps(r, indent=2)

    registry.register("a2a_show", a2a_show)
    registry.register("a2a_list", a2a_list)
    registry.register("a2a_members", a2a_members)
    registry.register("a2a_heartbeat", a2a_heartbeat)
except ImportError:
    pass
```

---

## 执行顺序（生产环境 webhook.py）

```
L480:  BLOCK2 — preprocessor 调用
        ├─ 现有 amail 预处理（不变）
        ├─ [WhoAmI] 检测 → 设 _whoami_prompt
        └─ _board_id + _board_role 检测 → 设 _role_prompt + _a2a_session_key

L493:  _render_prompt("", payload) → JSON dump → prompt

L499:  (skills 已删，跳过)

L616:  session_chat_id = f"webhook:{route}:{delivery_id}"
L617:  BLOCK5 — 消费三个字段
         _whoami_prompt → prompt += "\n\n---\n" + 内容
         _role_prompt   → prompt += "\n\n---\n" + 内容
         _a2a_session_key → session_chat_id = f"webhook:{route}:{key}"

L618:  # Store delivery info...（使用修改后的 session_chat_id）
L640:  MessageEvent(text=prompt, ...)（使用修改后的 prompt 和 chat_id）
L658:  BLOCK3 — ping-pong（进 agent session 前最后一步）
L694:  asyncio.create_task(self.handle_message(event))
```

## LLM 看到的 user message

| 邮件 Subject | prompt 内容 |
|-------------|------------|
| `[WhoAmI]` | JSON dump + whoami.md 身份声明 |
| `[Proposal]` / `[Criteria]` / `[Report]` / `[Review]` / `[Discuss]` / `[Confirm]` | JSON dump + 角色行为指导 |
| 普通邮件 | JSON dump（不变） |

## 不涉及的文件

| 文件 | 理由 |
|------|------|
| `agentmail/skill/SKILL.md` | 不动。agentmail 原有内容不变 |
| `agentmail/skill/whoami.md` | 不动。已有文件保留，新增 `role/whoami.md` 作为替代 |
| Rust amail-gateway 代码 | 另一阶段。Rust A2aInterceptor 负责注入 `_board_id` + `_board_role` |


---

## 实施步骤

按依赖关系排列，每步可独立测试。

### Step 0: 前置准备

确认以下文件存在并可写：

| 文件 | 检查项 |
|------|--------|
| `~/.hermes/hermes-agent/gateway/platforms/webhook.py` | 生产运行版本，含 BLOCK1-BLOCK4 补丁 |
| `~/.hermes/webhook_subscriptions.json` | 含 `agentmail-inbound` 路由 |
| `agentmail/patches/apply_webhook_patch.py` | 可执行 |
| `agentmail/lib/uninstall_hermes.py` | 可执行 |
| `agentmail/tools/agentmail_tools.py` | 含 `preprocess_mail_payload` |

### Step 1: 删 skills 默认值

**文件**：`agentmail/tools/agentmail_tools.py:756`

```python
# 改前
"skills": skills or ["agentmail"],

# 改后
"skills": skills or [],
```

**测试**：重新运行 `register_webhook_route()` 创建新路由，确认生成的 JSON 不含 `skills` 字段。已有路由手动编辑删掉 `skills` 行。

### Step 2: 新增角色 prompt 文件 × 4

**文件**：新建 4 个文件：

```
agentmail/skill/role/
├── whoami.md
├── orchestrator.md
├── verifier.md
└── worker.md
```

**内容**：参照本文档第 3 节的模板编写。安装时随 `agentmail/skill/` 一起复制到 `~/.hermes/skills/agentmail/role/`。

**测试**：手动读取文件确认内容完整、占位符格式一致。

### Step 3: 新增工具函数

**文件**：`agentmail/tools/agentmail_tools.py`

新增函数：

```python
def fill_template(text: str, ctx: dict) -> str
def build_ctx(payload, headers) -> dict
def _read_role_file(name: str) -> str
def _read_soul_md() -> str
def _read_skills() -> list[str]
def _resolve_agent_email() -> str
```

**测试**：写单元测试或手动调用验证：
- `fill_template("Hello {{NAME}}", {"NAME": "World"})` → `"Hello World"`
- `_read_role_file("whoami")` → 返回 whoami.md 内容
- `_read_soul_md()` → 返回当前 profile 的 SOUL.md

### Step 4: 扩充 preprocess_mail_payload

**文件**：`agentmail/tools/agentmail_tools.py`

在 `preprocess_mail_payload` 函数尾部追加三段逻辑（参照本文档第 4 节）：

1. `[WhoAmI]` 问询检测 → 设 `_whoami_prompt`
2. `_board_id` + `_board_role` 检测 → 设 `_role_prompt` + `_a2a_session_key`
3. 原返回逻辑不变

**测试**：

| 测试场景 | 输入 | 预期输出 |
|---------|------|---------|
| [WhoAmI] 邮件 | `subject: "[WhoAmI]"` | `payload._whoami_prompt` 不为空 |
| Board 上下文邮件 | `payload._board_id = "xxx"`, `payload._board_role = "orchestrator"` | `payload._role_prompt` + `_a2a_session_key` 不为空 |
| 普通邮件 | 无特殊前缀 | payload 不变 |
| [WhoAmI] + Board 同时 | `[WhoAmI]` 且 `_board_id` 存在 | 仅设 `_whoami_prompt`，不设 role（[WhoAmI] 先返回） |

### Step 5: 新增 a2a toolset × 4

**文件**：`agentmail/tools/agentmail_tools.py` 尾部

```python
registry.register("a2a_show", a2a_show)
registry.register("a2a_list", a2a_list)
registry.register("a2a_members", a2a_members)
registry.register("a2a_heartbeat", a2a_heartbeat)
```

**测试**：在 Hermes CLI 中手动调用验证：
```
/hermes> a2a_show(task_id="t_xxx")
/hermes> a2a_list(board="pgmig001")
```

### Step 6: 修改 apply_webhook_patch.py（新增 Patch 6）

**文件**：`agentmail/patches/apply_webhook_patch.py`

1. 在 `WEBHOOK_ANCHOR_MAP` 中为每个 commit 条目新增 `"field_consumer": N` 字段（指向 `session_chat_id = ...` 所在行号）
2. 在现有 Patch 5 之后新增 Patch 6 逻辑（参照本文档第 2 节）

**测试**：

```bash
# 备份当前 webhook.py
cp ~/.hermes/hermes-agent/gateway/platforms/webhook.py{,.bak}

# 模拟回退（unpatch）
python3 agentmail/lib/uninstall_hermes.py

# 重新打补丁
python3 agentmail/patches/apply_webhook_patch.py   ~/.hermes/hermes-agent/gateway/platforms/webhook.py

# 验证 BLOCK3 存在
grep -c "a2a_board: consume" ~/.hermes/hermes-agent/gateway/platforms/webhook.py

# 恢复
cp ~/.hermes/hermes-agent/gateway/platforms/webhook.py{.bak,}
```

### Step 7: 修改 uninstall_hermes.py（新增 WEBHOOK_BLOCK3）

**文件**：`agentmail/lib/uninstall_hermes.py`

1. 新增 `WEBHOOK_BLOCK3` 定义（参照本文档第 2 节）
2. 原 `WEBHOOK_BLOCK3` → `WEBHOOK_BLOCK4`
3. 原 `WEBHOOK_BLOCK4` → `WEBHOOK_BLOCK5`
4. unpatch 列表按顺序更新

**测试**：

```bash
# 先 apply，再 uninstall，确认 BLOCK3 被清除
python3 agentmail/lib/uninstall_hermes.py
grep -c "a2a_board: consume" ~/.hermes/hermes-agent/gateway/platforms/webhook.py
# 应返回 0
```

### Step 8: 全链路验证

| 测试 | 方法 | 预期 |
|------|------|------|
| 发送 [WhoAmI] 邮件 | 向自己发 `Subject: [WhoAmI]` | LLM 回复能力自述 |
| 发送 B 流邮件 | 向自己发 `Subject: [Proposal] pgmig001 方案 v1`（需 Board-ID 头） | LLM 按角色 prompt 行为响应 |
| 普通邮件 | 普通对话邮件 | 行为不变 |
| ping-pong 测试 | `check_status.py --ping` | ping-pong 正常 |
| a2a toolset | 手动调用 4 个 tool | 返回正确数据 |

---

## 实施顺序总结

```
Step 1: 删 skills 默认值         ─ 源头修复（无依赖）
Step 2: 角色 prompt 文件 × 4     ─ 纯文本（无依赖）
Step 3: 工具函数                 ─ 纯 Python（无依赖）
Step 4: 扩充 preprocess_mail_payload  ─ 依赖 Step 2+3
Step 5: a2a toolset × 4         ─ 依赖 Rust API 就绪
Step 6: apply_webhook_patch.py  ─ 依赖 Step 4（字段名一致）
Step 7: uninstall_hermes.py     ─ 依赖 Step 6（BLOCK 内容一致）
Step 8: 全链路验证               ─ 依赖 Step 1-7
```