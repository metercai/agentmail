#!/usr/bin/env python3
"""Shared gateway utilities — re-exports from tools/hermes/ for script use.

tools/hermes/ contains the full Hermes runtime (agentmail_base,
agentmail_tools, agentmail_board).  Scripts in scripts/ should only
import the minimal set of symbols defined here.
"""
import sys
from pathlib import Path

# Ensure tools/hermes/ is on sys.path for the underlying imports.
_tools_hermes = str(Path(__file__).resolve().parent / "hermes")
if _tools_hermes not in sys.path:
    sys.path.insert(0, _tools_hermes)

from agentmail_tools import _GatewayClient  # noqa: E402
from agentmail_base import (               # noqa: E402
    _gateway_config_path,
    _load_gateway_config,
    _agentmail_system_dir,
)

__all__ = [
    "_GatewayClient",
    "_gateway_config_path",
    "_load_gateway_config",
    "_agentmail_system_dir",
]
