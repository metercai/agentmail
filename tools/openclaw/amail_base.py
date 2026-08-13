#!/usr/bin/env python3
"""amail_base — OpenClaw 接入复用层.

复用 Hermes 的 agentmail_base.py（preprocess/parse/persona/board）与
scripts/gateway_api.py（标准 amail API 客户端），仅替换 config 加载与
目录约定为 OpenClaw 形态：

  ~/.agentmail/{system_id}/                  ← 独立激活产生的系统目录
      agentmail_gateway.json               ← 网关配置（激活时写入）
      mode.json                              ← push/pull 模式（探测时写入）
      agents.json                            ← {email → agentId} 路由注册表
      agents/<agentId>/config.json           ← 每 agent 配置（api_key 等）

不修改 amail-gateway，不修改 Hermes 代码 —— 只做运行时配置源替换。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

# ── agentmail repo 定位 ────────────────────────────────────────
_AGENTMAIL_REPO = os.environ.get(
    "AGENTMAIL_REPO",
    str(Path.home() / "agentmail"),
)

# ── 目录与配置 ─────────────────────────────────────────────────
# 公共共享代码已提升至 tools/（agentmail_base/tools/board——Hermes 与
# OpenClaw 均从同一位置引用/拷贝，修订一处全局生效）
_TOOLS = os.path.join(_AGENTMAIL_REPO, "tools")
_SCRIPTS = os.path.join(_AGENTMAIL_REPO, "scripts")
for _p in (_TOOLS, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agentmail_base as _ab          # noqa: E402  (Hermes 复用层)
import agentmail_tools as _tools      # noqa: E402  (6 工具函数体)
import gateway_api as _gw             # noqa: E402  (标准 API 客户端)

# ── 平台注入（公共核心注入点；Hermes → tools/hermes/agentmail_hermes.py 对称）──
def _openclaw_profile_dir() -> Optional[str]:
    """公共核心 _PROFILE_DIR_RESOLVER 的 OpenClaw 版：当前 system 目录。"""
    sid = detect_system_id()
    return str(system_dir(sid)) if sid else None


# 公共核心隐含依赖补齐（store_inbound_message/_log_amail/_GatewayClient 定义于
# agentmail_tools，公共 agentmail_base 的 preprocess 内部按模块级名字查找——
# Hermes 侧 agentmail_hermes.py 对称注入）
_ab.store_inbound_message = _tools.store_inbound_message
_ab._log_amail = _tools._log_amail
_ab._GatewayClient = _tools._GatewayClient
# 注入点设置（OpenClaw 平台实现；personas 用公共默认空）
_ab._PROFILE_DIR_RESOLVER = _openclaw_profile_dir
# ── 系统能力声明（跨系统共享开关，Hermes 默认 True 不变）────────
# OpenClaw 不支持 persona（角色 = 独立 agentId）→ 设 False。
# preprocess 内部按此开关处理派生地址：False 时归一为基础地址。
_ab.PERSONA_SUPPORTED = False

# ── 目录与配置 ─────────────────────────────────────────────────

def system_dir(system_id: str = "") -> Path:
    """~/.agentmail/{system_id}/（无 system_id 时为 ~/.agentmail/）。"""
    base = Path.home() / ".agentmail"
    return base / system_id if system_id else base


def load_gateway_config(system_id: str = "") -> Optional[dict]:
    """读取 agentmail_gateway.json（{gateway_url, admin_key, domain, system_id, system_name}）。"""
    return _gw.load_gateway_config(system_id)


def load_agents_registry(system_id: str) -> dict:
    """读取 agents.json 注册表 {email → agentId}。"""
    p = system_dir(system_id) / "agents.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def save_agents_registry(system_id: str, registry: dict) -> None:
    p = system_dir(system_id) / "agents.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


def load_agent_config(agent_id: str, system_id: str = "") -> Optional[dict]:
    """读取 agents/<agentId>/config.json（{gateway_url, api_key, email, system_name, mx_domain}）。"""
    if not system_id:
        system_id = detect_system_id()
    p = system_dir(system_id) / "agents" / agent_id / "config.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return None


def save_agent_config(agent_id: str, config: dict, system_id: str = "") -> None:
    if not system_id:
        system_id = config.get("system_id", detect_system_id())
    p = system_dir(system_id) / "agents" / agent_id / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def detect_system_id() -> str:
    """Resolve the OpenClaw system id from the agent pointer file.

    ~/.openclaw/agents/{agent_id}/agent/.agentmail names the system
    (agent_id from AMAIL_AGENT_ID, default "main").  System identity is
    fixed by config — env override is intentionally NOT supported:
    switching system_id must be an explicit config change, not a process
    env tweak.  Never scan ~/.agentmail (that picked the wrong system
    before, e.g. OpenClaw replying as agent.vfy@).
    """
    pointer = Path.home() / ".openclaw" / ".agentmail"
    if pointer.is_file():
        try:
            data = json.loads(pointer.read_text())
            return data.get("system_id", "")
        except Exception:
            pass
    raise SystemExit(
        "no .agentmail pointer at "
        + str(pointer)
        + " - system identity must be explicit"
    )


def load_mode(system_id: str = "") -> dict:
    """读取 mode.json（{"mode": "push"|"pull", ...}）。"""
    if not system_id:
        system_id = detect_system_id()
    p = system_dir(system_id) / "mode.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"mode": "pull"}


def save_mode(system_id: str, mode: dict) -> None:
    p = system_dir(system_id) / "mode.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mode, indent=2, ensure_ascii=False) + "\n")


def load_openclaw_hooks() -> Optional[dict]:
    """读取 ~/.openclaw/openclaw.json 的 hooks 块（token/path）。"""
    p = Path.home() / ".openclaw" / "openclaw.json"
    if p.is_file():
        try:
            cfg = json.loads(p.read_text())
            hooks = cfg.get("hooks") or {}
            if hooks.get("enabled") and hooks.get("token"):
                return hooks
        except Exception:
            pass
    return None


# ── agent 上下文切换（monkey-patch Hermes config 加载）───────────

_ACTIVE_AGENT_CONFIG: Optional[dict] = None


def _openclaw_profile_config() -> Optional[dict]:
    """替换 agentmail_base._load_profile_config 的 OpenClaw 版。"""
    return _ACTIVE_AGENT_CONFIG


def set_agent_context(agent_id: str, system_id: str = "") -> None:
    """把当前 agent 的 config 挂到公共核心的注入点上。

    preprocess_mail_payload()（agentmail_base）与 6 工具函数
    （agentmail_tools）内部都调用 _load_profile_config() —— 公共版读
    _CONFIG_LOADER 注入点，此处设置后两处同时生效（同一函数对象）。
    所有 OpenClaw 侧消费者（amail.py / MCP server / poll / bridge）
    统一走此入口，避免各份重复 patch。
    """
    global _ACTIVE_AGENT_CONFIG
    cfg = load_agent_config(agent_id, system_id)
    if cfg is None:
        raise RuntimeError(f"agent '{agent_id}' not registered — run register_agent.py first")
    _ACTIVE_AGENT_CONFIG = cfg
    _ab._CONFIG_LOADER = _openclaw_profile_config
    os.environ.setdefault("AMAIL_AGENT_ID", agent_id)
    os.environ.setdefault("AMAIL_SYSTEM_ID", cfg.get("system_id", system_id))

# ── 从 agentmail_base 转发（复用面）────────────────────────────
preprocess_mail_payload = _ab.preprocess_mail_payload
parse_amail_persona = _ab.parse_amail_persona
_extract_board_gateway = _ab._extract_board_gateway
register_board_gateway = _ab._register_board_gateway
store_board_credential = _ab._store_board_credential
email_for_agent = _ab.email_for_agent                  # 地址派生（注册/注销脚本共用）
register_agent_email = _ab.register_agent_email        # 注册链
deregister_agent_email = _ab.deregister_agent_email    # 注销链

# gateway_api 标准客户端转发
GatewayClient = _gw.GatewayClient
load_gateway_config_api = _gw.load_gateway_config
whoami = _gw.whoami
create_api_key = _gw.create_api_key


def make_client(api_key: str, system_id: str = ""):
    """按 api_key 构造标准 API 客户端。"""
    gw = load_gateway_config(system_id) if system_id else load_gateway_config(detect_system_id())
    if not gw:
        raise RuntimeError("agentmail_gateway.json not found")
    return GatewayClient(gw["gateway_url"], api_key)


def load_board_module():
    """加载 agentmail_board.py 函数体（裁剪顶层 registry.register 注册块）。

    Hermes 的 agentmail_board.py 顶层注册块引用了本文件不存在的 handler
    （依赖 Hermes 运行时特殊加载），CLI/MCP 场景用 ast 定位并删除注册块后
    exec，只取其函数体（board_* / set_public_whoami）。所有 OpenClaw 侧
    消费者（amail.py / amail_mcp_server.py）统一走此入口。

    同进程内缓存（sys.modules）——避免多次 exec 产生不同函数对象副本。
    """
    cached = sys.modules.get("agentmail_board")
    if cached is not None and hasattr(cached, "board_status"):
        return cached

    import ast as _ast
    import importlib.util as _ilu

    board_path = os.path.join(_TOOLS, "agentmail_board.py")
    src = open(board_path, encoding="utf-8").read()
    tree = _ast.parse(src)
    drop = []
    for node in tree.body:
        if (isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Call)
                and isinstance(node.value.func, _ast.Attribute)
                and node.value.func.attr == "register"):
            drop.append((node.lineno, node.end_lineno))
    lines = src.splitlines()
    src = "\n".join(ln for i, ln in enumerate(lines, 1)
                    if not any(a <= i <= b for a, b in drop))
    spec = _ilu.spec_from_file_location("agentmail_board", board_path)
    board = _ilu.module_from_spec(spec)
    sys.modules["agentmail_board"] = board
    exec(compile(src, board_path, "exec"), board.__dict__)
    return board


def build_message(payload: dict) -> str:
    """把富化后的 amail payload 组装成 agent 输入 message（C2/C5 共用）。

    ⚠ 核心业务逻辑对齐 Hermes：Hermes webhook.py `_render_prompt` 空模板
    fallback 为 `json.dumps(payload, indent=2)[:4000]`（富化 payload 全量
    JSON，ensure_ascii 默认 True）。OpenClaw 必须保持同一渲染语义——
    修订此处时须对照 Hermes 侧确认一致。
    """
    return json.dumps(payload, indent=2)[:4000]


# ── 共享运行时（C2/C5/CLI/MCP 统一入口，修订一处即全局生效）──────

def http_post(url: str, body: dict, api_key: str = "", token: str = "",
              timeout: int = 30) -> dict:
    """统一 JSON POST（amail API 用 X-Api-Key，OpenClaw hooks 用 Bearer）。"""
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if api_key:
        req.add_header("X-Api-Key", api_key)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, **json.loads(r.read())}
    except urllib.error.HTTPError as e:
        try:
            return {"status": e.code, **json.loads(e.read())}
        except Exception:
            return {"status": e.code, "error": str(e)}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def agent_for_email(registry: dict, email: str) -> str:
    """收件地址 → agentId（精确匹配 + persona 前缀剥离：support.alice@… → alice@…）。"""
    if email in registry:
        return registry[email]
    local = email.split("@")[0]
    for addr, agent_id in registry.items():
        base_local = addr.split("@")[0]
        if local and local.endswith("." + base_local):
            return agent_id
    return ""


# is_ping/is_pong/ping_id/handle_ping_pong come from agentmail_base
# (the shared Hermes + OpenClaw layer) — single implementation.
PONG_PREFIX = "__agentmail_pong__:"


PING_PREFIX = _ab.PING_PREFIX
PONG_PREFIX = _ab.PONG_PREFIX
is_ping = _ab.is_ping
is_pong = _ab.is_pong
ping_id = _ab.ping_id
handle_ping_pong = _ab.handle_ping_pong


# handle_ping_pong is imported from amail_common (single shared impl).


def send_pong(payload: dict, pong_id_value: str) -> bool:
    """ping → pong：调 amail.py send 回发（对齐 Hermes webhook.py 补丁）。"""
    import subprocess
    to = payload.get("from", "")
    body = json.dumps({"ping_id": pong_id_value,
                       "event": {"mail_id": payload.get("mail_id", "")}})
    amail_cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amail.py")
    r = subprocess.run(
        [sys.executable, amail_cli,
         "send", "--to", to, "--subject", f"{PONG_PREFIX}{pong_id_value}",
         "--body", body, "--message-id", str(payload.get("mail_id", ""))],
        capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout).get("success", False)
    except Exception:
        return False


def dispatch_to_hooks(hooks_url: str, hooks_token: str, agent_id: str,
                      payload: dict, idempotency_key: str,
                      extra_system_prompt: str = "", headers: dict = None,
                      system_id: str = "") -> dict:
    """统一入站投递链：set context → preprocess → build_message → POST /hooks/agent。

    C2（bridge）与 C5（poll）共用，修订富化/组装/注入逻辑只改此处。
    persona 能力差异由 PERSONA_SUPPORTED 驱动（Hermes 保留派生地址，
    OpenClaw 归一为基础地址），处理框架与 Hermes 完全一致。
    返回 hooks 响应（含 status；200/201/202 = 受理成功）。
    """
    set_agent_context(agent_id, system_id)
    enriched = preprocess_mail_payload(dict(payload), headers or {})
    # persona 差异由共享开关驱动（agentmail_base.PERSONA_SUPPORTED），
    # preprocess 内部已按开关归一/保留派生地址——此处无需后处理。
    req = {
        "message": build_message(enriched),
        "agentId": agent_id,
        "idempotencyKey": idempotency_key,
    }
    if extra_system_prompt:
        req["extraSystemPrompt"] = extra_system_prompt
    return http_post(hooks_url, req, token=hooks_token, timeout=60)
