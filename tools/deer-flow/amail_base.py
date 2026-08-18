#!/usr/bin/env python3
"""amail_base.py — DeerFlow 适配层（第三实例,2026-08-18）。

与 OpenClaw amail_base.py 同构（三件套）:
  ① 平台实现: config 加载 / profile 目录 / set_agent_context
  ② 注入点赋值 + 能力开关: PERSONA_SUPPORTED = False
  ③ 平台注册: 入站 bridge 投递目标(LangGraph API)

共享核心(tools/agentmail_base)已提供平台无关 set_agent_context
(按 agentmail.json 布局扫描),本适配层在 OpenClaw 基础上仅做:
  - 转发共享函数(与 OpenClaw 同款)
  - 注入 DeerFlow 身份(X-Agentmail-Agent: deerflow/...)
  - bridge 投递段: dispatch_to_deerflow(LangGraph threads+runs)

布局: ~/.agentmail/systems/{sid}/{cleaned_addr}/agentmail.json(共享)
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

_AGENTMAIL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# repo = <repo>/tools/deer-flow/ → 上溯 3 级 = 仓库根
if _AGENTMAIL_REPO.endswith("tools"):
    _AGENTMAIL_REPO = os.path.dirname(_AGENTMAIL_REPO)
_TOOLS = os.path.join(_AGENTMAIL_REPO, "tools")
_SCRIPTS = os.path.join(_AGENTMAIL_REPO, "scripts")
for _p in (_TOOLS, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agentmail_base as _ab          # noqa: E402  (共享核心)
import agentmail_tools as _tools      # noqa: E402  (X-Agentmail-Agent 身份注入)


# ── DeerFlow 身份检测(只报真实检测结果)───────────────────────────
def _detect_deerflow_version() -> str:
    """检测 DeerFlow 版本:优先 DEER_FLOW_HOME/backend/pyproject.toml,
    失败回退 unknown。"""
    for pp in (
        os.path.join(os.environ.get("DEER_FLOW_HOME", ""), "backend", "pyproject.toml"),
        os.path.join(os.path.expanduser("~"), "deer-flow", "backend", "pyproject.toml"),
        os.path.join(os.path.expanduser("~"), "deer-flow", "pyproject.toml"),
    ):
        if pp and os.path.isfile(pp):
            try:
                with open(pp) as f:
                    for line in f:
                        if line.strip().startswith("version"):
                            v = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if v:
                                return v
            except Exception:
                pass
    return "unknown"


# ── 注入身份(与 OpenClaw 同模式: 目录检测会误判,必须显式注入)────
_tools._AGENT_IDENTITY_OVERRIDE = f"deerflow/{_detect_deerflow_version()}"


# ── ① 平台实现 ──────────────────────────────────────────────────
def _deerflow_profile_dir() -> Optional[str]:
    """profile 目录: 当前 system 目录(system_id 解析同 OpenClaw 指针)。"""
    sid = os.environ.get("AMAIL_SYSTEM_ID", "")
    if sid:
        return str(Path.home() / ".agentmail" / "systems" / sid)
    return None


def set_agent_context(agent_id: str, system_id: str = "") -> None:
    """把当前 agent 的 config 挂到公共核心注入点(转发共享实现)。"""
    _ab.set_agent_context(agent_id, system_id)


def make_client(api_key: str = "", system_id: str = ""):
    """Gateway 客户端(agentmail_tools._GatewayClient,全方法集)。

    api_key 缺省时从当前 agent 的 agentmail.json 读取。
    """
    cfg = load_agent_config_for_key(system_id)
    gw_url = (cfg or {}).get("gateway_url", "")
    key = api_key or ((cfg or {}).get("api_key", ""))
    return _tools._GatewayClient(gw_url, key)


def load_agent_config_for_key(system_id: str = "") -> Optional[dict]:
    """读取当前 system 的 gateway 配置(agentmail_gateway.json)。"""
    try:
        sid = system_id or os.environ.get("AMAIL_SYSTEM_ID", "")
        path = Path.home() / ".agentmail" / "systems" / sid / "agentmail_gateway.json"
        if path.is_file():
            return json.loads(path.read_text())
    except Exception:
        pass
    return None


def load_gateway_config(system_id: str = "") -> Optional[dict]:
    """gateway 连接配置(转发共享 helper)。"""
    return _ab._load_gateway_config(system_id)


def detect_system_id() -> str:
    """系统身份: 指针文件唯一来源(~/.deer-flow/.agentmail 或 env)。"""
    sid = os.environ.get("AMAIL_SYSTEM_ID", "")
    if sid:
        return sid
    for ptr in (Path.home() / ".deer-flow" / ".agentmail",
                Path.home() / ".agentmail" / ".agentmail"):
        d = _ab._read_pointer(ptr)
        if d.get("system_id"):
            return d["system_id"]
    return ""


def load_agents_registry(system_id: str) -> dict:
    """扫描地址键 agentmail.json,重建 {email → agent_id} 路由映射(共享布局)。"""
    registry = {}
    sys_dir = Path.home() / ".agentmail" / "systems" / system_id
    if sys_dir.is_dir():
        for addr_dir in sorted(sys_dir.iterdir()):
            aj = addr_dir / "agentmail.json"
            if not aj.is_file():
                continue
            try:
                cfg = json.loads(aj.read_text())
                email = cfg.get("email", "")
                agent_id = cfg.get("agent_id", "")
                if email and agent_id:
                    registry[email] = agent_id
            except Exception:
                pass
    return registry


# ── ② 注入点 + 能力开关 ─────────────────────────────────────────
_ab.PERSONA_SUPPORTED = False        # DeerFlow 无 persona 派生地址概念
_ab._PROFILE_DIR_RESOLVER = _deerflow_profile_dir


# ── ③ bridge 投递段: DeerFlow LangGraph API ─────────────────────
def dispatch_to_deerflow(enriched_payload: dict, cfg: dict) -> dict:
    """投递富化后的邮件到 DeerFlow LangGraph API。

    cfg 键: deerflow_url(默认 http://127.0.0.1:8001) / assistant_id
    (默认 lead_agent) / thread_id(默认 UUID5("amail", email))。

    链路:
      POST {url}/api/runs/wait  RunCreateRequest
        {"assistant_id", "input": {"messages": [{role, content}]},
         "config": {"configurable": {"thread_id"}}, "metadata":
         {"idempotency_key": "amail:<delivery_id>"},
         "multitask_strategy": "reject", "if_not_exists": "create"}
    """
    import urllib.request
    url = (cfg.get("deerflow_url") or "http://127.0.0.1:8001").rstrip("/")
    assistant_id = cfg.get("assistant_id") or "lead_agent"
    email = enriched_payload.get("to") or ""
    if isinstance(email, list):
        email = email[0] if email else ""
    email = enriched_payload.get("my_amail_addr") or email
    thread_id = cfg.get("thread_id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"amail:{email}"))

    # 完整渲染(共享 render_message = json.dumps(payload) 语义,与 Hermes/
    # OpenClaw 一致):agent 需要 sender/recipients/my_amail_addr 才知道
    # 回复给谁——只传 body 会让 LLM 编造收件人(实测 test@example.com)。
    content = _ab.render_message(enriched_payload)
    body = {
        "assistant_id": assistant_id,
        "input": {"messages": [{"role": "user", "content": content}]},
        "config": {"configurable": {"thread_id": thread_id}},
        "metadata": {"idempotency_key": f"amail:{enriched_payload.get('mail_id', '')}",
                     "amail_email": email},
        "multitask_strategy": "reject",
        "if_not_exists": "create",
    }
    req = urllib.request.Request(
        f"{url}/api/runs/wait",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 120)) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# ── 转发共享核心(复用面,与 OpenClaw 同款)────────────────────────
preprocess_mail_payload = _ab.preprocess_mail_payload
process_inbound_mail = _ab.process_inbound_mail
parse_amail_persona = _ab.parse_amail_persona
_extract_board_gateway = _ab._extract_board_gateway
register_board_gateway = _ab._register_board_gateway
store_board_credential = _ab._store_board_credential
email_for_agent = _ab.email_for_agent
register_agent_email = _ab.register_agent_email
deregister_agent_email = _ab.deregister_agent_email
load_agent_config = _ab.load_agent_config
render_message = _ab.render_message
agent_for_email = _ab.route_agent_for_email
