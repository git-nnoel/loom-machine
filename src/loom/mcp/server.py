"""The read-only MCP server, and the stdio transport `loom mcp` runs it on.

**stdout is the JSON-RPC channel and carries nothing else** (charter §11, decision D8). A single
stray byte kills the client connection and surfaces as a malformed stream with no diagnosable
cause, which is why this server is its own process and why nothing in it prints. Two mechanisms
keep that true, and they cover different windows:

* the SDK's `stdio_server()` points **fd 1 at stderr** while it serves and writes the wire through
  a private duplicate of the original descriptor, so a stray write from a handler misses the
  client;
* **before** the transport claims that descriptor — logging setup, root resolution, opening the
  library — nothing is diverted and charter §11 holds on its own. That window is exactly where
  `tests/mcp/test_stdout_purity.py` aims, because it is the only one a mechanism does not cover.

**The server is read-only structurally, not by promise.** `mcp/` may not import
`application.write`; the `mcp-is-read-only` import contract fails the suite if that ever changes,
and `tests/test_architecture.py` fails with it.

**The transport is stdio and only stdio.** `starlette`, `uvicorn` and `sse-starlette` arrive in the
environment as transitive dependencies of the SDK and are deliberately unused: decision D8 fixes
the transport, and an HTTP path here would reopen a decision the specification closed. Initiative
03 serves HTTP from its own process, over the same `application/read` surface.
"""

from __future__ import annotations

import asyncio
from importlib import metadata
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from loom.domain.repository import ArtifactRepository
from loom.mcp.dispatch import call_tool
from loom.mcp.tools import TOOLS, ToolSpec

SERVER_NAME = "loom-machine"
"""How the server introduces itself in the initialize handshake."""

INSTRUCTIONS = (
    "A read-only view of a Claude Code harness library: its skills, its agents, their references "
    "and their validation findings. Call `list_artifacts` first to see what exists, "
    "`search_artifacts` to find a phrase across entry documents and markdown references, and "
    "`get_artifact` for one artifact in full. Prefer `get_reference` when you need a single "
    "reference file: these skills are reference-heavy and the entry document alone can run to "
    "hundreds of lines."
)


def server_version() -> str:
    """The installed package version, or `0.0.0` when the package is not installed.

    Read from the distribution metadata rather than restated, so the version a client sees in the
    handshake cannot drift from the one in `pyproject.toml`.
    """
    try:
        return metadata.version("loom-machine")
    except metadata.PackageNotFoundError:  # pragma: no cover - only when running from a raw tree
        return "0.0.0"


def describe(tool: ToolSpec[Any, Any]) -> types.Tool:
    """One registry entry as the client sees it in `tools/list`.

    Both schemas are generated from the entry's own models, so what is advertised and what is
    produced cannot disagree. Declaring `outputSchema` is what lets the client revalidate every
    result against contract C-7 — the guarantee that `mcp/` renders the same payload the CLI's
    `--json` does, enforced rather than asserted.
    """
    return types.Tool(
        name=tool.name,
        title=tool.title,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        annotations=types.ToolAnnotations(read_only_hint=True, destructive_hint=False),
    )


def build_server(repository: ArtifactRepository) -> Server[object]:
    """The server, over a library the caller has already opened.

    The repository arrives ready (ruling R28): `cli/` owns the composition root, so `mcp/` never
    resolves a library root, never reads the environment and cannot disagree with the CLI about
    which library is being served.

    Both handlers are thin. `tools/list` maps over `TOOLS`; `tools/call` hands off to the
    synchronous dispatcher. Neither holds a name, a schema or a branch of its own — the registry is
    the single source and this is the only place it is read.
    """

    async def on_list_tools(
        context: object, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[describe(tool) for tool in TOOLS])

    async def on_call_tool(
        context: object, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        return call_tool(repository, params.name, params.arguments)

    return Server(
        SERVER_NAME,
        version=server_version(),
        title="Harness library",
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def serve(repository: ArtifactRepository) -> None:
    """Serve one stdio connection until the client closes it."""
    server = build_server(repository)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve_stdio(repository: ArtifactRepository) -> None:
    """Run the server on this process's stdin and stdout. Returns when the client disconnects.

    `asyncio.run` rather than `anyio.run`: the transport runs unchanged on a plain asyncio loop,
    and the standard library is one fewer name in the import graph than the SDK's own runtime.
    """
    asyncio.run(serve(repository))


__all__ = [
    "INSTRUCTIONS",
    "SERVER_NAME",
    "build_server",
    "describe",
    "serve",
    "serve_stdio",
    "server_version",
]
