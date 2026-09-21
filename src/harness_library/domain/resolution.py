"""`--resolve` — which side of a refused path the user chose, and the seam that shows them both.

**This module is the other half of every refusal in initiative 02.** Apply leaves a `LOCAL_EDIT`
or a `CONFLICT` untouched and comes back `INCOMPLETE = 6` (R48, R57), which is the right posture
and is only half a tool: a user who is told "you must decide" and given no way to act on the
decision has been handed a worse product, not a safer one. Ruling **R54** is the other half, and
it is deliberately small — choose a side per artifact, or look at both versions. **No merge**, not
here and not later: the plan's Deferred section says never.

## The three ways, and why the third is not a `Resolution`

`Resolution` names a **side**: the library's version, or the target's. That is the whole of what
can be chosen, because those are the only two versions that exist. `$EDITOR` is not a third side —
it shows both and decides nothing, and the decision the user reaches is then spelled as one of
these two. So the enum has two members and `application/write/resolve.py` has two functions, and
the flag with three spellings is T-22's to map onto them.

## The editor is a seam, for the reason every other I/O in this project is

`ConflictEditor` is a protocol in `domain/` satisfied structurally, exactly as C-4, C-12, C-13,
C-15 and C-16 are (ruling R14). The alternative — a use case that reached for `subprocess` — would
make every test of `--resolve` launch a process, and a test that launches `$EDITOR` is a test that
hangs CI with a vi buffer nobody will ever close. This layer performs no I/O and
`tests/domain/test_purity.py` bars `os`, `io`, `subprocess` and `tempfile` from it.

## Absent is not unreadable (R72)

`ConflictVersions` carries two versions and, separately, a reason the target side could not be
fetched. Those are three states and not two, because `PlanEntry.target_sha` has three (R72): a
digest, `None` for *the target does not hold this path*, and `UNHASHED_TARGET_SHA` for *the target
holds it and its content was never read* — a symlink, which ruling R6 never follows. A comparison
that collapsed the last two into "no bytes" would show a user an empty pane where the honest
answer is "there is something here and I will not read through it".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Resolution(StrEnum):
    """Which version of a refused path the user chose. Closed, two members. Ruling R54.

    A `StrEnum` rather than a bare string for the reason `Verdict` is one: T-22 parses a flag into
    it and `resolve_conflict` branches on it, so a rename fails at the branch instead of passing
    silently as a token nothing handles.
    """

    LIBRARY = "library"
    """Take the library's version: write it into the target, and record it as installed.

    The one operation in this initiative that deliberately overwrites an edit of the user's, which
    is why it takes a backup (R88) and why it is per artifact and never per run.
    """

    TARGET = "target"
    """Keep what is on the target's disk, and **repair the record to match**.

    Nothing is written. What changes is the manifest: after this, the path holds what this tool
    considers installed, so it stops being refused. It is the one operation here that can make the
    tool claim a file it did not put there — which is exactly what the user is asking for, and
    exactly why it must do that and nothing more.
    """


@dataclass(frozen=True, slots=True)
class ConflictVersions:
    """Both versions of one refused path, as far as they can be fetched. What `$EDITOR` is given.

    Attributes:
        path: the target-relative path being decided about. A `str`, never a `Path` (R21).
        library: the library's bytes, or `None` when the library does not hold this path — the
            conflict shape in which the library dropped a file the target still has.
        target: the target's bytes, or `None` when the target does not hold this path **or** when
            its content could not be read. `unreadable` is what tells those two apart.
        unreadable: why the target's content is missing although the target holds the path, or
            `None`. Set only for `UNHASHED_TARGET_SHA` today — a symlink, which R6 never follows
            and never reads through. Prose, never contract.

    The one invariant, and it runs one way: **`unreadable` implies no target bytes.** A reason
    beside real content would say the content is missing while handing it over. The converse is
    deliberately not enforced — a target that simply does not hold the path has no bytes and owes
    no explanation beyond its own absence.
    """

    path: str
    library: bytes | None = None
    target: bytes | None = None
    unreadable: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("ConflictVersions.path must not be empty")
        if self.unreadable is not None and self.target is not None:
            raise ValueError(
                f"{self.path!r} carries both the target's content and a reason it could not be "
                "read: the reason exists to say that a path the target holds has no bytes here "
                "(R72), and beside real content it says the opposite of what is true"
            )


@runtime_checkable
class ConflictEditor(Protocol):
    """Where a user is shown both versions of a refused path. One member, and no second.

    The seam behind `$EDITOR`. `infrastructure/editor.py` implements it by materialising each
    version as a file and launching an editor command over them; a test implements it by keeping
    what it was handed. Nothing in this project reads anything back from an editor — see the
    module docstring.

    Satisfied **structurally**, like every other protocol in `domain/` (R14).
    """

    def compare(self, versions: tuple[ConflictVersions, ...]) -> None:
        """Show every version pair at once, so one editor session covers the whole artifact.

        A tuple and not one call per path: an artifact's refused paths are one decision, and a
        user answering it one `$EDITOR` invocation at a time would be answering a question this
        tool never asked. An empty tuple is a value and means there was nothing to show.

        Raises:
            OSError: the versions could not be materialised or the editor could not be run. A
                builtin, ruling R24's posture — `application/` is where a failed syscall becomes
                one of this project's codes, and an implementation that raised one itself would
                make that translation untestable by pre-supplying its result.
        """
        ...


__all__ = ["ConflictEditor", "ConflictVersions", "Resolution"]
