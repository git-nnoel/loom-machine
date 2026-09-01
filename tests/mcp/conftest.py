"""Shared scaffolding for the MCP suite — two ways to talk to a **real** `hl mcp` process.

Charter §10 tests this adapter over real JSON-RPC frames, and nothing here fakes the transport.
Two levels, because they prove different things:

* `speak` drives a raw, line-oriented exchange over a pipe. It is the only level at which
  "stdout carries nothing but JSON-RPC frames" is a statement about **bytes**, which is what
  charter §11 actually requires.
* `with_client` drives the MCP SDK's own client through a real handshake. It is the only level at
  which protocol negotiation happens, and it is what revalidates every tool result against the
  `outputSchema` the server declared — so contract C-7 is enforced by the client rather than
  asserted by us.

Both spawn `python -m harness_library.cli.main … mcp`. `pyproject.toml` still declares no
`[project.scripts]`, so there is no `hl` on PATH to spawn; the module entry point is the same code
by the same route.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_LIBRARY = REPO_ROOT / "tests" / "fixtures" / "library"

SPAWN_TIMEOUT_SECONDS = 60.0
"""A watchdog, not a tuning knob: a server that never answers must fail the suite, not hang it."""


@pytest.fixture
def fixture_library() -> Path:
    """The committed fixture library's root."""
    assert FIXTURE_LIBRARY.is_dir(), (
        f"the committed fixture library is missing from {FIXTURE_LIBRARY}. Charter §10: it is the "
        "regression suite for the reason this product exists and is never deleted."
    )
    return FIXTURE_LIBRARY


def spawn_arguments(library: Path | None, *extra: str) -> list[str]:
    """The command a client spawns, as a client would spawn it."""
    root = [] if library is None else ["--library", str(library)]
    return [sys.executable, "-m", "harness_library.cli.main", *root, "mcp", *extra]


@dataclass
class Conversation:
    """Everything a raw exchange produced, kept as text so a test can assert about bytes.

    Attributes:
        stdout: every byte the process wrote to stdout, decoded.
        stderr: every byte it wrote to stderr, decoded.
        exit_code: the process's status.
        responses: the stdout lines parsed as JSON, in order.
    """

    stdout: str
    stderr: str
    exit_code: int
    responses: list[dict[str, Any]] = field(default_factory=list)

    def response(self, request_id: int) -> dict[str, Any]:
        """The response to one request id. Fails loudly rather than returning a default."""
        for response in self.responses:
            if response.get("id") == request_id:
                return response
        raise AssertionError(f"no response with id {request_id} in:\n{self.stdout}")

    def result(self, request_id: int) -> dict[str, Any]:
        """The `result` of one response, asserting the server did not answer with an error."""
        response = self.response(request_id)
        assert "error" not in response, f"JSON-RPC error for id {request_id}: {response}"
        result: dict[str, Any] = response["result"]
        return result


def speak(
    frames: Sequence[dict[str, Any]],
    *,
    library: Path | None,
    extra: Sequence[str] = (),
    expect_responses: int | None = None,
) -> Conversation:
    """Send raw JSON-RPC frames to a real `hl mcp` process and collect everything it wrote.

    Responses are read **before** stdin is closed. Closing it first races the server's shutdown
    against its last write, and a test that lost the final frame to that race would be flaky in the
    one direction that looks like a bug in the code under test.

    Args:
        frames: the request and notification frames, in order. One line each, as the transport
            expects.
        library: the `--library` argument, or `None` to pass none at all.
        extra: further arguments after `mcp` — a bad flag, for instance.
        expect_responses: how many response lines to wait for. Defaults to the number of frames
            carrying an `id`; pass `0` for an invocation expected to fail before it serves.
    """
    wanted = (
        sum(1 for frame in frames if "id" in frame)
        if expect_responses is None
        else (expect_responses)
    )
    process = subprocess.Popen(
        spawn_arguments(library, *extra),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        cwd=REPO_ROOT,
    )
    assert process.stdin is not None and process.stdout is not None
    watchdog = threading.Timer(SPAWN_TIMEOUT_SECONDS, process.kill)
    watchdog.start()
    lines: list[str] = []
    try:
        for frame in frames:
            process.stdin.write(json.dumps(frame) + "\n")
        process.stdin.flush()
        for _ in range(wanted):
            line = process.stdout.readline()
            if not line:
                break
            lines.append(line)
        remaining_out, stderr = process.communicate()
    finally:
        watchdog.cancel()
        if process.poll() is None:  # pragma: no cover - only when the watchdog did not fire
            process.kill()
            process.wait()

    stdout = "".join(lines) + remaining_out
    responses = _parse_leniently(stdout)
    return Conversation(
        stdout=stdout, stderr=stderr, exit_code=process.returncode, responses=responses
    )


def _parse_leniently(stdout: str) -> list[dict[str, Any]]:
    """The JSON-RPC frames on stdout, **skipping any line that is not one**.

    Deliberately tolerant, and that is the whole point. Whether stdout is pure is a question for
    `tests/mcp/test_stdout_purity.py`, which asserts it line by line. If this shared helper raised
    on a stray line instead, a single stray byte would take down every test in the suite at once —
    including the positive controls whose job is to stay green while the purity test fails, which
    is exactly how a mutation check stops being able to tell you anything.
    """
    frames: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            frames.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return frames


def handshake_frames() -> Iterator[dict[str, Any]]:
    """The two frames every conversation opens with."""
    yield {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "harness-library-tests", "version": "0"},
        },
    }
    yield {"jsonrpc": "2.0", "method": "notifications/initialized"}


def with_client[T](library: Path, work: Callable[[ClientSession], Awaitable[T]]) -> T:
    """Run `work` against a real MCP client session connected to a real `hl mcp` subprocess.

    Synchronous on the outside deliberately: the project has no async test plugin and needs none —
    the only async thing about this server is its transport, so one `asyncio.run` at the edge keeps
    every test a plain function.
    """
    arguments = spawn_arguments(library)

    async def run() -> T:
        parameters = StdioServerParameters(command=arguments[0], args=arguments[1:], cwd=REPO_ROOT)
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            return await work(session)

    return asyncio.run(asyncio.wait_for(run(), SPAWN_TIMEOUT_SECONDS))
