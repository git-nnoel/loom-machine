"""Ruling R5 — `updated_at` from git, with the mtime fallback. Against real repositories.

Every test here builds its own git work tree under `tmp_path` and **owns the commit dates**. That is
what makes "this answer came from git and not from a file's mtime" an assertion rather than a
coincidence: the commit dates are set years away from any mtime the test could produce, so a scanner
that silently fell back to mtime for everything cannot accidentally agree with them.

The committed fixture library is deliberately **not** used here. It lives inside this repository, so
it is dirty while uncommitted and clean once committed, and any timestamp asserted against it would
flip at that boundary.

What this module is blind to: nothing about validation. R5 fills two fields on a value; whether the
artifact carrying them is valid is charter §8's business, decided a layer up.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loom.domain.raw import RawArtifact
from loom.infrastructure.scanner import scan_library
from loom.infrastructure.timestamps import (
    FixedTimestamps,
    GitTimestamps,
    Timestamp,
    _parse_porcelain_z,
)
from tests.infrastructure.conftest import git, init_repository, write, write_skill

ANCIENT = "2021-03-04T05:06:07+00:00"
"""A commit date far enough from any mtime this suite can produce that agreeing with it by accident
is impossible."""

LESS_ANCIENT = "2022-07-08T09:10:11+00:00"


@pytest.fixture(autouse=True)
def _git_is_installed() -> None:
    """R5's subject. A skip here would quietly retire the guard, so it fails instead."""
    if shutil.which("git") is None:  # pragma: no cover - git is a hard requirement of this repo
        pytest.fail("git is not installed, so ruling R5 cannot be verified")


def scan(library_root: Path) -> dict[str, RawArtifact]:
    """A real scan, with the real `GitTimestamps` — the whole point of this module."""
    return {raw.id: raw for raw in scan_library(library_root).artifacts}


# ==================================================================================================
# The named assertion of R5 — the one test that fails if git is never consulted
# ==================================================================================================


def test_updated_at_is_the_last_commit_touching_the_artifact_and_not_its_mtime(
    tmp_path: Path,
) -> None:
    """Ruling R5, stated as the difference between two artifacts in one repository.

    **This is the test that fails if `updated_at` silently fell back to mtime for every artifact.**
    Both skills are written moments before the scan, so both mtimes are "now"; their commits are
    dated 2021 and 2022. A scanner reading mtime would give the two artifacts the same present-day
    timestamp, and would agree with neither literal below. A scanner reading `git log` on the whole
    repository rather than on the artifact's own paths would give both the *later* date — which is
    why there are two artifacts here and not one.
    """
    init_repository(tmp_path)
    write_skill(tmp_path, "older")
    git(tmp_path, "add", "skills/older")
    git(tmp_path, "commit", "-m", "add older", when=ANCIENT)

    write_skill(tmp_path, "newer")
    git(tmp_path, "add", "skills/newer")
    git(tmp_path, "commit", "-m", "add newer", when=LESS_ANCIENT)

    scanned = scan(tmp_path)

    assert scanned["skill/older"].updated_at == datetime.fromisoformat(ANCIENT)
    assert scanned["skill/newer"].updated_at == datetime.fromisoformat(LESS_ANCIENT)
    assert scanned["skill/older"].is_dirty is False
    assert scanned["skill/newer"].is_dirty is False


def test_a_later_commit_touching_the_artifact_moves_its_timestamp(tmp_path: Path) -> None:
    """Positive control for the two literals above: they are capable of changing, so pinning them
    is evidence that git was read and not that a constant was returned."""
    init_repository(tmp_path)
    root = write_skill(tmp_path, "moving")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "first", when=ANCIENT)

    write(root / "references" / "added.md", "# Added later\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "second", when=LESS_ANCIENT)

    assert scan(tmp_path)["skill/moving"].updated_at == datetime.fromisoformat(LESS_ANCIENT)


# ==================================================================================================
# The two fallbacks, and `is_dirty` on both of them
# ==================================================================================================


def test_a_library_that_is_not_a_repository_falls_back_to_mtime_and_is_dirty(
    tmp_path: Path,
) -> None:
    """R5's first fallback. A plain directory of skills is a supported way to hold a library, so
    this is a documented path and not a degraded mode — which is why nothing raises."""
    write_skill(tmp_path, "loose")

    raw = scan(tmp_path)["skill/loose"]

    assert raw.is_dirty is True
    assert raw.updated_at.tzinfo is not None
    entry_mtime = (tmp_path / "skills" / "loose" / "SKILL.md").stat().st_mtime
    assert raw.updated_at == datetime.fromtimestamp(entry_mtime, tz=UTC)


def test_an_artifact_with_uncommitted_changes_falls_back_to_mtime_and_is_dirty(
    tmp_path: Path,
) -> None:
    """R5's second fallback, and the pairing that makes it meaningful: one artifact in the same
    repository is committed and clean, the other is edited and dirty. Without the clean sibling,
    "dirty" could just as well be "this code never asks git anything"."""
    init_repository(tmp_path)
    write_skill(tmp_path, "clean")
    edited = write_skill(tmp_path, "edited")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "both", when=ANCIENT)

    (edited / "SKILL.md").write_text("---\nname: edited\ndescription: changed\n---\n", "utf-8")

    scanned = scan(tmp_path)

    assert scanned["skill/clean"].is_dirty is False
    assert scanned["skill/clean"].updated_at == datetime.fromisoformat(ANCIENT)
    assert scanned["skill/edited"].is_dirty is True
    assert scanned["skill/edited"].updated_at != datetime.fromisoformat(ANCIENT)


def test_an_untracked_file_anywhere_under_the_root_makes_the_whole_artifact_dirty(
    tmp_path: Path,
) -> None:
    """The artifact is the unit, not the file — a new reference nobody committed means the
    artifact's committed date no longer describes what is on disk."""
    init_repository(tmp_path)
    root = write_skill(tmp_path, "growing")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "first", when=ANCIENT)

    write(root / "references" / "brand-new.md", "# Not committed\n")

    assert scan(tmp_path)["skill/growing"].is_dirty is True


def test_a_staged_rename_makes_the_artifact_dirty(tmp_path: Path) -> None:
    """The rename record in `git status --porcelain -z` carries a *second* path field. A parser
    that read that field as a new record would misread the stream from there on, and the artifact
    would report a stale commit date as if it were current."""
    init_repository(tmp_path)
    root = write_skill(tmp_path, "renaming")
    write(root / "references" / "before.md", "# Before\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "first", when=ANCIENT)

    git(
        tmp_path,
        "mv",
        "skills/renaming/references/before.md",
        "skills/renaming/references/after.md",
    )

    assert scan(tmp_path)["skill/renaming"].is_dirty is True


def test_an_artifact_in_a_library_below_the_repository_root_is_read_correctly(
    tmp_path: Path,
) -> None:
    """`git status --porcelain` answers in repository-relative paths while a pathspec is resolved
    relative to the current directory. Conflating the two reports every artifact clean in any
    library that is not itself the repository root — which is most of them."""
    init_repository(tmp_path)
    library = tmp_path / "nested" / "library"
    write_skill(library, "buried")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "buried", when=ANCIENT)

    clean = scan(library)["skill/buried"]
    assert clean.is_dirty is False
    assert clean.updated_at == datetime.fromisoformat(ANCIENT)

    # Positive control: the same nested library, now edited, is seen as dirty. Without it, the
    # `is_dirty is False` above would also pass for a prefix bug that matched nothing at all.
    (library / "skills" / "buried" / "SKILL.md").write_text("---\nname: buried\n---\n", "utf-8")
    assert scan(library)["skill/buried"].is_dirty is True


def test_a_v1_directory_with_no_files_still_gets_a_timestamp(tmp_path: Path) -> None:
    """An artifact with no files has no file mtimes to take a maximum of, and git cannot track an
    empty directory either. The root's own mtime is the floor beneath both, so an artifact that
    exists on disk always has a timestamp to report."""
    (tmp_path / "skills" / "empty").mkdir(parents=True)

    raw = scan(tmp_path)["skill/empty"]

    assert raw.files == ()
    assert raw.updated_at.tzinfo is not None
    assert raw.is_dirty is True


# ==================================================================================================
# The pieces, directly
# ==================================================================================================


def test_git_timestamps_reports_whether_it_found_a_work_tree(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert GitTimestamps(plain).in_repository is False

    repository = tmp_path / "repository"
    init_repository(repository)
    assert GitTimestamps(repository).in_repository is True


def test_parse_porcelain_z_consumes_the_second_path_of_a_rename_record() -> None:
    """Driven directly because building every porcelain shape through real git commands is
    impractical, and this parser is the piece most likely to be subtly wrong. The end-to-end
    counterpart is `test_a_staged_rename_makes_the_artifact_dirty`."""
    stream = (
        "R  skills/new/SKILL.md\0skills/old/SKILL.md\0 M skills/edited/SKILL.md\0?? untracked\0"
    )

    assert _parse_porcelain_z(stream) == [
        "skills/new/SKILL.md",
        "skills/old/SKILL.md",
        "skills/edited/SKILL.md",
        "untracked",
    ]


def test_parse_porcelain_z_of_an_empty_stream_is_empty() -> None:
    """Positive control for the absence this parser reports as "nothing is dirty"."""
    assert _parse_porcelain_z("") == []


def test_a_naive_timestamp_is_rejected() -> None:
    """`Artifact` and `RawArtifact` both refuse a naive `updated_at`, because mixing a naive value
    from the mtime path with an aware one from the git path raises inside sorting, far from the
    cause. `Timestamp` refuses it at the source, where the two paths are still visible together."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Timestamp(datetime(2026, 1, 1), is_dirty=False)


def test_fixed_timestamps_answers_the_same_for_every_artifact(tmp_path: Path) -> None:
    """The double the rest of the suite scans with. Pinned so a test elsewhere asserting
    `updated_at == SCANNED_AT` is asserting something about the scanner's plumbing."""
    fixed = FixedTimestamps(datetime(2026, 8, 31, 12, 0, tzinfo=UTC), is_dirty=True)

    assert fixed.for_artifact(tmp_path, []) == Timestamp(
        datetime(2026, 8, 31, 12, 0, tzinfo=UTC), is_dirty=True
    )
