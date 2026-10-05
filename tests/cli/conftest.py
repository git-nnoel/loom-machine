"""Shared scaffolding for the CLI suite.

Charter §10 tests adapters through Typer's own runner, so every test here goes through argument
parsing, the callback, the composition root and the exit status — the parts that only exist at this
layer. Nothing is asserted about a rule firing or an order being right: those were decided and
proven below, and re-asserting them here would produce a second suite that fails for reasons that
have nothing to do with the CLI.

**Assertions are against the JSON payload, never against the human format** (ruling R7). The
columnar output is presentation and may be re-tasted at any time; a test that pinned a substring of
it would break on a cosmetic change and would be claiming a guarantee the project has not made.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import pytest
import typer.rich_utils
from typer.testing import CliRunner, Result

from loom.cli.main import app

FIXTURE_LIBRARY = Path(__file__).resolve().parent.parent / "fixtures" / "library"
"""The committed fixture library — lesson L6: `~/.claude/` is a target layout, not a library."""

HELP_WIDTH = 80
"""The width every rendered screen in this suite is laid out at. See `pinned_terminal_width`."""


@pytest.fixture(autouse=True)
def no_ambient_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove `$LOOM_LIBRARY` from every test that does not set it deliberately.

    Autouse and not optional: contract C-8's precedence is the thing this suite proves, and a
    developer with `LOOM_LIBRARY` exported in their shell would otherwise get a different answer
    from the same test than CI does — the precedence tests would pass locally for the wrong
    reason.
    """
    monkeypatch.delenv("LOOM_LIBRARY", raising=False)


@pytest.fixture(autouse=True)
def pinned_terminal_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay every rendered screen out at `HELP_WIDTH`, instead of inheriting a terminal (R117).

    `typer.rich_utils.MAX_WIDTH` is the global `_get_rich_console` reads, and it is read from
    `$TERMINAL_WIDTH` once at import — so this is the seam, and an environment variable would be
    both too late and ambient. `setattr` rather than a default means a Typer that renamed the
    global fails this fixture loudly instead of silently going back to inheriting one.

    Pinned at **80**, which is Rich's own fallback for a stream that is not a terminal, so nothing
    re-renders today; what changes is that a developer whose `$COLUMNS` says otherwise now gets
    the same layout CI does. Deliberately **not** widened until nothing wraps: a wrap is the
    normal case for an option's help, and a pin chosen to make wrapping disappear would leave
    `flattened` — the thing that actually makes these assertions honest — unexercised.
    """
    monkeypatch.setattr(typer.rich_utils, "MAX_WIDTH", HELP_WIDTH)


@pytest.fixture
def fixture_library() -> Path:
    """The committed fixture library's root."""
    assert FIXTURE_LIBRARY.is_dir(), (
        f"the committed fixture library is missing from {FIXTURE_LIBRARY}. Charter §10: it is the "
        "regression suite for the reason this product exists and is never deleted."
    )
    return FIXTURE_LIBRARY


class Invoke(Protocol):
    """Calling convention of the `loom` fixture: bare arguments, one `Result` back."""

    def __call__(self, *arguments: str) -> Result: ...


@pytest.fixture
def runner() -> CliRunner:
    """Typer's runner. Click 8.5 keeps stdout and stderr apart, which charter §11 depends on."""
    return CliRunner()


@pytest.fixture
def loom_cli(runner: CliRunner, fixture_library: Path) -> Iterator[Invoke]:
    """Invoke `loom` against the committed fixture library."""

    def invoke(*arguments: str) -> Result:
        return runner.invoke(app, ["--library", str(fixture_library), *arguments])

    yield invoke


def payload_of(result: Result) -> dict[str, Any]:
    """The `--json` payload, parsed. Fails loudly when the command did not succeed.

    Parsing rather than substring-matching is what makes ruling R7 real: the assertion is about the
    contract Pydantic emitted, not about text that happens to appear near it.
    """
    assert result.exit_code == 0, f"exit {result.exit_code}; stderr: {result.stderr}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def error_of(result: Result) -> dict[str, Any]:
    """The `--json` error envelope from stderr, parsed."""
    envelope: dict[str, Any] = json.loads(result.stderr)
    error: dict[str, Any] = envelope["error"]
    return error


def write(path: Path, text: str) -> Path:
    """Write a text file, creating its parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_skill(library_root: Path, name: str, *, body: str = "Prose.") -> Path:
    """A valid skill under `library_root`, so a test perturbs exactly one thing."""
    root = library_root / "skills" / name
    write(root / "SKILL.md", f"---\nname: {name}\ndescription: what {name} does\n---\n\n{body}\n")
    return root
