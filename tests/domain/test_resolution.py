"""`Resolution`, `ConflictVersions` and the `ConflictEditor` seam — T-21's domain vocabulary.

Pure, zero I/O. What this suite **cannot** prove is stated once, here: that any real editor is
ever launched, that two versions reach two real files, or that an argument vector is one an editor
would accept. Those are `tests/infrastructure/test_editor.py`'s, and even there **no process is
started** — the runner is a parameter, because a test that spawns `$EDITOR` hangs CI on a buffer
nobody will ever close.
"""

from __future__ import annotations

import pytest

from loom.domain.resolution import ConflictEditor, ConflictVersions, Resolution

LIBRARY_BYTES = b"# the library has moved on\n"
EDITED_BYTES = b"# and then the user edited it\n"
REFUSED_PATH = "skills/delivery-lead/SKILL.md"


class FakeEditor:
    """The full surface. One member, as the protocol has one."""

    def __init__(self) -> None:
        self.calls: list[tuple[ConflictVersions, ...]] = []

    def compare(self, versions: tuple[ConflictVersions, ...]) -> None:
        self.calls.append(versions)


class SilentEditor:
    """The surface the protocol refuses: something that looks like an editor and shows nothing.

    Named because it is the plausible mistake — a seam whose member was spelled `show` or `open`
    would satisfy nothing `compare_versions` calls, and a structural protocol says so only if
    something is asserted against it.
    """

    def open(self, versions: tuple[ConflictVersions, ...]) -> None:
        """Not `compare`."""


# -------------------------------------------------------------------------------------------
# Resolution — the two sides, and why there is no third
# -------------------------------------------------------------------------------------------


def test_a_resolution_names_one_of_exactly_two_sides() -> None:
    """**Ruling R54 as a closed set.** Choose-a-side per artifact, and the only two sides that
    exist are the library's version and the target's.

    `$EDITOR` is deliberately not a member: it shows both and decides nothing, so the decision a
    user reaches through it is still spelled as one of these two. A third member would make
    every `if resolution is ...` in the write path silently non-total.
    """
    assert [member.value for member in Resolution] == ["library", "target"]


def test_a_resolution_is_its_own_string() -> None:
    """A `StrEnum`, for the reason `Verdict` is one: T-22 parses a flag into it and the write
    path branches on it, so a rename fails at the branch rather than passing as a token nothing
    handles.

    Bound to `str` first because `mypy --strict` reads a bare `Resolution.LIBRARY == "library"`
    as a comparison between two non-overlapping literal types and rejects it — the same trap
    L45 records for a pair of asserts, met here from the other side.
    """
    library: str = Resolution.LIBRARY
    target: str = Resolution.TARGET

    assert library == "library"
    assert target == "target"


# -------------------------------------------------------------------------------------------
# ConflictVersions — three target states, not two (ruling R72)
# -------------------------------------------------------------------------------------------


def test_both_versions_of_a_path_are_carried_together() -> None:
    versions = ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES, target=EDITED_BYTES)

    assert versions.library == LIBRARY_BYTES
    assert versions.target == EDITED_BYTES
    assert versions.unreadable is None


def test_a_side_the_library_does_not_hold_is_absent_rather_than_empty() -> None:
    """`None` and never `b""`. An empty version says *this file is empty*, which is a different
    and confidently wrong answer from *this side does not have this file* — and the second is a
    real conflict shape: the library dropped a path the target still holds."""
    versions = ConflictVersions(path=REFUSED_PATH, target=EDITED_BYTES)

    assert versions.library is None
    assert versions.target == EDITED_BYTES


def test_a_target_side_that_could_not_be_read_carries_the_reason_and_no_bytes() -> None:
    """**Ruling R72's three states, at the type that has to carry them.**

    A symlink means the target *holds* the path and its content was never read. Showing that as
    an absence would tell a user there is nothing there, when in fact there is something there
    that R6 will not read through — and those call for two different decisions.
    """
    versions = ConflictVersions(
        path=REFUSED_PATH,
        library=LIBRARY_BYTES,
        unreadable="the target holds a symlink here",
    )

    assert versions.target is None
    assert versions.unreadable == "the target holds a symlink here"


def test_a_reason_may_not_sit_beside_real_target_content() -> None:
    """The one invariant, and the one direction it runs: a reason the content is missing, beside
    the content, says the opposite of what is true."""
    with pytest.raises(ValueError, match="could not be read"):
        ConflictVersions(
            path=REFUSED_PATH,
            target=EDITED_BYTES,
            unreadable="the target holds a symlink here",
        )


def test_an_absent_target_side_needs_no_reason() -> None:
    """**The converse is deliberately not enforced**, and this pins the choice so nobody
    tightens it by accident.

    A path the target simply does not hold owes no explanation beyond its own absence, and
    requiring one would mean every ordinary "the user deleted it" shape had to invent a sentence
    — which the four conflict reasons in `install_plan.py` already own.
    """
    versions = ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES)

    assert versions.target is None
    assert versions.unreadable is None


def test_a_comparison_has_a_path() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ConflictVersions(path="", library=LIBRARY_BYTES)


# -------------------------------------------------------------------------------------------
# ConflictEditor — the seam
# -------------------------------------------------------------------------------------------


def test_a_full_editor_satisfies_the_protocol() -> None:
    assert isinstance(FakeEditor(), ConflictEditor)


def test_something_that_shows_nothing_does_not_satisfy_it() -> None:
    """Positive control for the assertion above: without it, a protocol that accepted anything
    would make the previous test pass having checked nothing."""
    assert not isinstance(SilentEditor(), ConflictEditor)


def test_an_editor_is_shown_a_whole_artifacts_paths_at_once() -> None:
    """One session per artifact, not one per path. An artifact's refused paths are one decision,
    and a user answering it one editor invocation at a time would be answering a question this
    tool never asked."""
    editor: ConflictEditor = FakeEditor()
    shown = (
        ConflictVersions(path=REFUSED_PATH, library=LIBRARY_BYTES, target=EDITED_BYTES),
        ConflictVersions(path="skills/delivery-lead/references/notes.md", library=LIBRARY_BYTES),
    )

    editor.compare(shown)

    assert isinstance(editor, FakeEditor)
    assert editor.calls == [shown]
