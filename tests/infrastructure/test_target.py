"""Contract C-12 over a real install target, against the committed fixture and real writes.

Charter §10: this layer is tested against **real files**. Two kinds, and the split is the one
`tests/fixtures/README.md` describes:

* the **committed fixture target** (`tests/fixtures/target/`), which is prerequisite P-3 and holds
  the shapes a `~/.claude` really holds — a foreign tree nobody here authored, a loose
  `settings.json`, an editor swap file, a binary, and a symlink that resolves out of the target.
  Nothing in this module writes into it, and one test proves that by hashing it before and after;
* **copies of it under `tmp_path`**, which is where every write goes.

`~/.claude/` is never used as a target by any test (initiative plan §8, cross-cutting).

**What this layer is blind to.** It cannot see whether a path it reports belongs to an artifact,
was installed by this tool, or has drifted — those are C-9's and C-10's, one layer up, and a test
here could not observe them because nothing is ever compared to a library or a manifest. It is
also the *only* layer that can see the things the domain suite cannot: that a symlink on a real
disk comes back flagged, and that the swap file the library scanner refuses is recorded here.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from harness_library.domain.hashing import hash_bytes
from harness_library.domain.target import TargetFile, TargetRepository
from harness_library.infrastructure.scanner import EDITOR_SWAP_SUFFIXES, is_text
from harness_library.infrastructure.target import (
    DIRECTORY_MODE,
    FILE_MODE,
    FilesystemTargetRepository,
)
from tests.infrastructure.conftest import FIXTURE_TARGET

THE_LINK = "skills/delivery-lead/references/elsewhere.md"
"""The committed fixture's symlink. It resolves outside the target root, which is the escape R6
names, and its destination is a real file so `ruff` does not exit 2 on the tree (L21)."""

THE_SWAP_FILE = "skills/delivery-lead/SKILL.md.swp"
"""The editor swap file. The library scanner skips this name; the target scanner records it."""

THE_BINARY = "skills/delivery-lead/references/diagram.png"

EVERY_FIXTURE_PATH = (
    "agents/scribe.md",
    "settings.json",
    "skills/delivery-lead/SKILL.md",
    "skills/delivery-lead/SKILL.md.swp",
    "skills/delivery-lead/references/cost-and-time.md",
    "skills/delivery-lead/references/diagram.png",
    "skills/delivery-lead/references/elsewhere.md",
    "skills/synced/.bucket-7c1f9a2e",
    "skills/synced/7c1f9a2e_4b0d3f61/remote-helper/SKILL.md",
)
"""Every path the committed fixture holds, in the order a scan produces them.

A golden list rather than a count: a count goes green when one path is swapped for another. Paths
only — no `is_symlink` — so that this test is not a second copy of the two the task's mutation is
aimed at (L42).
"""

OUTSIDE = Path(__file__).resolve().parent.parent / "fixtures" / "outside"
"""Where the fixture's symlink points. Outside the target, which is the point of it."""


@pytest.fixture
def target(fixture_target: Path) -> FilesystemTargetRepository:
    """The committed fixture, opened read-only. Every write in this module uses `writable`."""
    return FilesystemTargetRepository(fixture_target)


@pytest.fixture
def writable(fixture_target: Path, tmp_path: Path) -> Path:
    """A faithful, writable copy of the committed fixture under `tmp_path`.

    `symlinks=True` copies the link as a link rather than as its destination, and the destination
    is recreated at the same relative position so the copy's link resolves exactly as the
    committed one does. A copy whose link dangled would be a different fixture, and the write and
    delete refusals would be proven against the easy case.
    """
    root = tmp_path / "target"
    shutil.copytree(fixture_target, root, symlinks=True)
    shutil.copytree(OUTSIDE, tmp_path / "outside")
    return root


def _entry(entries: tuple[TargetFile, ...], path: str) -> TargetFile:
    """The one entry at `path`, failing the test loudly rather than raising `StopIteration`."""
    found = [entry for entry in entries if entry.path == path]
    assert len(found) == 1, (
        f"expected exactly one entry at {path!r}, found {[e.path for e in found]}"
    )
    return found[0]


def _hash_tree(root: Path) -> dict[str, str]:
    """Every path under `root` and a digest of what it is — a symlink by the path it names.

    Content, not mtime (L37): the committed fixture's mtimes move when git touches it, and mtime
    would report a change where there is none and miss a rewrite that kept the timestamp.
    """
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            manifest[relative] = f"symlink:{os.readlink(path)}"
        elif path.is_file():
            manifest[relative] = hash_bytes(path.read_bytes())
    return manifest


# -------------------------------------------------------------------------------------------
# The scan — what a target is, and how it differs from a library
# -------------------------------------------------------------------------------------------


def test_the_scan_records_every_path_in_the_fixture_in_a_deterministic_order(
    target: FilesystemTargetRepository,
) -> None:
    """The whole tree, depth-first and name-sorted, with nothing filtered out."""
    assert [entry.path for entry in target.scan()] == list(EVERY_FIXTURE_PATH)


def test_two_scans_of_one_target_agree(target: FilesystemTargetRepository) -> None:
    """Determinism is a property this layer is asserted on: a report that reorders itself between
    two runs cannot be diffed or pinned to the golden list above."""
    assert target.scan() == target.scan()


def test_the_installed_files_are_recorded(target: FilesystemTargetRepository) -> None:
    """The control for the foreign-tree mutation: the paths this tool would have installed are
    recorded whether or not anything foreign is."""
    paths = [entry.path for entry in target.scan()]

    assert "skills/delivery-lead/SKILL.md" in paths
    assert "skills/delivery-lead/references/cost-and-time.md" in paths
    assert "agents/scribe.md" in paths


def test_the_foreign_synced_tree_is_recorded_whole(target: FilesystemTargetRepository) -> None:
    """Claude Code's own skill-sync bucket, two levels down, with no entry document at its root
    and no library artifact claiming it.

    **Ruling R44: it gets no named exclusion.** It is `FOREIGN` like anything else the library and
    the manifest both disown, and an exclusion keyed on the name `synced` would silently hide
    whatever else that directory grows — which it does, between one dispatch and the next.
    """
    paths = [entry.path for entry in target.scan()]

    assert "skills/synced/.bucket-7c1f9a2e" in paths
    assert "skills/synced/7c1f9a2e_4b0d3f61/remote-helper/SKILL.md" in paths


def test_the_loose_foreign_settings_file_is_recorded(
    target: FilesystemTargetRepository,
) -> None:
    """`settings.json` sits at the target root, under no artifact root at all. It is the path R60
    exists for: the plan entry for it carries `artifact_id=None`, because there is no
    `<type>/<name>` to give it."""
    paths = [entry.path for entry in target.scan()]

    assert "settings.json" in paths


def test_the_editor_swap_file_the_library_scanner_refuses_is_recorded_here(
    target: FilesystemTargetRepository,
) -> None:
    """The sharpest single difference between the two scanners, asserted rather than described.

    `EDITOR_SWAP_SUFFIXES` is imported from the library scanner so this is a statement about *that
    module's* rule and not about a name that happens to look like one: the library skips this path
    and reports V6, because it is deciding what an artifact contains. The target scanner records
    it, because it is reporting what is there — and install has to see it to leave it alone.
    """
    assert THE_SWAP_FILE.endswith(EDITOR_SWAP_SUFFIXES)
    assert THE_SWAP_FILE in [entry.path for entry in target.scan()]


def test_each_entry_carries_the_real_digest_and_size_of_its_bytes(
    target: FilesystemTargetRepository, fixture_target: Path
) -> None:
    """`sha256` is `hashing.hash_bytes` over the file's contents — the project's one hashing
    implementation (charter §7), not a second `hashlib` call that would drift from it."""
    entry = _entry(target.scan(), "skills/delivery-lead/SKILL.md")
    data = (fixture_target / "skills/delivery-lead/SKILL.md").read_bytes()

    assert entry.sha256 == hash_bytes(data)
    assert entry.size == len(data)


def test_two_different_files_carry_two_different_digests(
    target: FilesystemTargetRepository,
) -> None:
    """Positive control for the assertion above: a digest that was constant, or empty, would
    satisfy `== hash_bytes(data)` for exactly one file and go unnoticed."""
    entries = target.scan()

    assert _entry(entries, "settings.json").sha256 != _entry(entries, "agents/scribe.md").sha256


# -------------------------------------------------------------------------------------------
# Symlinks — recorded, never followed (R6). The task's mutation subject and its control.
# -------------------------------------------------------------------------------------------


def test_the_scan_records_the_fixtures_real_symlink_as_one(
    target: FilesystemTargetRepository,
) -> None:
    """**The mutation subject.** A real, committed symlink, walked off a real disk.

    A fake cannot prove this: a fake returns whatever flag it was written to return. Only a scan
    of a directory that really contains a link can show that `is_symlink` is derived from the disk
    rather than defaulted. The previous initiative shipped a rule green and non-functional because
    nothing populated the list it read; this is the assertion that shape would have failed.
    """
    assert _entry(target.scan(), THE_LINK).is_symlink is True


def test_an_ordinary_file_in_the_same_scan_is_not_a_symlink(
    target: FilesystemTargetRepository,
) -> None:
    """**The must-stay-green control.** Without it, "always `False`" and "correct for ordinary
    files" are the same test result, and a scanner that flagged nothing would look right."""
    assert _entry(target.scan(), "skills/delivery-lead/SKILL.md").is_symlink is False


def test_the_symlink_entry_carries_no_content_digest(
    target: FilesystemTargetRepository,
) -> None:
    """R6: never followed, never hashed. The link's `size` is its own — the length of the path it
    names — and not the size of what it points at."""
    entry = _entry(target.scan(), THE_LINK)
    destination = OUTSIDE / "target-escape.md"

    assert entry.sha256 is None
    assert entry.size == len("../../../../outside/target-escape.md")
    assert entry.size != destination.stat().st_size


def test_nothing_outside_the_target_is_hashed_through_the_link(
    target: FilesystemTargetRepository,
) -> None:
    """The assertion of absence, with its positive control in the same test.

    Absence: no entry in the scan carries the destination's digest. Control: the destination is a
    real file with a real digest, so the search had something to find — without it this passes
    just as well when the file is missing or `hash_bytes` returns a constant.
    """
    destination = OUTSIDE / "target-escape.md"
    outside_digest = hash_bytes(destination.read_bytes())

    assert destination.is_file(), "positive control: the link's destination must exist (L21)"
    assert len(outside_digest) == 64
    assert outside_digest not in [entry.sha256 for entry in target.scan()]


def test_a_symlinked_path_is_never_read_through(target: FilesystemTargetRepository) -> None:
    """`read_bytes` refuses the link the scan recorded. The scan reporting a path and the
    repository refusing to read it is not a contradiction — it is the whole posture: install must
    *see* the link to leave it alone, and must never resolve it."""
    with pytest.raises(ValueError, match="never followed"):
        target.read_bytes(THE_LINK)


# -------------------------------------------------------------------------------------------
# Text and binary — charter §7, decided per file by the library scanner's one implementation
# -------------------------------------------------------------------------------------------


def test_a_binary_target_file_round_trips_through_read_bytes(
    target: FilesystemTargetRepository, fixture_target: Path
) -> None:
    """Byte-identical, which is the guarantee charter §7 makes about binary: stored, hashed and
    installed, never decoded. A `read_text` on this surface would make that unprovable."""
    data = target.read_bytes(THE_BINARY)

    assert data == (fixture_target / THE_BINARY).read_bytes()
    assert data.startswith(b"\x89PNG"), "positive control: the fixture's binary is really a PNG"


def test_text_and_binary_are_decided_per_file_by_the_scanners_one_implementation(
    target: FilesystemTargetRepository,
) -> None:
    """Charter §7 decides this **per file**, and `infrastructure.scanner.is_text` is the single
    implementation of it. `TargetFile` carries no `is_text` because C-12 gives it no such field
    and no member of C-12 needs one; the decision is made over the bytes `read_bytes` returns,
    here and in T-21's diff, and this module adds no second copy of the rule."""
    assert is_text(target.read_bytes("skills/delivery-lead/SKILL.md")) is True
    assert is_text(target.read_bytes(THE_BINARY)) is False
    assert is_text(target.read_bytes(THE_SWAP_FILE)) is False


# -------------------------------------------------------------------------------------------
# Writing, deleting and existence — all of it under tmp_path
# -------------------------------------------------------------------------------------------


def test_write_creates_the_file_and_the_directories_it_needs(writable: Path) -> None:
    repository = FilesystemTargetRepository(writable)

    repository.write("skills/new-skill/references/note.md", b"# note\n")

    assert (writable / "skills/new-skill/references/note.md").read_bytes() == b"# note\n"


def test_write_normalises_the_mode_it_leaves_behind(writable: Path) -> None:
    """F-9 and ruling R56: files `0644`, directories `0755`. `write` is the only thing that
    creates a file in a target, so leaving the mode to the process umask is how a strict umask
    ships a user a harness their own editor cannot read. Mode is excluded from the content hash
    (R9), so normalising it moves no digest and no verdict."""
    repository = FilesystemTargetRepository(writable)

    repository.write("skills/new-skill/references/note.md", b"# note\n")

    written = writable / "skills/new-skill/references/note.md"
    assert stat.S_IMODE(written.stat().st_mode) == FILE_MODE
    assert stat.S_IMODE(written.parent.stat().st_mode) == DIRECTORY_MODE


def test_write_leaves_a_directory_it_did_not_create_alone(writable: Path) -> None:
    """Only the directories this call created are normalised. A directory the user chose the mode
    of is theirs."""
    chosen = writable / "skills/delivery-lead"
    chosen.chmod(0o700)
    repository = FilesystemTargetRepository(writable)

    repository.write("skills/delivery-lead/extra.md", b"x\n")

    assert stat.S_IMODE(chosen.stat().st_mode) == 0o700


def test_write_replaces_the_contents_of_an_existing_file(writable: Path) -> None:
    repository = FilesystemTargetRepository(writable)

    repository.write("skills/delivery-lead/SKILL.md", b"replaced\n")

    assert repository.read_bytes("skills/delivery-lead/SKILL.md") == b"replaced\n"


def test_delete_removes_one_file_and_leaves_its_neighbour(writable: Path) -> None:
    repository = FilesystemTargetRepository(writable)

    repository.delete("skills/delivery-lead/SKILL.md.swp")

    assert not (writable / "skills/delivery-lead/SKILL.md.swp").exists()
    assert (writable / "skills/delivery-lead/SKILL.md").is_file()


def test_delete_refuses_a_directory(writable: Path) -> None:
    """Uninstall removes the files a manifest names and nothing else (F-12). A repository that
    could remove a directory is a repository T-18 could use to take a foreign file with it."""
    repository = FilesystemTargetRepository(writable)

    with pytest.raises(IsADirectoryError):
        repository.delete("skills/delivery-lead")

    assert (writable / "skills/delivery-lead").is_dir()


def test_delete_says_so_when_there_is_nothing_there(writable: Path) -> None:
    repository = FilesystemTargetRepository(writable)

    with pytest.raises(FileNotFoundError):
        repository.delete("skills/delivery-lead/never-existed.md")


def test_exists_answers_for_a_file_and_for_nothing(writable: Path) -> None:
    repository = FilesystemTargetRepository(writable)

    assert repository.exists("settings.json") is True
    assert repository.exists("settings.yaml") is False


def test_exists_counts_a_dangling_symlink(tmp_path: Path) -> None:
    """The question `exists` answers is "would a write land on something", and a link whose
    destination is gone is very much something: writing through it would create the destination
    wherever it points."""
    root = tmp_path / "target"
    root.mkdir()
    (root / "broken.md").symlink_to(tmp_path / "gone" / "missing.md")
    repository = FilesystemTargetRepository(root)

    assert (root / "broken.md").exists() is False, "positive control: the destination is absent"
    assert repository.exists("broken.md") is True


def test_a_scan_is_a_fresh_walk_and_not_a_held_snapshot(writable: Path) -> None:
    """`FilesystemArtifactRepository` caches its scan because C-4 promises one snapshot per
    process. This one writes, so a cached scan would describe a target that stopped existing at
    the first `write`."""
    repository = FilesystemTargetRepository(writable)
    before = [entry.path for entry in repository.scan()]

    repository.write("skills/new-skill/SKILL.md", b"new\n")

    assert "skills/new-skill/SKILL.md" not in before
    assert "skills/new-skill/SKILL.md" in [entry.path for entry in repository.scan()]


# -------------------------------------------------------------------------------------------
# Refusals — the ways a relative path still leaves the target
# -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["", ".", "/etc/passwd", "../outside/target-escape.md", "skills/../../escape.md"],
    ids=["empty", "dot", "absolute", "climbs-out", "climbs-out-mid-path"],
)
def test_a_path_that_is_not_inside_the_target_is_refused(
    target: FilesystemTargetRepository, path: str
) -> None:
    """Stage one, and it is a property of the string: no filesystem is consulted, so the refusal
    holds on a target that happens not to contain the escaped-to file."""
    with pytest.raises(ValueError, match="not a path inside this target"):
        target.read_bytes(path)


def test_every_member_refuses_a_path_that_climbs_out(writable: Path) -> None:
    """The refusal is in `_locate`, which is the only way any of the four reaches the disk — so
    the guarantee is not one `read_bytes` happens to have and `write` happens not to."""
    repository = FilesystemTargetRepository(writable)
    escape = "../outside/target-escape.md"

    for call in (
        lambda: repository.read_bytes(escape),
        lambda: repository.write(escape, b"owned\n"),
        lambda: repository.delete(escape),
        lambda: repository.exists(escape),
    ):
        with pytest.raises(ValueError, match="not a path inside this target"):
            call()


def test_a_path_through_a_symlinked_directory_is_refused(tmp_path: Path) -> None:
    """The realistic escape: no `..` anywhere in the path, and it still leaves the target because
    one of its directories is a link. Nobody writes `../../etc`; people really do symlink
    `~/.claude/skills` onto another disk."""
    root = tmp_path / "target"
    (root / "real").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "taken.md").write_text("theirs\n", encoding="utf-8")
    (root / "linked").symlink_to(elsewhere, target_is_directory=True)
    repository = FilesystemTargetRepository(root)

    with pytest.raises(ValueError, match="which is a symlink"):
        repository.write("linked/taken.md", b"ours\n")

    assert (elsewhere / "taken.md").read_text(encoding="utf-8") == "theirs\n"


def test_writing_through_a_symlink_is_refused_and_its_destination_is_untouched(
    writable: Path, tmp_path: Path
) -> None:
    """The escape R6 names, stated as bytes: a link resolving outside the target is how a copy
    writes where it should not. Asserted on the destination file, not on the refusal — F-10's
    posture, because a report can say "left alone" while the bytes disagree."""
    destination = tmp_path / "outside" / "target-escape.md"
    before = destination.read_bytes()
    repository = FilesystemTargetRepository(writable)

    assert (writable / THE_LINK).is_file(), "positive control: the copy's link really resolves"
    with pytest.raises(ValueError, match="never written through"):
        repository.write(THE_LINK, b"owned\n")

    assert destination.read_bytes() == before


def test_deleting_a_symlink_removes_the_link_and_not_what_it_points_at(
    writable: Path, tmp_path: Path
) -> None:
    """`delete` is the one member that accepts a symlinked final component, because `os.unlink`
    removes the link itself. Refusing here would leave a link planted over an installed path
    impossible to uninstall."""
    destination = tmp_path / "outside" / "target-escape.md"
    before = destination.read_bytes()
    repository = FilesystemTargetRepository(writable)

    repository.delete(THE_LINK)

    assert not (writable / THE_LINK).is_symlink()
    assert destination.read_bytes() == before


def test_a_target_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    """Charter §13's posture, one directory over: fail loudly rather than treat a typo as an empty
    target and install a whole harness into it. Creating a target that does not exist is the
    composition root's decision (T-22), not a side effect of building a repository."""
    not_a_directory = tmp_path / "settings.json"
    not_a_directory.write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="not an install target"):
        FilesystemTargetRepository(not_a_directory)

    with pytest.raises(FileNotFoundError, match="not an install target"):
        FilesystemTargetRepository(tmp_path / "never-created")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file regardless")
def test_a_file_the_scan_cannot_read_is_a_fault_and_not_an_absence(writable: Path) -> None:
    """Where this scanner parts company with the library's, which answers an unreadable path with
    a `SkippedPath` and carries on.

    A target path missing from the scan is a path the verdict rule is told the target does not
    hold — `CREATE` — and the next apply writes straight over it. Refusing to produce a scan at
    all is the only honest answer, and there is no C-6 code for it yet: `TARGET_UNWRITABLE` is
    about writing. Flagged to the delivery lead.
    """
    unreadable = writable / "settings.json"
    unreadable.chmod(0o000)
    repository = FilesystemTargetRepository(writable)
    try:
        with pytest.raises(PermissionError):
            repository.scan()
    finally:
        unreadable.chmod(0o644)

    assert [entry.path for entry in repository.scan()] == list(EVERY_FIXTURE_PATH)


# -------------------------------------------------------------------------------------------
# Nothing in this module writes outside tmp_path
# -------------------------------------------------------------------------------------------


def test_writing_through_the_repository_never_touches_the_committed_fixture(
    writable: Path, tmp_path: Path
) -> None:
    """The cross-cutting criterion, proven by content hash and never by mtime (L37): the committed
    fixture's timestamps move when git touches it, and mtime would report a change where there is
    none while missing a rewrite that kept the timestamp.

    The positive control is the copy: the same battery of writes really does change *it*, so the
    committed tree's manifest staying equal is evidence rather than a comparison of two things
    that could not have differed.
    """
    fixture_before = _hash_tree(FIXTURE_TARGET)
    outside_before = _hash_tree(OUTSIDE)
    copy_before = _hash_tree(writable)
    repository = FilesystemTargetRepository(writable)

    repository.write("skills/new-skill/SKILL.md", b"new\n")
    repository.write("settings.json", b"{}\n")
    repository.delete("skills/delivery-lead/SKILL.md.swp")

    assert _hash_tree(writable) != copy_before, "positive control: the copy really was written to"
    assert _hash_tree(FIXTURE_TARGET) == fixture_before
    assert _hash_tree(OUTSIDE) == outside_before
    assert len(fixture_before) == len(EVERY_FIXTURE_PATH)


def test_the_filesystem_repository_satisfies_the_protocol(
    target: FilesystemTargetRepository,
) -> None:
    """Structural, never inherited — ruling R14's shape: `domain/` keeps knowing nothing about who
    implements its protocols."""
    assert isinstance(target, TargetRepository)


# ==================================================================================================
# Ruling R94 — reading a link as a link, and writing one back
# ==================================================================================================
#
# Neither member is in contract C-12, which has five "and no sixth" because every member a fake
# implements is a member two tasks can get wrong in two places. Nothing that plans or applies an
# install needs these; the only caller is `FilesystemBackupStore`, which already holds this
# concrete class. **Flagged: C-12 wants them, and that is a plan-level decision.**


def test_a_link_is_read_as_the_raw_text_it_names(writable: Path) -> None:
    """`readlink`, never `resolve`. The `..` components are kept, which is both the whole
    diagnosis when a link escapes the target and what makes recreating it reproduce the link the
    user actually wrote rather than an absolute path this tool invented."""
    repository = FilesystemTargetRepository(writable)

    assert repository.read_link(THE_LINK) == "../../../../outside/target-escape.md"


def test_reading_a_regular_file_as_a_link_is_refused(writable: Path) -> None:
    """A regular file names no destination, and answering with one would invent it. The link in
    the same target is the positive control: the refusal is about this path, not about a member
    that refuses everything."""
    repository = FilesystemTargetRepository(writable)

    with pytest.raises(ValueError, match="not a symlink"):
        repository.read_link("settings.json")

    assert repository.read_link(THE_LINK) != ""


def test_reading_a_link_that_is_not_there_is_a_missing_file(writable: Path) -> None:
    """Told apart from the refusal above, because the two are different mistakes: one is "that
    path is not a link" and the other is "that path is nothing at all"."""
    repository = FilesystemTargetRepository(writable)

    with pytest.raises(FileNotFoundError):
        repository.read_link("skills/never-existed/SKILL.md")


def test_a_written_link_is_a_link_and_not_a_copy_of_its_destination(writable: Path) -> None:
    """**What makes a restore a restore.** Writing the destination's *bytes* would satisfy "the
    path is back" and would leave the user with a snapshot of somebody else's directory where
    they had a pointer to it.

    Asserted on `is_symlink`, on the raw destination, and on the content reachable through it.
    """
    repository = FilesystemTargetRepository(writable)
    repository.delete(THE_LINK)

    repository.write_link(THE_LINK, "../../../../outside/target-escape.md")

    assert (writable / THE_LINK).is_symlink()
    assert os.readlink(writable / THE_LINK) == "../../../../outside/target-escape.md"
    assert (writable / THE_LINK).read_bytes() == (
        writable.parent / "outside" / "target-escape.md"
    ).read_bytes()


def test_writing_a_link_replaces_whatever_is_at_the_path(writable: Path) -> None:
    """A restore puts a target back, whatever took the path's place in the meantime — a regular
    file a reinstall left, or another link. `os.symlink` refuses an existing name outright, so
    the old entry is unlinked **as itself** first, never followed."""
    repository = FilesystemTargetRepository(writable)
    repository.write("skills/new-skill/SKILL.md", b"an ordinary file\n")

    repository.write_link("skills/new-skill/SKILL.md", "../../elsewhere.md")

    assert (writable / "skills/new-skill/SKILL.md").is_symlink()
    assert os.readlink(writable / "skills/new-skill/SKILL.md") == "../../elsewhere.md"


def test_writing_a_link_creates_the_directories_it_needs(writable: Path) -> None:
    """The same parent handling `write` does, at `DIRECTORY_MODE`, so a restore into a target
    whose directories a clean emptied still lands."""
    repository = FilesystemTargetRepository(writable)

    repository.write_link("skills/brand-new/references/link.md", "../../../outside/whatever.md")

    created = writable / "skills/brand-new/references"
    assert (created / "link.md").is_symlink()
    assert stat.S_IMODE(created.stat().st_mode) == DIRECTORY_MODE


def test_a_link_is_never_written_through_a_symlinked_directory(writable: Path) -> None:
    """The same three-stage path safety every other member keeps (R6). Nobody writes
    `../../etc`, but a user really does symlink `~/.claude/skills` somewhere."""
    (writable / "linked-skills").symlink_to("skills", target_is_directory=True)
    repository = FilesystemTargetRepository(writable)

    with pytest.raises(ValueError, match="is a symlink"):
        repository.write_link("linked-skills/new/SKILL.md", "../../outside/x.md")


def test_a_link_with_no_destination_is_refused(writable: Path) -> None:
    """A link's destination is its whole content, and the empty string is not one. Refused here
    rather than at `os.symlink`, so the diagnosis names the path."""
    repository = FilesystemTargetRepository(writable)

    with pytest.raises(ValueError, match="empty destination"):
        repository.write_link("skills/new-skill/SKILL.md", "")


def test_a_written_link_may_dangle_and_is_reported_as_one(writable: Path) -> None:
    """A dangling link restores as a dangling link, because that is what was there. The
    destination is written verbatim and never checked: correcting it would put back a different
    link from the one that was removed."""
    repository = FilesystemTargetRepository(writable)

    repository.write_link("skills/new-skill/SKILL.md", "nowhere-at-all.md")

    assert (writable / "skills/new-skill/SKILL.md").is_symlink()
    assert not (writable / "skills/new-skill/SKILL.md").exists()
    assert repository.exists("skills/new-skill/SKILL.md")
