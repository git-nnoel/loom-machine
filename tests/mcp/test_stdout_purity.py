"""Charter §11 — **nothing but JSON-RPC frames ever reaches stdout in the `loom mcp` process.**

This is the acceptance criterion the whole task lives or dies by, and it is asserted about *bytes*
on a real pipe from a real process, because that is the only level at which the guarantee means
anything. A single stray byte kills the client connection and surfaces as a malformed stream with
no diagnosable cause — the failure has no signature, so it must be impossible rather than rare.

**Every absence assertion here is paired with a positive control** (charter §10). "stdout was
empty" is worthless on its own: a process that died before it opened its mouth satisfies it. Each
test therefore also proves that the process *did* speak — on stderr, where diagnoses belong.

The rule is "nothing on **stdout**", not "no output at all". A change that silenced logging would
satisfy the first assertion while destroying every diagnostic the server has, and
`test_the_server_still_reports_its_tool_calls_on_stderr` exists to fail on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.mcp.conftest import handshake_frames, speak
from tests.rendering import without_ansi

TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
GET_REFERENCE = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "get_reference",
        "arguments": {"artifact_id": "skill/delivery-lead", "path": "references/checklist.md"},
    },
}


def _as_json(line: str) -> dict[str, Any] | None:
    """One stdout line as a JSON object, or `None` when it is not one.

    Parsed rather than asserted so that a stray line fails on a **named assertion** that says what
    was wrong, instead of on a decoder traceback the reader has to interpret."""
    try:
        parsed: Any = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def test_every_byte_on_stdout_is_a_json_rpc_frame(fixture_library: Path) -> None:
    """The absence half, stated as a property of every line rather than of the whole stream.

    A stray line anywhere — a log record, a warning, a `print` in the entry path before the
    transport claims the descriptor — fails this, because a JSON-RPC stream is one frame per line
    and every line must parse as one."""
    conversation = speak([*handshake_frames(), TOOLS_LIST, GET_REFERENCE], library=fixture_library)

    lines = conversation.stdout.splitlines()
    assert lines, "the server wrote nothing at all; there is no purity to speak of"
    for line in lines:
        frame = _as_json(line)
        assert frame is not None, f"a line on stdout that is not JSON at all: {line!r}"
        assert frame.get("jsonrpc") == "2.0", f"not a JSON-RPC frame on stdout: {line!r}"
        assert "id" in frame or "method" in frame, (
            f"a JSON-RPC frame with no id or method: {line!r}"
        )


def test_the_server_still_reports_its_tool_calls_on_stderr(fixture_library: Path) -> None:
    """**The positive control for the whole file**, and ruling R3's one line per tool call.

    Without this, every purity assertion here would be satisfied by a server that had been made
    mute. This one fails on that fix, so the two together say what charter §11 actually says:
    diagnostics exist, and they are on the other stream."""
    conversation = speak([*handshake_frames(), TOOLS_LIST, GET_REFERENCE], library=fixture_library)

    assert "mcp.tool_call" in conversation.stderr
    assert "get_reference" in conversation.stderr
    assert conversation.stderr.count("mcp.tool_call") == 1, "ruling R3: one line per tool call"


def test_the_answers_still_arrive_while_stdout_stays_pure(fixture_library: Path) -> None:
    """The other positive control: purity that came at the cost of the answers is not purity.

    A server writing nothing to stdout would pass the absence test perfectly and be useless."""
    conversation = speak([*handshake_frames(), TOOLS_LIST, GET_REFERENCE], library=fixture_library)

    assert conversation.result(1)["protocolVersion"]
    assert len(conversation.result(2)["tools"]) == 4
    assert conversation.result(3)["content"][0]["text"]


def test_an_invalid_flag_writes_nothing_to_stdout(fixture_library: Path) -> None:
    """Feature F-6, and lesson L7 — Typer's own usage error must not reach the transport.

    `loom mcp --nope` never gets as far as serving, so the SDK's fd-1 diversion is not protecting
    anything here: this is charter §11 holding on its own, in the window before the transport
    exists. The positive control is on stderr, where the complaint belongs.

    **The control reads stderr as text, and that is not incidental** (R117). Typer's option
    highlighter styles the leading hyphen of a flag as a span of its own, so the raw stream holds
    `ESC[1;36m-ESC[0mESC[1;36m-nopeESC[0m` and the literal `--nope` is nowhere in it. The control
    once matched the raw bytes and rotted the day Rich decided it had a terminal — the guarantee
    never moved, only the styling around it. What is claimed here is that the complaint *names
    the flag*; the colour it names it in is decoration (L61)."""
    conversation = speak([], library=fixture_library, extra=["--nope"], expect_responses=0)

    assert conversation.stdout == ""
    assert conversation.exit_code != 0
    assert "--nope" in without_ansi(conversation.stderr)


def test_a_non_library_root_writes_nothing_to_stdout(tmp_path: Path) -> None:
    """Charter §13's loud failure, on the one stream where loudness is fatal.

    Ruling R29 gave this condition a code, so the diagnosis now names `NOT_A_LIBRARY` — and it
    still goes to stderr, in full, while stdout stays untouched."""
    not_a_library = tmp_path / "just-a-directory"
    not_a_library.mkdir()

    conversation = speak([], library=not_a_library, expect_responses=0)

    assert conversation.stdout == ""
    assert conversation.exit_code != 0
    assert "not a harness library" in conversation.stderr
    assert "NOT_A_LIBRARY" in conversation.stderr


def test_a_malformed_frame_does_not_provoke_a_stray_byte(fixture_library: Path) -> None:
    """The client's mistakes are answered on the wire, in the protocol's own vocabulary.

    A server that printed a traceback on bad input would corrupt the very stream it was trying to
    complain about."""
    conversation = speak(
        [*handshake_frames(), {"jsonrpc": "2.0", "id": 2, "method": "no/such/method"}],
        library=fixture_library,
    )

    for line in conversation.stdout.splitlines():
        frame = _as_json(line)
        assert frame is not None and frame["jsonrpc"] == "2.0", f"stray output: {line!r}"
    assert "error" in conversation.response(2)
