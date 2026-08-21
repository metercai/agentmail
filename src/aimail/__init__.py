# -*- coding: utf-8 -*-
"""aimail — AgentMail runtime SDK (Python).

Runtime payload package, equivalent to the TS @aimail/* npm packages:
core gateway client + platform adapters + resource files. Installation,
provisioning and maintenance tools stay in the agentmail source repository.

Module layout mirrors the repository tools/ directory so existing
sys.path bootstrap logic keeps working unchanged:

  aimail/
    agentmail_base.py        shared core (platform-agnostic)
    agentmail_tools.py       shared core (GatewayClient / send_mail)
    agentmail_board.py       shared core (A2A board)
    gateway_api.py           standard amail API client
    amail_mcp_server.py      platform-agnostic MCP server (stdio JSON-RPC)
    _aimail_bootstrap.py     location-agnostic sys.path bootstrap (runtime glue)
    hermes/agentmail_hermes.py   Hermes adapter
    openclaw/                 OpenClaw adapter (CLI / bridge / shared)
    deer-flow/                DeerFlow adapter (inbound router / shared)
    skills/                   agentmail SKILL.md + DESCRIPTION.md
    board_role_prompt_en/     board role prompt templates (en)

Usage as a library:
    import aimail
    import sys
    sys.path.insert(0, aimail.core_dir())   # enables flat-script imports
    import agentmail_tools                  # GatewayClient / send_mail / ...
    import agentmail_base                   # preprocess / parse / persona / board
    # MCP server: run str(aimail.mcp_server_path()) as a stdio subprocess
"""

import os as _os

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "root",
    "core_dir",
    "skills_dir",
    "board_role_prompt_dir",
    "mcp_server_path",
]


def root() -> str:
    """Absolute path of this package directory."""
    return _os.path.dirname(_os.path.abspath(__file__))


def core_dir() -> str:
    """Directory holding the flat-script core modules (agentmail_base.py ...).

    Insert this on sys.path to enable the runtime's flat imports:

        import sys, aimail
        sys.path.insert(0, aimail.core_dir())
        import agentmail_base
    """
    return root()


def skills_dir() -> str:
    """agentmail SKILL.md / DESCRIPTION.md directory."""
    return _os.path.join(root(), "skills")


def board_role_prompt_dir() -> str:
    """Board role prompt templates (English) directory."""
    return _os.path.join(root(), "board_role_prompt_en")


def mcp_server_path() -> str:
    """Path of the platform-agnostic MCP server entry script."""
    return _os.path.join(root(), "amail_mcp_server.py")
