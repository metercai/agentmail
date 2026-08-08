#!/usr/bin/env python3
"""amail_mcp_server.py — OpenClaw agentmail MCP server（stdio）。

暴露 Hermes 等价工具集（结构化调用，替代 CLI 方式）：
  send_mail / manage_contacts / contact_profile / set_contact_profile
  email_summary / set_email_summary / board_*（A2A）

agent 上下文：env AMAIL_AGENT_ID（mcp.servers.<name>.env 配置，默认 main）。
每工具也可显式传 agentId 参数覆盖（多 agent 共享 server 时）。

零第三方依赖：纯标准库 JSON-RPC over stdio。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "openclaw"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "hermes"))

import amail_base as _base            # noqa: E402
import agentmail_tools as _tools      # noqa: E402


# ── MCP stdio 帧（OpenClaw 打包的 SDK 用 newline-delimited JSON，
#    不支持 Content-Length 帧）─────────────────────────────────

def read_msg():
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    return json.loads(line)


def write_msg(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ── agent 上下文 ────────────────────────────────────────────────

def _agent_ctx(agent_id: str = "") -> str:
    """确定当前 agentId（显式参数 > env）并切换上下文（统一走 amail_base）。"""
    aid = agent_id or os.environ.get("AMAIL_AGENT_ID", "main")
    _base.set_agent_context(aid)
    return aid


def _safe(fn):
    """工具调用包装：异常 → MCP error。"""
    try:
        return {"ok": True, **fn()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 工具实现 ────────────────────────────────────────────────────

def tool_send_mail(args: dict) -> dict:
    def fn():
        return _tools.send_mail(
            to=args.get("to", ""),
            subject=args.get("subject", ""),
            body=args.get("body", ""),
            cc=args.get("cc"),
            attachments=args.get("attachments"),
            message_id=args.get("message_id"),
        )
    return _safe(fn)


def tool_manage_contacts(args: dict) -> dict:
    def fn():
        return _tools.manage_contacts(
            action=args.get("action", "check"),
            address=args.get("address"),
            direction=args.get("direction", "all"),
        )
    return _safe(fn)


def tool_contact_profile(args: dict) -> dict:
    def fn():
        return _tools.contact_profile(address=args.get("address", ""), name=args.get("name", ""))
    return _safe(fn)


def tool_set_contact_profile(args: dict) -> dict:
    def fn():
        return _tools.set_contact_profile(address=args.get("address", ""),
                                          profile=args.get("profile", ""))
    return _safe(fn)


def tool_email_summary(args: dict) -> dict:
    def fn():
        return _tools.email_summary(message_id=args.get("message_id", ""))
    return _safe(fn)


def tool_set_email_summary(args: dict) -> dict:
    def fn():
        return _tools.set_email_summary(message_id=args.get("message_id", ""),
                                        summary=args.get("summary", ""))
    return _safe(fn)


def tool_board_status(args: dict) -> dict:
    def fn():
        return {"status": _board.board_status(args.get("board", ""))}
    return _safe(fn)


def tool_board_task_list(args: dict) -> dict:
    def fn():
        return {"tasks": _board.board_task_list(args.get("board", ""),
                                                args.get("status", ""),
                                                args.get("assignee", ""))}
    return _safe(fn)


def tool_board_task_show(args: dict) -> dict:
    def fn():
        return {"task": _board.board_task_show(args.get("task_id", ""))}
    return _safe(fn)


def tool_board_heartbeat(args: dict) -> dict:
    def fn():
        return {"result": _board.board_heartbeat(args.get("task_id", ""), args.get("note", ""))}
    return _safe(fn)


# ── 工具注册表 ──────────────────────────────────────────────────

SCHEMA_STR = {"type": "string"}
TOOLS = [
    {"name": "send_mail", "description": (
        "Send an email via your agentmail address. For replies: pass the inbound "
        "message_id — the tool resolves In-Reply-To/References and sender persona "
        "automatically. For new emails: omit message_id. After sending, call "
        "set_email_summary to refine the thread summary."),
     "inputSchema": {"type": "object", "properties": {
         "to": {"type": "string", "description": "Comma-separated recipients"},
         "subject": SCHEMA_STR, "body": {"type": "string", "description": "Markdown body"},
         "cc": {"type": "string", "description": "Comma-separated CC"},
         "attachments": {"type": "array", "items": {"type": "string"},
                         "description": "Local file paths"},
         "message_id": {"type": "string", "description": "Inbound message_id for threading"},
     }, "required": ["to", "subject", "body"]}},
    {"name": "manage_contacts", "description": (
        "Manage your address book (whitelist). check: verify address allowed "
        "(in_contacts). add: sends approval request to manager. remove: delete. "
        "update: change direction. direction: from/to/all."),
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["check", "add", "remove", "update"]},
         "address": {"type": "string", "description": "email address"},
         "direction": {"type": "string", "enum": ["from", "to", "all"], "default": "all"},
     }, "required": ["action"]}},
    {"name": "contact_profile", "description": (
        "Look up a contact profile by address or name. Returns profile fields "
        "(name/title/location/focus/close_contacts/style) or ambiguous candidates."),
     "inputSchema": {"type": "object", "properties": {
         "address": SCHEMA_STR, "name": SCHEMA_STR}, "required": []}},
    {"name": "set_contact_profile", "description": (
        "Store or update a contact profile (JSON merge on gateway). Only write "
        "fields that changed; + prefix appends, - removes."),
     "inputSchema": {"type": "object", "properties": {
         "address": SCHEMA_STR, "profile": {"type": "string", "description": "JSON string"}},
         "required": ["address", "profile"]}},
    {"name": "email_summary", "description": (
        "Retrieve the stored thread summary for a message_id (pre-loaded as "
        "thread_summary in inbound payloads; call when you need to re-read)."),
     "inputSchema": {"type": "object", "properties": {"message_id": SCHEMA_STR},
                     "required": ["message_id"]}},
    {"name": "set_email_summary", "description": (
        "Store or update the summary for an email thread. Call after processing "
        "an inbound email to persist updated state. Empty summary clears."),
     "inputSchema": {"type": "object", "properties": {
         "message_id": SCHEMA_STR,
         "summary": {"type": "string", "description": "Actionable thread summary, max 2000 chars"}},
         "required": ["message_id", "summary"]}},
    {"name": "board_status", "description": "Query A2A board status.",
     "inputSchema": {"type": "object", "properties": {"board": SCHEMA_STR}, "required": []}},
    {"name": "board_task_list", "description": "List A2A board tasks (filter by status/assignee).",
     "inputSchema": {"type": "object", "properties": {
         "board": SCHEMA_STR, "status": SCHEMA_STR, "assignee": SCHEMA_STR}, "required": []}},
    {"name": "board_task_show", "description": "Show A2A board task detail.",
     "inputSchema": {"type": "object", "properties": {"task_id": SCHEMA_STR}, "required": ["task_id"]}},
    {"name": "board_heartbeat", "description": "Post a heartbeat note to an A2A task.",
     "inputSchema": {"type": "object", "properties": {"task_id": SCHEMA_STR, "note": SCHEMA_STR},
                     "required": ["task_id"]}},
]

HANDLERS = {
    "send_mail": tool_send_mail,
    "manage_contacts": tool_manage_contacts,
    "contact_profile": tool_contact_profile,
    "set_contact_profile": tool_set_contact_profile,
    "email_summary": tool_email_summary,
    "set_email_summary": tool_set_email_summary,
    "board_status": tool_board_status,
    "board_task_list": tool_board_task_list,
    "board_task_show": tool_board_task_show,
    "board_heartbeat": tool_board_heartbeat,
}

# board 函数体（统一走 amail_base.load_board_module，与 amail.py 共用）
_board = _base.load_board_module()


# ── MCP 主循环 ──────────────────────────────────────────────────

def main() -> int:
    while True:
        msg = read_msg()
        if msg is None:
            break
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}

        if method == "initialize":
            write_msg({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "amail-mcp", "version": "1.0.0"},
            }})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            write_msg({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            handler = HANDLERS.get(name)
            if not handler:
                write_msg({"jsonrpc": "2.0", "id": mid,
                           "error": {"code": -32601, "message": f"unknown tool {name}"}})
                continue
            # agent 上下文：显式 agentId 参数 > env
            agent_id = args.pop("agentId", "") if isinstance(args, dict) else ""
            try:
                _agent_ctx(agent_id)
            except RuntimeError as e:
                write_msg({"jsonrpc": "2.0", "id": mid,
                           "error": {"code": -32000, "message": str(e)}})
                continue
            result = handler(args)
            text = json.dumps(result, ensure_ascii=False)
            write_msg({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}]}})
        elif method == "ping":
            write_msg({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            write_msg({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32601, "message": f"unknown method {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
