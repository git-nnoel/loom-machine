"""Ruling R3 and charter §11 — no log record reaches stdout, in any process, at any level.

**This is the configuration T-8 inherits**, and `loom mcp` dies on a single stdout byte because
stdout is the JSON-RPC transport. The guarantee is therefore proven here rather than asserted in a
docstring, and it is proven with a positive control: an absence test whose subject never emitted
anything is a test that passes for the wrong reason.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from loom.cli.logging import configure_logging, get_logger
from loom.cli.main import app


def _emit_every_level() -> None:
    logger = get_logger("test")
    logger.debug("a debug record")
    logger.info("an info record")
    logger.warning("a warning record")
    logger.error("an error record")


def test_no_log_record_reaches_stdout_at_any_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The absence half. Every level, because a handler misconfigured for one is misconfigured."""
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    configure_logging(verbose=True)
    _emit_every_level()

    assert out.getvalue() == ""


def test_the_records_do_reach_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """**The positive control** (charter §10). Without it, the test above would pass just as well
    against a logger that was silently dropping everything, which would prove nothing about
    stdout and would hide the loss of every diagnostic the tool emits."""
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    configure_logging(verbose=True)
    _emit_every_level()

    written = err.getvalue()
    assert "a debug record" in written
    assert "an info record" in written
    assert "a warning record" in written
    assert "an error record" in written


def test_a_command_that_logs_leaves_stdout_carrying_only_its_payload(
    runner: CliRunner, fixture_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the real callback: `--verbose` turns logging up as far as it goes, and
    stdout still parses as exactly one JSON document."""
    import json

    result = runner.invoke(app, ["--verbose", "--library", str(fixture_library), "list", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["total"] > 0


def test_a_failing_command_writes_nothing_at_all_to_stdout(
    runner: CliRunner, fixture_library: Path
) -> None:
    """The failure path matters as much: a diagnosis on stdout would corrupt a JSON-RPC stream
    just as effectively as a log line, and would break `loom list --json | jq` for a missing id."""
    result = runner.invoke(
        app, ["--library", str(fixture_library), "show", "skill/does-not-exist", "--json"]
    )

    assert result.exit_code != 0
    assert result.stdout == ""
    assert result.stderr != ""
