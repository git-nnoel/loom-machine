"""Ruling R5 — when an artifact was last updated, and whether that answer came from git.

**This module is the reason `domain/` stays pure.** R5 derives `updated_at` from a `git log`
subprocess, and the tempting place to write that subprocess is next to the field it fills, inside
`domain/artifact.py`, where `import-linter` would not have stopped it — its `domain-is-pure`
contract polices this project's other layers and says nothing about the standard library. The second
guard, `tests/domain/test_purity.py`, names `subprocess` in its forbidden set for exactly this task.
So `subprocess` is imported here and nowhere else, and the guard is left armed rather than widened.

**R5 stated once, in code below and in prose here.** `updated_at` is the committer date of the last
commit touching the artifact's paths. It falls back to the maximum mtime of the artifact's scanned
files when the library is not a git work tree, or when the artifact has uncommitted changes, and
`is_dirty` is set on **both** of those paths — which is what `Artifact.is_dirty` already promises it
means: "`updated_at` came from the mtime fallback rather than from git".

**Two questions up front, one per artifact.** Whether this is a work tree, and which paths are
dirty, are asked once per scan rather than once per artifact; only `git log -1` runs per artifact.
A library of fifty artifacts is therefore fifty-two processes rather than a hundred and fifty. That
is still linear, and it is the accepted cost of a read-only single-user tool (charter §12); if a
library ever grows large enough to matter, the replacement is one `git log --name-only` pass, not
a cache.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

GIT_EXECUTABLE = "git"

_TIMEOUT_SECONDS = 30
"""A bound on any one git call. A hung subprocess in a read path would otherwise hang the CLI, the
MCP server and every later initiative with no diagnosable cause."""

_RENAME_STATUSES = frozenset({"R", "C"})
"""Porcelain status letters whose record carries a **second** path field — the rename or copy
source. Consumed explicitly rather than parsed as a new record."""


@dataclass(frozen=True, slots=True)
class Timestamp:
    """When an artifact was last updated, and where that answer came from.

    Attributes:
        updated_at: timezone-aware, always. `Artifact` rejects a naive value because mixing a naive
            value from the mtime path with an aware value from the git path raises inside sorting,
            far from the cause.
        is_dirty: `True` when this came from the mtime fallback rather than from git.
    """

    updated_at: datetime
    is_dirty: bool

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError("Timestamp.updated_at must be timezone-aware")


class ArtifactTimestamps(Protocol):
    """How the scanner asks for R5's answer.

    A protocol so a test can pin a scan to a fixed instant without a git repository, and so R5's
    subprocess work is provably absent from every test that is not about R5.
    """

    def for_artifact(self, root: Path, files: Sequence[Path]) -> Timestamp:
        """The timestamp for the artifact rooted at `root`, whose scanned files are `files`.

        Args:
            root: the artifact root — a directory for a `DIRECTORY`-kind artifact, and the document
                itself for a `FILE`-kind one.
            files: the absolute paths the scan took. Skipped paths are not among them.
        """
        ...


@dataclass(frozen=True, slots=True)
class FixedTimestamps:
    """Every artifact updated at one instant. For tests that are not about R5."""

    updated_at: datetime
    is_dirty: bool = False

    def for_artifact(self, root: Path, files: Sequence[Path]) -> Timestamp:
        return Timestamp(updated_at=self.updated_at, is_dirty=self.is_dirty)


class GitTimestamps:
    """R5 against a real git work tree, with the mtime fallback.

    Constructed once per scan: the two library-wide questions — is this a work tree, and what is
    dirty — are asked in `__init__`, and `for_artifact` then costs at most one `git log -1`.
    """

    def __init__(self, library_root: Path) -> None:
        self._library_root = library_root
        self._prefix = _repository_prefix(library_root)
        self._dirty_paths: frozenset[str] = (
            _dirty_paths(library_root) if self._prefix is not None else frozenset()
        )

    @property
    def in_repository(self) -> bool:
        """Whether the library root sits inside a git work tree.

        When it does not, every artifact takes the mtime path and every `is_dirty` is `True`. That
        is R5's first fallback, not a degraded mode.
        """
        return self._prefix is not None

    def for_artifact(self, root: Path, files: Sequence[Path]) -> Timestamp:
        """R5, for one artifact. See the module docstring for the rule in prose."""
        relative = self._relative_to_library(root)
        if self._prefix is None or relative is None:
            return Timestamp(_max_mtime(root, files), is_dirty=True)
        if self._is_dirty(relative):
            return Timestamp(_max_mtime(root, files), is_dirty=True)
        committed = _last_commit_date(self._library_root, relative)
        if committed is None:
            # In a work tree, tracked, and yet no commit touches it. `git status` did not call it
            # dirty either, so the honest answer is "git does not know", which is the fallback.
            return Timestamp(_max_mtime(root, files), is_dirty=True)
        return Timestamp(committed, is_dirty=False)

    def _relative_to_library(self, root: Path) -> str | None:
        """`root` as a POSIX path relative to the library root, or `None` if it is not under it."""
        try:
            return root.relative_to(self._library_root).as_posix()
        except ValueError:
            return None

    def _is_dirty(self, relative: str) -> bool:
        """Whether any uncommitted change falls on or under this artifact.

        Prefix matching on the path is what makes a change to *any* file under a `DIRECTORY`-kind
        artifact make the whole artifact dirty, which is what R5 asks for — the artifact is the
        unit, not the file.
        """
        assert self._prefix is not None
        repository_relative = f"{self._prefix}{relative}"
        if repository_relative in self._dirty_paths:
            return True
        below = f"{repository_relative}/"
        return any(path.startswith(below) for path in self._dirty_paths)


# ------------------------------------------------------------------------------------------------
# The git calls. Every one of them is best-effort: git being absent, or this not being a repository,
# is R5's documented first fallback and never an error the user has to hear about.
# ------------------------------------------------------------------------------------------------


def _repository_prefix(library_root: Path) -> str | None:
    """Where the library root sits inside its work tree, as a `""`-or-`"a/b/"` prefix.

    `None` means "not a git work tree", which includes git not being installed at all.

    The prefix exists because the two git commands answer in **different bases**: `git status
    --porcelain` reports paths relative to the *repository* root, while a pathspec is resolved
    relative to the *current directory*. Conflating the two silently reports every artifact clean in
    any library that is not itself the repository root.
    """
    result = _run(library_root, "rev-parse", "--show-prefix")
    if result is None:
        return None
    return result.strip()


def _dirty_paths(library_root: Path) -> frozenset[str]:
    """Every path with an uncommitted change at or below the library root, repository-relative.

    `-z` rather than the default format because `core.quotePath` escapes non-ASCII names into
    C-style quoted strings, and a library whose skill is named in Portuguese would then never match
    its own status line and would read as permanently clean. `-uall` so an untracked directory is
    reported as its individual files rather than collapsed to a trailing-slash entry.
    """
    output = _run(library_root, "status", "--porcelain", "-z", "-uall", "--", ".")
    if output is None:
        return frozenset()
    return frozenset(_parse_porcelain_z(output))


def _parse_porcelain_z(output: str) -> list[str]:
    """The paths in a `git status --porcelain -z` stream.

    Each record is `XY <path>`, and a rename or copy is followed by a **second** field holding the
    source path. Both halves of a rename are returned: over-reporting dirtiness is safe here, since
    the only consequence is R5 taking its documented mtime fallback, while under-reporting would
    hand back a stale commit date as if it were current.
    """
    fields = [field for field in output.split("\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4 or record[2] != " ":
            continue
        status, path = record[:2], record[3:]
        paths.append(path)
        if (status[0] in _RENAME_STATUSES or status[1] in _RENAME_STATUSES) and index < len(fields):
            paths.append(fields[index])
            index += 1
    return paths


def _last_commit_date(library_root: Path, relative: str) -> datetime | None:
    """The committer date of the last commit touching `relative`, or `None` if there is none.

    The pathspec carries `:(literal)` magic so an artifact whose name contains `*`, `?` or `[` is
    asked about as a path rather than read as a glob — which would otherwise silently answer about
    a different set of files, or about none.
    """
    output = _run(library_root, "log", "-1", "--format=%cI", "--", f":(literal){relative}")
    if not output:
        return None
    try:
        parsed = datetime.fromisoformat(output.strip())
    except ValueError:  # pragma: no cover - git's %cI is always ISO 8601
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _run(cwd: Path, *arguments: str) -> str | None:
    """One git call, or `None` when git cannot answer.

    Every failure mode collapses to `None` on purpose: git missing from the machine, the directory
    not being a work tree, and a non-zero exit are the same fact to R5 — "no commit date is
    available" — and each takes the mtime fallback. Raising instead would make a read-only listing
    fail on a plain directory of skills, which is a supported way to hold a library.
    """
    try:
        # Fixed executable, no shell, and every argument a literal built here.
        completed = subprocess.run(
            [GIT_EXECUTABLE, *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _max_mtime(root: Path, files: Sequence[Path]) -> datetime:
    """R5's fallback: the newest mtime among the artifact's scanned files.

    The artifact root's own mtime is used only when the artifact has no files at all — a V1
    directory has none, and git cannot track an empty directory either, so without this an artifact
    that exists on disk would have no timestamp to report.
    """
    stamps = []
    for file in files:
        try:
            stamps.append(file.stat().st_mtime)
        except OSError:  # pragma: no cover - the file was read moments earlier
            continue
    if not stamps:
        try:
            stamps.append(root.stat().st_mtime)
        except OSError:  # pragma: no cover - the root was walked moments earlier
            stamps.append(0.0)
    return datetime.fromtimestamp(max(stamps), tz=UTC)


__all__ = [
    "ArtifactTimestamps",
    "FixedTimestamps",
    "GitTimestamps",
    "Timestamp",
]
