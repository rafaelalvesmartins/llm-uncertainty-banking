# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""MCP tool surface for llm-uncertainty-banking.

Exposes the library's public API as Model Context Protocol tools so any
Claude Code session or ruflo swarm can call it. The server speaks
JSON-RPC over stdio and is registered via the ``lub-mcp-server``
console script.

Hand-written workflow tools (5) live in :mod:`lub.mcp.server`. Auto-
generated estimator and metric tools (~29) live in :mod:`lub.mcp.tools`
and are appended at server-build time so importing this package stays
cheap.

The ``mcp`` PyPI package is an optional dependency; install with
``pip install 'llm-uncertainty-banking[mcp]'`` to enable the runtime.
"""

from __future__ import annotations

from lub.mcp.server import TOOLS, build_server, list_all_tools, run_stdio

__all__ = ["TOOLS", "build_server", "list_all_tools", "run_stdio"]
