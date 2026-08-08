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