"""`tools/call`, as one synchronous function.

Kept out of `server.py` and kept synchronous on purpose: every read use case is a plain call, so
the only thing async about this server is its transport. A sync dispatcher is testable directly —
no event loop, no client, no subprocess — which leaves the wire tests free to prove the things only
a wire can prove.

**Ruling R24 lands here.** An unknown artifact id, an unreadable file, an empty query and a
collection the library does not declare are all `HarnessLibraryError`s with stable codes, and every
one of them crosses the pipe as an MCP **error result** — never as an exception. A tool that let an
exception escape would show up at the client as a transport-level fault with nothing in it a caller
could branch on.

**The error envelope is the CLI's, verbatim**: `{"error": {"code", "message"}}`, with `code` null
when no `ErrorCode` covers the condition. An unknown tool name and malformed arguments are client
mistakes that the taxonomy has no code for, and charter §9 forbids inventing one at a raise site —
the same reason `LibraryRootError` carried no code until ruling R29 put one in the contract.

**Ruling R3: one log line per tool call**, on stderr, whatever the outcome.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types
import structlog
from pydantic import ValidationError

from loom.domain.errors import HarnessLibraryError
from loom.domain.repository import ArtifactRepository
from loom.mcp.tools import TOOLS_BY_NAME


def _log() -> structlog.stdlib.BoundLogger:
    """A bound logger, resolved **at write time**.

    `mcp/` may not import `cli/` — ruling R28 puts `cli` above it — so the stderr-only
    configuration is applied by the process entry point (`loom mcp` runs through the Typer
    callback, which calls `cli.logging.configure_logging`) and read here through structlog's
    global configuration. Resolving per call rather than at import is lesson L27: a logger
    bound at import writes into whatever stream existed then, so a test replacing `sys.stderr`
    afterwards would watch an empty stream and pass for the wrong reason.

    The transport is a second line of defence, not the first: while `stdio_server()` serves, it
    points fd 1 at stderr and writes the wire through a private duplicate, so a stray write
    during a tool call misses the client. Charter §11 still has to hold on its own before the
    transport claims that descriptor.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger("loom.mcp")
    return logger


def call_tool(
    repository: ArtifactRepository, name: str, arguments: dict[str, Any] | None
) -> types.CallToolResult:
    """Run one tool and answer with a result — successful or errored, never an exception.

    Args:
        repository: the library, opened by the composition root and handed in. `mcp/` never
            resolves a root of its own (ruling R28).
        name: the tool the client asked for.
        arguments: the client's raw arguments, validated against the tool's own model.

    Returns:
        A `CallToolResult` carrying the contract C-7 payload as both text and structured content,
        or an error result carrying the taxonomy's code.
    """
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        _log().info("mcp.tool_call", tool=name, ok=False, error="UNKNOWN_TOOL")
        known = ", ".join(sorted(TOOLS_BY_NAME))
        return _error(None, f"no such tool {name!r}; this server offers {known}")

    try:
        payload = tool.invoke(repository, arguments or {})
    except ValidationError as error:
        # A client mistake, not a library fault: no `ErrorCode` covers it and §9 forbids minting
        # one here. The Pydantic report names the offending field, which is the whole diagnosis.
        _log().info("mcp.tool_call", tool=name, ok=False, error="INVALID_ARGUMENTS")
        return _error(None, f"invalid arguments for {name}: {error}")
    except HarnessLibraryError as error:
        # Ruling R24: the taxonomy crosses the pipe as a result a caller can branch on.
        _log().info("mcp.tool_call", tool=name, ok=False, error=error.code.value)
        return _error(error.code.value, str(error))

    # Anything else is a bug rather than a diagnosis, and is deliberately not caught: the SDK
    # answers it as a JSON-RPC error, so it still does not crash the connection, and it stays
    # visible as a fault instead of being flattened into an empty result.
    _log().info("mcp.tool_call", tool=name, ok=True)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=payload.model_dump_json(indent=2))],
        structured_content=payload.model_dump(mode="json"),
    )


def _error(code: str | None, message: str) -> types.CallToolResult:
    """An MCP error result carrying the CLI's error envelope.

    The envelope is JSON in the text block as well as being the result's error flag, so a client
    that only reads text still gets the machine `code` — which is the branchable value, where the
    message is prose and may be reworded without notice.
    """
    envelope = {"error": {"code": code, "message": message}}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(envelope, indent=2))],
        is_error=True,
    )


__all__ = ["call_tool"]
