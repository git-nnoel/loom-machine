"""`SubprocessConflictEditor` — `$EDITOR` over two versions, against real files. T-21, R54.

**No test in this module starts a process, and none ever may.** The runner is a constructor
parameter with a real default, and every test here passes a recorder instead: a test that launched
`$EDITOR` would hang CI on a buffer nobody closes, and it would do it on a machine whose `$EDITOR`
nobody controls. What is real is everything else — a real workspace under `tmp_path`, real files,
real bytes — which is the whole reason this module exists beside the fake in
`tests/application/test_resolve.py`.

Nothing is written to `~/.claude/`, and nothing outside `tmp_path`.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path

import pytest

from harness_library.domain.resolution import ConflictEditor, ConflictVersions
from harness_library.infrastructure.editor import (
    LIBRARY_DIRECTORY,
    TARGET_DIRECTORY,
    SubprocessConflictEditor,
    run_editor,
)

REFUSED_PATH = "skills/delivery-lead/SKILL.md"
NESTED_PATH = "skills/delivery-lead/references/notes.md"

LIBRARY_BYTES = b"# the library has moved on\n"
EDITED_BYTES = b"# and then the user edited it\n"
BINARY_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
"""Every byte value plus a bare `\\r\\n`. A version that went through `str` would not come back."""

COMMAND = ("vim", "-d")
"""A plausible split `$EDITOR`. Never run — see the module docstring."""


class Recorder:
    """The injected runner. Keeps the argument vector and starts nothing."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> None:
        self.calls.append(list(argv))

    @property
    def argv(self) -> list[str]:
        """The last vector, or an empty one when nothing was run."""
        return self.calls[-1] if self.calls else []


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Where the versions are materialised. Supplied, never invented by the class.

    A constructor parameter rather than a `mkdtemp` inside `compare`, so the composition root
    owns where a user's content is written and this suite can look at what was written.
    """
    return tmp_path / "conflict"


def an_editor(workspace: Path, runner: Recorder) -> SubprocessConflictEditor:
    return SubprocessConflictEditor(COMMAND, workspace=workspace, run=runner)


# -------------------------------------------------------------------------------------------
# What reaches the disk, and what reaches the command line
# -------------------------------------------------------------------------------------------


def test_both_versions_are_written_at_their_real_relative_paths(workspace: Path) -> None:
    """One directory per side, and the path kept whole inside it.

    The extension survives, so the editor picks the right syntax highlighting; the basename
    survives, so a split window is legible; and the two sides of one path cannot collide, which
    a flat directory of basenames could not promise.
    """
    runner = Recorder()

    an_editor(workspace, runner).compare(
        (ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES, target=EDITED_BYTES),)
    )

    assert (workspace / LIBRARY_DIRECTORY / REFUSED_PATH).read_bytes() == LIBRARY_BYTES
    assert (workspace / TARGET_DIRECTORY / REFUSED_PATH).read_bytes() == EDITED_BYTES


def test_the_command_is_run_once_with_every_file_appended(workspace: Path) -> None:
    """One session for the whole artifact, as the protocol requires — an artifact's refused paths
    are one decision, and a user answering it one editor invocation at a time would be answering
    a question this tool never asked.

    The command is a **vector** and not a string, because a real `$EDITOR` is routinely
    `code --wait` or `vim -d` and splitting one here would be a second, worse shell.
    """
    runner = Recorder()

    an_editor(workspace, runner).compare(
        (
            ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES, target=EDITED_BYTES),
            ConflictVersions(path=NESTED_PATH, library=LIBRARY_BYTES),
        )
    )

    assert len(runner.calls) == 1
    assert runner.argv[:2] == ["vim", "-d"]
    assert runner.argv[2:] == [
        str(workspace / LIBRARY_DIRECTORY / REFUSED_PATH),
        str(workspace / TARGET_DIRECTORY / REFUSED_PATH),
        str(workspace / LIBRARY_DIRECTORY / NESTED_PATH),
    ]


def test_a_missing_side_contributes_no_file_at_all(workspace: Path) -> None:
    """Not an empty file. An empty pane says *this version is empty*, which is a different and
    confidently wrong answer from *this version does not exist* — and the second is a real
    conflict shape (the library dropped a path the target still holds).

    The control is in the same test: the side that *is* present really was written, so "no file"
    is a fact about the absent side rather than about a materialiser that wrote nothing.
    """
    runner = Recorder()

    an_editor(workspace, runner).compare(
        (ConflictVersions(path=REFUSED_PATH, target=EDITED_BYTES),)
    )

    assert not (workspace / LIBRARY_DIRECTORY / REFUSED_PATH).exists()
    assert (workspace / TARGET_DIRECTORY / REFUSED_PATH).read_bytes() == EDITED_BYTES
    assert runner.argv[2:] == [str(workspace / TARGET_DIRECTORY / REFUSED_PATH)]


def test_an_unreadable_target_side_reaches_the_editor_as_one_pane(workspace: Path) -> None:
    """**Ruling R72 at the adapter.** A symlink means the target holds the path and its content
    was never read, so there is nothing to materialise for that side — the library's version is
    still worth seeing, and the reason is in the report the caller renders."""
    runner = Recorder()

    an_editor(workspace, runner).compare(
        (
            ConflictVersions(
                path=REFUSED_PATH,
                library=LIBRARY_BYTES,
                unreadable="the target holds a symlink here",
            ),
        )
    )

    assert not (workspace / TARGET_DIRECTORY / REFUSED_PATH).exists()
    assert runner.argv[2:] == [str(workspace / LIBRARY_DIRECTORY / REFUSED_PATH)]


def test_a_binary_version_survives_being_materialised(workspace: Path) -> None:
    """Bytes and never text. A refused path can hold anything — charter §7 keeps binary content
    readable without decoding it — and what an editor makes of the buffer is the editor's
    business and the user's."""
    runner = Recorder()

    an_editor(workspace, runner).compare(
        (ConflictVersions(path="skills/messy/references/diagram.png", library=BINARY_BYTES),)
    )

    written = workspace / LIBRARY_DIRECTORY / "skills/messy/references/diagram.png"
    assert written.read_bytes() == BINARY_BYTES


def test_nothing_is_run_when_there_is_nothing_to_show(workspace: Path) -> None:
    """An empty session launches nothing. Opening an editor on no files would leave a user
    staring at a blank buffer wondering what this tool thought it was asking.

    The control is every test above: the runner really is called when there is something to
    show, so "not called" is not a recorder that never works.
    """
    runner = Recorder()

    an_editor(workspace, runner).compare(())

    assert runner.calls == []
    assert not workspace.exists()


def test_the_workspace_is_created_on_demand(workspace: Path) -> None:
    """The composition root names the directory; this class makes it. A constructor that created
    it eagerly would leave an empty directory behind for every run that showed nothing."""
    assert not workspace.exists()
    runner = Recorder()

    an_editor(workspace, runner).compare(
        (ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES),)
    )

    assert workspace.is_dir()


# -------------------------------------------------------------------------------------------
# The refusals
# -------------------------------------------------------------------------------------------


def test_an_editor_with_no_command_is_refused(workspace: Path) -> None:
    """An editor seam with no editor would write both versions out and then quietly do nothing,
    which looks exactly like a user who decided not to resolve anything — the silent-no-op this
    product exists to eliminate."""
    with pytest.raises(ValueError, match="needs a command to run"):
        SubprocessConflictEditor((), workspace=workspace)


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.md", "skills/../../outside.md", "."])
def test_a_version_may_not_be_written_outside_the_workspace(workspace: Path, path: str) -> None:
    """These paths come from a plan and so cannot be any of these shapes. Re-checked anyway,
    because this is the one class in the project that writes a user's content into a directory
    chosen by somebody else, and the guarantee is worth having as a property of the string."""
    runner = Recorder()

    with pytest.raises(ValueError, match="not a path a conflict version"):
        an_editor(workspace, runner).compare((ConflictVersions(path=path, library=LIBRARY_BYTES),))

    assert runner.calls == []


def test_a_failing_runner_surfaces_as_a_builtin(workspace: Path) -> None:
    """Ruling R24's posture: `application/` is where a failed syscall becomes one of this
    project's codes, so this layer raises the builtin and translates nothing. C-6 has no code for
    "the editor would not start" and charter §9 forbids inventing one here."""

    def refuse(argv: Sequence[str]) -> None:
        raise OSError("no such command")

    editor = SubprocessConflictEditor(COMMAND, workspace=workspace, run=refuse)

    with pytest.raises(OSError, match="no such command"):
        editor.compare((ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES),))


# -------------------------------------------------------------------------------------------
# The seam itself
# -------------------------------------------------------------------------------------------


def test_the_adapter_satisfies_the_protocol(workspace: Path) -> None:
    """Structurally, like every other implementation in this layer (R14): the class does not
    inherit `ConflictEditor`, so `domain/` keeps knowing nothing about who implements it."""
    assert isinstance(an_editor(workspace, Recorder()), ConflictEditor)


def test_the_default_runner_is_the_one_that_really_spawns() -> None:
    """The default is `run_editor`, which calls `subprocess.run`. Asserted on the **signature**
    and never by calling it: naming the seam's default is what makes "no test in this project
    starts an editor" a property of the module rather than a hope, and reading it off the
    signature keeps the assertion from being the one place that launches one."""
    default = inspect.signature(SubprocessConflictEditor.__init__).parameters["run"].default

    assert default is run_editor
