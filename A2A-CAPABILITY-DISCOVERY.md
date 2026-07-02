# 能力自述改进方案：预处理器驱动的结构化能力发现

## 问题

当前方案将能力自述放在 `agentmail` SKILL 中，由 LLM 在收到能力问询邮件时自行提取 SOUL.md 和 SKILL 列表。但 LLM 没有直接的文件访问能力——它只能看到 system prompt 中已有的内容，无法可靠地以结构化方式提取"我当前加载了哪些 SKILL"。

## 改进：预处理器接管能力自述

将能力自述的**数据收集**从 LLM 推理阶段前置到预处理器阶段，由预处理器读取实际文件后构造专属 prompt，再调用 agent session 执行。

### 流程

```
旧流程（LLM 自解析，不可靠）：

Orchestrator → 能力问询邮件
  → webhook → preprocessor → agent session（带 skill）
  → LLM 尝试从自己的 system prompt 中找出 SOUL.md 内容和 SKILL 列表
  → 不可靠，可能遗漏或误解


新流程（预处理器驱动，可靠）：

Orchestrator → 能力问询邮件
  → webhook → preprocessor
  → a2a_board preprocessor 检测到 [A2A] capability-inquiry
  → 读取目标 profile 的配置文件：                                      ← 新增
      ~/.hermes/profiles/<profile-name>/config.yaml  → 获取 SKILL 列表
      ~/.hermes/profiles/<profile-name>/SOUL.md       → 获取角色定义
  → 构造专属 prompt（内含实际的 SOUL.md 内容和 SKILL 列表）
  → 调用 agent session 执行能力自述                                     ← LLM 只需格式化输出
  → 回复能力声明邮件
```

### Preprocessor 实现

```python
# agentmail/tools/a2a_board.py

import os
import yaml
from pathlib import Path

HERMES_PROFILES = os.path.expanduser("~/.hermes/profiles")

def resolve_profile(email: str) -> str | None:
    """根据 email 地址查找对应的 profile 名称。
    
    email 的本地部分通常与 profile 名一致。
    遍历 profiles 目录，查找 config.yaml 中 email_address 匹配的条目。
    """
    for entry in os.listdir(HERMES_PROFILES):
        config_path = Path(HERMES_PROFILES) / entry / "config.yaml"
        if not config_path.exists():
            continue
        with open(config_path) as f:
            config = yaml.safe_load(f)
        if config.get("email_address") == email:
            return entry
    return None

def read_soul_md(profile: str) -> str:
    path = Path(HERMES_PROFILES) / profile / "SOUL.md"
    if path.exists():
        return path.read_text()
    return ""

def read_skills(profile: str) -> list[str]:
    config_path = Path(HERMES_PROFILES) / profile / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return config.get("skills", [])
    return []

def build_capability_prompt(profile: str, email: str) -> str:
    soul = read_soul_md(profile)
    skills = read_skills(profile)
    
    return f"""
你的 email 地址：{email}

你的角色定义（来自 SOUL.md）：
{"=" * 40}
{soul}
{"=" * 40}

你加载的 SKILL：
{chr(10).join(f"- {s}" for s in skills)}

请基于以上信息，以结构化格式回复能力自述。
"""

def a2a_board_preprocessor(payload: dict, headers: dict) -> dict:
    # ... 其他 A2A 命令处理 ...
    
    subject = payload.get("subject", "")
    if not subject.strip().upper().startswith("[A2A] CAPABILITY-INQUIRY"):
        return payload
    
    target_email = payload.get("to", "")
    profile = resolve_profile(target_email)
    if not profile:
        # 无法定位 profile，不回邮件也可能
        return payload
    
    # 设置特殊 prompt
    payload["_special_prompt"] = build_capability_prompt(profile, target_email)
    payload["_a2a_capability_response"] = True
    
    return payload
```

### Webhook handler 侧的修改

```python
# gateway/webhook.py 或 Hermes webhook 处理逻辑

if payload.get("_a2a_capability_response"):
    # 使用特殊 prompt 启动 agent session，不走正常邮件处理流程
    special_prompt = payload.pop("_special_prompt")
    response = agent_session.run(prompt=special_prompt)
    
    # agent 的回复直接作为能力自述邮件发送
    capability_body = format_capability_response(response)
    send_mail(
        to=payload["from"],
        subject="Re: " + payload["subject"],
        body=capability_body,
    )
    # 不需要 webhook 通知、不需要存 email_records
    return True
```

### 数据流

```
Preprocessor 读取的内容（可靠）：
  ~/.hermes/profiles/researcher-a/
  ├── SOUL.md       → "你是一个云成本分析师，专攻 AWS 定价模型..."
  ├── config.yaml
  │   └── skills:   → [agentmail, data-analysis, aws-cost-tools]
  └── SOUL.md       → 角色定位全文

LLM 收到专属 prompt（有真实数据，不需要猜测）：
  "你的 SOUL.md 内容是：[全文]
   你加载的 SKILL 有：agentmail, data-analysis, aws-cost-tools"
   → LLM 只需将已有信息格式化为结构化输出
```

### 优势

| 之前（LLM 自解析） | 之后（预处理器驱动） |
|-------------------|-------------------|
| LLM 需要从 system prompt 中挖掘 SOUL.md 内容 | Preprocessor 读取实际文件，100% 准确 |
| LLM 需要推断自己加载了哪些 SKILL | Preprocessor 从 config.yaml 中直接读取 |
| 回复格式不可控，质量依赖 LLM 的理解 | LLM 拿到具体数据后只需格式输出 |
| 无法访问实际文件系统 | 利用已有的 Hermes 配置文件结构 |
| 跨系统 agent 无法自述能力（没有 SOUL.md） | 需要跨系统时新增扩展点（见下方） |

### 跨系统扩展

对于非 Hermes 系统的 agent（没有 `~/.hermes/profiles`），capability-inquiry 不走预处理器特殊路径，退回普通 agent session 模式：

```python
if not profile:
    # 非 Hermes 系统 agent，走普通 agent session
    # agentmail SKILL 中的能力自述章节处理
    return payload
```

agentmail SKILL 中的能力自述章节作为**兜底方案**保留，优先由预处理器处理。

### 实施

| 组件 | 修改 | 工作量 |
|------|------|--------|
| `a2a_board.py` | 新增 `resolve_profile()`、`read_soul_md()`、`read_skills()`、`build_capability_prompt()` | 小 |
| Hermes webhook handler | 检测 `_a2a_capability_response`，使用特殊 prompt 启动 session | 中 |
| `agentmail` SKILL | 保留能力自述章节作为跨系统兜底 | 小 |
