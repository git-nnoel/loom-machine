"""Charter §13 and ruling R104 — the one object that reads the environment, and `$EDITOR`.

`$HL_LIBRARY`'s half of this is proven in `test_composition.py`, which walks contract C-8's
precedence. What T-22 adds is the variable that is **not** in this tool's namespace: `$EDITOR`
belongs to the user's shell and every other editor-launching program on the machine already
reads it, so an `HL_EDITOR` nobody sets would open a different editor from `git commit`.

**No test in this module — or anywhere in this suite — spawns an editor.** T-21 made the runner
an injected parameter for that reason, and the one thing left to prove at this layer is the
translation: a seam whose `OSError` becomes ruling R102's code rather than a traceback.
"""

from __future__ import annotations

import pytest

from harness_library.cli.composition import ReportingConflictEditor
from harness_library.cli.settings import Settings, editor_command
from harness_library.domain.errors import EditorFailedError, ErrorCode
from harness_library.domain.resolution import ConflictVersions


def test_the_editor_comes_from_editor_and_not_from_the_hl_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `validation_alias` is what takes this one field outside the `HL_` prefix.

    Asserted in **both** directions, because an alias that silently stopped working would make
    `$EDITOR` read as unset and an `HL_EDITOR` that quietly started working would open something
    the user never configured.
    """
    monkeypatch.setenv("EDITOR", "vim -d")
    monkeypatch.setenv("HL_EDITOR", "something-else")

    assert Settings().editor == "vim -d"


def test_the_editor_is_split_into_an_argument_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling R104: a real `$EDITOR` is routinely `code --wait`, and it is split **here**.

    Splitting it in `infrastructure/editor.py` would put a second, worse shell inside the one
    class in this project that spawns a process; splitting it at the call site would put three
    of them there. Quoting is honoured, because a path with a space in it is one argument.
    """
    monkeypatch.setenv("EDITOR", "'/opt/my editor/bin/ed' --wait -f")

    assert editor_command(Settings()) == ("/opt/my editor/bin/ed", "--wait", "-f")


def test_an_unset_editor_is_refused_with_its_own_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """`EDITOR_FAILED`, and **before anything is materialised**: nothing to clean up."""
    monkeypatch.delenv("EDITOR", raising=False)

    with pytest.raises(EditorFailedError) as raised:
        editor_command(Settings())

    assert raised.value.code is ErrorCode.EDITOR_FAILED
    assert raised.value.command is None


def test_a_blank_editor_is_refused_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """`EDITOR=" "` is a variable somebody set to nothing, which is not a command.

    The positive control for the test above: without it, "unset" and "set to whitespace" would
    be one case and an implementation that only checked `is None` would pass.
    """
    monkeypatch.setenv("EDITOR", "   ")

    with pytest.raises(EditorFailedError):
        editor_command(Settings())


def test_an_unparseable_editor_is_refused_naming_what_was_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unbalanced quote. The user sees what they set, which is the whole diagnosis."""
    monkeypatch.setenv("EDITOR", "'unbalanced --wait")

    with pytest.raises(EditorFailedError) as raised:
        editor_command(Settings())

    assert raised.value.command == "'unbalanced --wait"


class _Exploding:
    """A `ConflictEditor` whose `compare` fails the way a real one does. Never spawns anything."""

    def compare(self, versions: tuple[ConflictVersions, ...]) -> None:
        raise OSError(2, "No such file or directory")


class _Recording:
    """A `ConflictEditor` that keeps what it was handed. The positive control below."""

    def __init__(self) -> None:
        self.seen: tuple[ConflictVersions, ...] = ()

    def compare(self, versions: tuple[ConflictVersions, ...]) -> None:
        self.seen = versions


def test_the_editors_oserror_becomes_r102s_code() -> None:
    """**The translation T-21 could not make**, because C-6 had no code for it and charter §9
    forbids inventing one at a raise site. R102 closed that and this is the line that does it.

    Wrapped around the seam rather than around `compare_versions`, deliberately: that call also
    reaches the library repository, whose `read_bytes` raises a bare `OSError` for a permission
    fault that has nothing to do with an editor, and a wider translation would send the user to
    their shell configuration for a file they cannot read.
    """
    editor = ReportingConflictEditor(_Exploding(), command=("code", "--wait"))

    with pytest.raises(EditorFailedError) as raised:
        editor.compare((ConflictVersions(path="skills/x/SKILL.md", library=b"a", target=b"b"),))

    assert raised.value.code is ErrorCode.EDITOR_FAILED
    assert raised.value.command == "code --wait"


def test_a_working_editor_is_passed_through_untouched() -> None:
    """The positive control: the wrapper adds a translation and nothing else.

    Without it, an implementation that raised `EditorFailedError` unconditionally would pass the
    test above and break every comparison that was going to work.
    """
    inner = _Recording()
    versions = (ConflictVersions(path="skills/x/SKILL.md", library=b"a", target=b"b"),)

    ReportingConflictEditor(inner, command=("code",)).compare(versions)

    assert inner.seen == versions
