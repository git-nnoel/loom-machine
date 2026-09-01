"""MCP server adapter. stdout is the JSON-RPC channel and carries nothing else.

Four read-only tools over one library — `list_artifacts`, `search_artifacts`, `get_artifact` and
`get_reference` — named once, in `tools.TOOLS`. `cli/` opens the library and hands it in
(ruling R28); nothing here resolves a root or reads the environment.

Everything a caller needs is re-exported, so `cli/main.py` imports one module path and never has to
know which module a name lives in.
"""

from harness_library.mcp.dispatch import call_tool
from harness_library.mcp.server import (
    INSTRUCTIONS,
    SERVER_NAME,
    build_server,
    describe,
    serve,
    serve_stdio,
    server_version,
)
from harness_library.mcp.tools import TOOLS, TOOLS_BY_NAME, ToolSpec

__all__ = [
    "INSTRUCTIONS",
    "SERVER_NAME",
    "TOOLS",
    "TOOLS_BY_NAME",
    "ToolSpec",
    "build_server",
    "call_tool",
    "describe",
    "serve",
    "serve_stdio",
    "server_version",
]
