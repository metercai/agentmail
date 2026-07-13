"""agentmail_board — Board query tools for A2A Board collaboration."""
from __future__ import annotations
import json
import logging
import os
import re
import secrets
import hashlib
import threading
import time
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any

from agentmail_tools import _GatewayClient
from agentmail_base import _load_profile_config


logger = logging.getLogger(__name__)
_TOOLSET = "agentmail"


registry.register(
    name="set_email_summary",
    toolset=_TOOLSET,
    schema={
        "name": "set_email_summary",
        "description": (
            "Store or update the summary for an email thread. "
            "Pass any message_id from the thread -- the tool resolves "
            "the canonical thread_id automatically. "
            "Pass an empty string as summary to clear it. "
            "Call this after processing an inbound email to persist the updated state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Any message_id from the thread (usually the current inbound email's message_id).",
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "Plain-text summary of all active topics in the thread. "
                        "For each topic: one short sentence on what's being decided "
                        "plus current status or next step (e.g. 'waiting for David'). "
                        "Fully resolved topics: either remove entirely or mark [DONE] "
                        "and drop after one more round. "
                        "Multiple topics: numbered or bullet lines (max 5). "
                        "Single topic: a short paragraph is fine. "
                        "Keep it actionable — future you must understand open items "
                        "within seconds. Do NOT archive the email chain; only distill "
                        "active decisions, pending actions, and unresolved questions. "
                        "Max 2000 characters. Empty string clears the summary."
                    ),
                },
            },
            "required": ["message_id", "summary"],
        },
    },
    handler=_handle_set_email_summary,
    emoji="📝",
)


# ═══════════════════════════════════════════════════════════════
# a2a_board toolset — board query tools for role prompts
# ═══════════════════════════════════════════════════════════════

def _resolve_board(task_id: str) -> str:
    """Extract board_id from task_id."""
    if task_id.startswith("t_"):
        parts = task_id.split("_", 2)
        if len(parts) >= 2:
            return parts[1]
    if task_id.startswith("board:"):
        parts = task_id.split(":", 2)
        if len(parts) >= 2:
            return parts[1]
    return ""

def _resolve_gateway_url(task_id: str) -> str:
    """Return gateway URL for the board of this task."""
    board_id = _resolve_board(task_id)
    cfg = _load_profile_config()
    if not cfg or not board_id:
        return cfg.get("gateway_url", "") if cfg else ""
    gateway_url = _board_gateways.get(board_id, "")
    if not gateway_url:
        gateway_url = cfg.get("gateway_url", "")
    return gateway_url

def _get_board_token(board_id: str) -> Optional[str]:
    """Get board token from persisted creds file."""
    try:
        import json as _json
        cfg = _load_profile_config()
        sid = cfg.get("system_id", "default") if cfg else "default"
        creds_path = Path.home() / ".agentmail" / sid / "board_creds.json"
        if creds_path.exists():
            creds = _json.loads(creds_path.read_text())
            return creds.get(board_id, {}).get("token")
    except Exception:
        pass
    return None


def board_task_show(task_id: str) -> str:
    """查询任务详情。返回 task 的所有字段（body、status、assignee、reviewer 等）。"""
    import json
    cfg = _load_profile_config()
    if not cfg:
        return "{\"error\": \"no profile config\"}"
    gateway_url = _resolve_gateway_url(task_id)
    token = _get_board_token(board_id) if board_id else None
    if token:
        client = _GatewayClient(gateway_url, token)
    else:
        client = _GatewayClient(gateway_url, cfg["api_key"])
    board_id = _resolve_board(task_id)
    if not board_id:
        return "{\"error\": \"cannot resolve board_id from task_id\"}"
    try:
        r = client._request("GET", f"/api/v1/board/{board_id}/task/{task_id}")
        return json.dumps(r, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def board_task_list(board: str, status: str = "", assignee: str = "") -> str:
    """按条件过滤 task 列表。支持 status、assignee 过滤。常用于巡视。"""
    import json
    cfg = _load_profile_config()
    if not cfg:
        return "{\"error\": \"no profile config\"}"
    gateway_url = _resolve_gateway_url(task_id)
    token = _get_board_token(board_id) if board_id else None
    if token:
        client = _GatewayClient(gateway_url, token)
    else:
        client = _GatewayClient(gateway_url, cfg["api_key"])
    params = {}
    if status:
        params["status"] = status
    if assignee:
        params["assignee"] = assignee
    try:
        r = client._request("GET", f"/api/v1/board/{board}/tasks", params=params)
        return json.dumps(r, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})



def board_members(board_id: str, email: str = "") -> str:
    """列出 Board 成员。可选按 email 过滤。"""
    import json, urllib.parse
    cfg = _load_profile_config()
    if not cfg:
        return json.dumps({"error": "no profile config"})
    gateway_url = _resolve_gateway_url(task_id)
    token = _get_board_token(board_id) if board_id else None
    if token:
        client = _GatewayClient(gateway_url, token)
    else:
        client = _GatewayClient(gateway_url, cfg["api_key"])
    try:
        path = f"/api/v1/board/{board_id}/members"
        if email:
            path += f"?email={urllib.parse.quote(email)}"
        return json.dumps(client._request("GET", path), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

def board_roles(board_id: str, role: str = "") -> str:
    """获取 Board 角色权限表。可选按 role 过滤返回该角色的成员和权限。"""
    import json, urllib.parse
    cfg = _load_profile_config()
    if not cfg:
        return json.dumps({"error": "no profile config"})
    gateway_url = _resolve_gateway_url(task_id)
    token = _get_board_token(board_id) if board_id else None
    if token:
        client = _GatewayClient(gateway_url, token)
    else:
        client = _GatewayClient(gateway_url, cfg["api_key"])
    try:
        path = f"/api/v1/board/{board_id}/roles"
        if role:
            path += f"?role={urllib.parse.quote(role)}"
        return json.dumps(client._request("GET", path), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

def board_status(board_id: str) -> str:
    """获取 Board 状态总览：管线分布 + 依赖关系 + 负责人。"""
    import json
    cfg = _load_profile_config()
    if not cfg: return json.dumps({"error": "no profile config"})
    gateway_url = _resolve_gateway_url(task_id)
    token = _get_board_token(board_id) if board_id else None
    if token:
        client = _GatewayClient(gateway_url, token)
    else:
        client = _GatewayClient(gateway_url, cfg["api_key"])
    try:
        return json.dumps(client._request("GET", f"/api/v1/board/{board_id}/status"), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

def board_heartbeat(task_id: str, note: str = "") -> str:
    """发心跳更新任务时间戳。长任务期间定期调用，让Board/Orchestrator知道任务仍在进行。"""
    import json
    cfg = _load_profile_config()
    if not cfg:
        return "{\"error\": \"no profile config\"}"
    gateway_url = _resolve_gateway_url(task_id)
    token = _get_board_token(board_id) if board_id else None
    if token:
        client = _GatewayClient(gateway_url, token)
    else:
        client = _GatewayClient(gateway_url, cfg["api_key"])
    board_id = _resolve_board(task_id)
    if not board_id:
        return "{\"error\": \"cannot resolve board_id from task_id\"}"
    try:
        r = client._request("POST", f"/api/v1/board/{board_id}/task/{task_id}/heartbeat?actor=toolset",
                            body={"note": note})
        return json.dumps(r, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── a2a tool registration ──
try:
    registry.register(
        name="board_task_show",
        toolset=_TOOLSET,
        schema={
            "name": "a2a_show",
            "description": "查询任务详情。返回 task 的所有字段。比发邮件快，零 SMTP 往返。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "任务 ID（如 t_a1b2c3d4）"
                    }
                },
                "required": ["task_id"]
            }
        },
        handler=board_task_show,
        emoji="📋",
    )

    registry.register(
        name="board_task_list",
        toolset=_TOOLSET,
        schema={
            "name": "a2a_list",
            "description": "按条件过滤 task 列表。Orchestrator 巡视用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "看板 ID"},
                    "status": {"type": "string", "description": "过滤状态（running/blocked/done）"},
                    "assignee": {"type": "string", "description": "过滤负责人 email"}
                },
                "required": ["board"]
            }
        },
        handler=board_task_list,
        emoji="📋",
    )

    registry.register(
        name="board_members",
        toolset=_TOOLSET,
        schema={
            "name": "a2a_members",
            "description": "查询某 Board 的成员列表及角色。",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "看板 ID"}
                },
                "required": ["board"]
            }
        },
        handler=board_members,
        emoji="👥",
    )

    registry.register(
        name="board_heartbeat",
        toolset=_TOOLSET,
        schema={
            "name": "a2a_heartbeat",
            "description": "发心跳更新任务时间戳。长任务用此工具代替发邮件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"},
                    "note": {"type": "string", "description": "进度备注（可选）"}
                },
                "required": ["task_id"]
            }
        },
        handler=board_heartbeat,
        emoji="💓",
    )
except Exception as _e:
    logger.warning("[a2a_board] tool registration failed: %s", _e)

try:
    registry.register(
        name="set_public_whoami",
        toolset=_TOOLSET,
        schema={
            "name": "a2a_set_public_whoami",
            "description": "Set Agent public identity card for stranger [WHOAMI] queries",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Public identity text"}
                },


def set_public_whoami(text: str) -> str:
    """Set Agent public WHOAMI card for stranger queries."""
    import json
    cfg = _load_profile_config()
    if not cfg: return json.dumps({"error": "no profile config"})
    client = _GatewayClient(cfg["gateway_url"], cfg["api_key"])
    try:
        r = client.agent_state_put("public_whoami", text)
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})
