"""The scanner, against real files. Charter §10.

**This module exists to close the gap `tests/domain/test_assembly.py` names in its own docstring.**
That suite proves a `RawArtifact` with no entry produces V1, and that a recorded `SkippedPath`
becomes a V6 warning. It cannot prove — and says so — that a real directory missing a real
`SKILL.md` produces that `RawArtifact`, or that a real symlink in a real directory is recorded
as skipped at all. Every test here is that half, and it is why the T-5 mutation sits above
the fake.

What *this* layer is blind to, stated once: it decides nothing about validity. No
`ValidationFinding` is reachable from here, no rule is implemented here, and a scan of a library
full of broken artifacts produces no error — only values. Whether a recorded skip is a warning or a
disaster is charter §8's business, and `tests/infrastructure/test_repository.py` is where the two
halves are proven to meet.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness_library.domain.artifact import ArtifactKind
from harness_library.domain.identity import ArtifactType
from harness_library.domain.raw import LibraryScan, RawArtifact, SkipReason
from harness_library.infrastructure.scanner import is_text, scan_library
from tests.infrastructure.conftest import FIXED_TIMESTAMPS, SCANNED_AT, write, write_skill


def scan(library_root: Path) -> dict[str, RawArtifact]:
    """Scan with R5 held still, keyed by artifact id."""
    return {
        raw.id: raw for raw in scan_library(library_root, timestamps=FIXED_TIMESTAMPS).artifacts
    }


AGENT_DOCUMENT = "---\nname: scribe\ndescription: writes things down\n---\n"
"""A well-formed `FILE`-kind artifact, for the tests that link to one from outside."""


def paths(raw: RawArtifact) -> list[str]:
    return [file.path for file in raw.files]


def skips(raw: RawArtifact) -> list[tuple[str, SkipReason]]:
    return [(skipped.path, skipped.reason) for skipped in raw.skipped]


# ==================================================================================================
# The baseline every perturbation below is measured against
# ==================================================================================================


def test_a_well_formed_skill_directory_scans_into_a_complete_raw_artifact(tmp_path: Path) -> None:
    """The positive control the absence assertions in this module lean on: the scanner is capable
    of producing a full value from a real tree, so an empty `files` or `skipped` elsewhere is
    evidence rather than a walk that never ran."""
    write_skill(tmp_path, "delivery-lead", body="See references/checklist.md.")
    write(tmp_path / "skills" / "delivery-lead" / "references" / "checklist.md", "# Checklist\n")

    raw = scan(tmp_path)["skill/delivery-lead"]

    assert raw.type is ArtifactType.SKILL
    assert raw.name == "delivery-lead"
    assert raw.kind is ArtifactKind.DIRECTORY
    assert raw.root_path == "skills/delivery-lead"
    assert raw.entry_path == "SKILL.md"
    assert paths(raw) == ["SKILL.md", "references/checklist.md"]
    assert raw.skipped == ()
    assert raw.entry is not None
    assert raw.entry.frontmatter["name"] == "delivery-lead"
    assert "See references/checklist.md." in raw.entry.body
    assert raw.updated_at == SCANNED_AT


def test_every_scanned_file_carries_its_own_digest_and_size(tmp_path: Path) -> None:
    """Contract C-1. Initiative 02 judges install per path, so the per-file digest is not a
    convenience — a scan that produced only a whole-artifact hash would make that initiative
    re-implement this walk on a second code path."""
    write_skill(tmp_path, "sized", body="x" * 40)

    (entry,) = scan(tmp_path)["skill/sized"].files

    assert entry.size == (tmp_path / "skills" / "sized" / "SKILL.md").stat().st_size
    assert len(entry.sha256) == 64
    assert entry.is_text is True


# ==================================================================================================
# V1's real half — a real directory with no real entry document
# ==================================================================================================


def test_a_skill_directory_with_no_entry_document_scans_with_entry_none(tmp_path: Path) -> None:
    """The producer side of V1, which the domain suite cannot reach.

    `tests/domain/test_assembly.py` proves `entry=None` becomes a V1 ERROR. Only this test proves
    that a real directory really missing its `SKILL.md` is what produces `entry=None` — the failure
    observed twice on the real library, both times loading silently as nothing.
    """
    root = tmp_path / "skills" / "no-entry"
    write(root / "references" / "orphan.md", "# Orphan\n")

    raw = scan(tmp_path)["skill/no-entry"]

    assert raw.entry is None
    # The artifact is still returned, carrying its files. Nothing is dropped for being broken.
    assert paths(raw) == ["references/orphan.md"]


def test_a_directory_holding_an_entry_document_does_not_scan_with_entry_none(
    tmp_path: Path,
) -> None:
    """Positive control for the assertion above — `entry is None` is capable of being False."""
    write_skill(tmp_path, "has-entry")

    assert scan(tmp_path)["skill/has-entry"].entry is not None


def test_a_symlinked_entry_document_is_never_followed_and_leaves_no_entry(tmp_path: Path) -> None:
    """Ruling R6 meeting V1. A symlinked `SKILL.md` is not followed, so the artifact genuinely does
    load as nothing — and the scan says both things: the skip, and the absent entry."""
    target = write(tmp_path / "elsewhere.md", "---\nname: sneaky\n---\n\nreal content\n")
    root = tmp_path / "skills" / "linked-entry"
    root.mkdir(parents=True)
    (root / "SKILL.md").symlink_to(os.path.relpath(target, root))

    raw = scan(tmp_path)["skill/linked-entry"]

    assert raw.entry is None
    assert skips(raw) == [("SKILL.md", SkipReason.SYMLINK)]
    assert raw.files == ()


# ==================================================================================================
# V6's real half — ruling R6 and charter §8, against real directory entries
# ==================================================================================================


def test_a_real_symlink_is_recorded_as_a_skipped_path(tmp_path: Path) -> None:
    """The scanner half of the T-5 mutation. `tests/domain/test_assembly.py` is explicit that it
    cannot prove this; here a real link, in a real directory, becomes a real `SkippedPath`."""
    outside = write(tmp_path / "outside" / "secret.md", "not part of any artifact\n")
    root = write_skill(tmp_path, "messy")
    link = root / "references" / "elsewhere.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(os.path.relpath(outside, link.parent))

    raw = scan(tmp_path)["skill/messy"]

    (skipped,) = raw.skipped
    assert skipped.path == "references/elsewhere.md"
    assert skipped.reason is SkipReason.SYMLINK
    assert skipped.detail is not None
    assert ".." in skipped.detail, "the raw target is reported, so an escape is visible as one"


def test_a_symlink_is_never_followed_hashed_or_taken_into_the_artifact(tmp_path: Path) -> None:
    """Ruling R6, as three separate absences — and the sibling below is their positive control.

    A link resolving outside the artifact root is how a copy writes outside its target, and
    initiative 02 writes into `~/.claude/`. The scan must therefore not merely decline to *install*
    it: the bytes must never enter `files` and never reach the hash.
    """
    outside = write(tmp_path / "outside" / "secret.md", "SECRET-CONTENT\n")
    root = write_skill(tmp_path, "messy")
    (root / "linked.md").symlink_to(os.path.relpath(outside, root))

    raw = scan(tmp_path)["skill/messy"]

    assert paths(raw) == ["SKILL.md"]
    assert "linked.md" not in paths(raw)
    from harness_library.domain.hashing import hash_bytes

    assert hash_bytes(outside.read_bytes()) not in {file.sha256 for file in raw.files}


def test_a_regular_file_in_the_same_directory_is_taken(tmp_path: Path) -> None:
    """Positive control for the three absences above: the walk does reach that directory and does
    take what it finds there, so the symlink's absence is a decision and not a walk that stopped."""
    root = write_skill(tmp_path, "messy")
    write(root / "linked.md", "an ordinary file with the same name\n")

    assert paths(scan(tmp_path)["skill/messy"]) == ["SKILL.md", "linked.md"]


@pytest.mark.parametrize(
    "filename",
    ["SKILL.md.swp", "SKILL.md.swo", "SKILL.md.swn", "SKILL.md~", ".#SKILL.md", "#SKILL.md#"],
)
def test_editor_leftovers_are_skipped_as_editor_swap(tmp_path: Path, filename: str) -> None:
    """Charter §8. Observed destroying real content when a copy took them along."""
    root = write_skill(tmp_path, "messy")
    write(root / filename, "editor leftovers\n")

    assert skips(scan(tmp_path)["skill/messy"]) == [(filename, SkipReason.EDITOR_SWAP)]


def test_a_vendor_tree_is_skipped_whole_and_never_descended(tmp_path: Path) -> None:
    """Charter §8. Descending one turns a scan of a skill into a scan of a package manager's
    output — so the assertion is not only that `node_modules` is reported, but that nothing
    *inside* it appears anywhere in the result."""
    root = write_skill(tmp_path, "messy")
    write(root / "node_modules" / "left-pad" / "index.js", "module.exports = 1;\n")

    raw = scan(tmp_path)["skill/messy"]

    assert skips(raw) == [("node_modules", SkipReason.VENDOR_TREE)]
    assert paths(raw) == ["SKILL.md"]
    assert not any("left-pad" in path for path in paths(raw) + [s[0] for s in skips(raw)])


def test_a_nested_git_directory_is_skipped_as_other(tmp_path: Path) -> None:
    """Not a vendored dependency, so not `VENDOR_TREE`. `OTHER` exists so a scanner never has to
    choose between silence and a domain change."""
    root = write_skill(tmp_path, "messy")
    write(root / ".git" / "HEAD", "ref: refs/heads/main\n")

    (skipped,) = scan(tmp_path)["skill/messy"].skipped
    assert (skipped.path, skipped.reason) == (".git", SkipReason.OTHER)
    assert skipped.detail == "a nested git directory"


def test_a_skipped_path_never_reaches_files(tmp_path: Path) -> None:
    """Charter §7 — skipped paths are excluded from `files` and therefore from the content hash."""
    root = write_skill(tmp_path, "messy")
    write(root / "SKILL.md.swp", "swap\n")
    write(root / "node_modules" / "pkg" / "index.js", "1\n")

    raw = scan(tmp_path)["skill/messy"]

    assert set(paths(raw)).isdisjoint({skipped.path for skipped in raw.skipped})


# ==================================================================================================
# Text and binary — charter §7 decides this per file
# ==================================================================================================


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"plain ascii", True),
        ("prose with an em dash — and accents ção".encode(), True),
        (b"", True),
        (b"\x89PNG\r\n\x1a\n\x00\x00", False),
        (b"text then a \x00 nul", False),
        (b"\xff\xfe invalid utf-8", False),
    ],
)
def test_is_text_is_decided_per_file(data: bytes, expected: bool) -> None:
    """A NUL byte or a failed UTF-8 decode makes a file binary. Binary is stored, hashed, exported
    and installed — never searched or diffed, which is charter §7's whole point."""
    assert is_text(data) is expected


def test_a_binary_file_is_scanned_stored_and_hashed_but_not_text(tmp_path: Path) -> None:
    root = write_skill(tmp_path, "messy")
    (root / "references").mkdir()
    (root / "references" / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")

    raw = scan(tmp_path)["skill/messy"]

    binary = next(file for file in raw.files if file.path == "references/diagram.png")
    assert binary.is_text is False
    assert binary.size == 10
    assert len(binary.sha256) == 64
    # Positive control: the sibling text file in the same scan is classified the other way, so
    # `is_text is False` is a decision about these bytes and not a constant.
    assert next(file for file in raw.files if file.path == "SKILL.md").is_text is True


# ==================================================================================================
# `FILE`-kind artifacts — the registry decides the layout, never this module
# ==================================================================================================


def test_an_agent_is_one_file_whose_path_is_its_own_basename(tmp_path: Path) -> None:
    """Contract C-1: "for a `FILE`-kind artifact the single entry's path is its own basename"."""
    write(tmp_path / "agents" / "scribe.md", "---\nname: scribe\ndescription: writes\n---\n\nX\n")

    raw = scan(tmp_path)["agent/scribe"]

    assert raw.kind is ArtifactKind.FILE
    assert raw.root_path == "agents/scribe.md"
    assert raw.entry_path == "scribe.md"
    assert paths(raw) == ["scribe.md"]
    assert raw.entry is not None
    assert raw.entry.frontmatter["description"] == "writes"


def test_a_file_in_the_agents_directory_that_is_not_a_document_is_not_an_artifact(
    tmp_path: Path,
) -> None:
    """`agents/notes.txt` is not an agent. Absence assertion; the sibling above is its control."""
    write(tmp_path / "agents" / "notes.txt", "not an agent\n")
    write(tmp_path / "agents" / "scribe.md", "---\nname: scribe\ndescription: writes\n---\n")

    assert sorted(scan(tmp_path)) == ["agent/scribe"]


# ==================================================================================================
# What the scan passes over, and what it refuses to invent
# ==================================================================================================


def test_a_symlinked_artifact_root_is_never_followed_and_is_reported(tmp_path: Path) -> None:
    """Ruling R6 at the artifact-root position, **and ruling R46's other half**.

    The open question this test carried until T-20 was what to do about the omission. It is
    answered: the root is still never followed and still produces no `RawArtifact` — emitting one
    would fire V1 against a skill that loads perfectly — but it is now *reported*, as a
    `SymlinkedRoot` the assembler turns into V11.

    Both halves are asserted, and they are two facts rather than one: the artifact set still
    holds only the real skill, and the scan says why the other one is not in it.
    """
    real = write_skill(tmp_path, "real")
    (tmp_path / "skills" / "aliased").symlink_to(real, target_is_directory=True)

    scanned = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)

    assert sorted(raw.id for raw in scanned.artifacts) == ["skill/real"]
    assert [(root.id, root.root_path) for root in scanned.symlinked_roots] == [
        ("skill/aliased", "skills/aliased")
    ]
    assert scanned.symlinked_roots[0].destination == str(real)


def test_a_symlinked_root_is_reported_even_when_it_dangles(tmp_path: Path) -> None:
    """`readlink`, never `resolve` (R6). A link whose destination is gone is still a link, still
    unscannable, and still the reason an artifact is missing — resolving it to decide would both
    follow it and turn the diagnosis into an error.

    The positive control is the destination assertion: the raw text really came back, so this is
    not passing by reporting an empty value for everything."""
    write_skill(tmp_path, "real")
    (tmp_path / "skills" / "ghost").symlink_to("../../nowhere/at/all", target_is_directory=True)

    scanned = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)

    assert [root.id for root in scanned.symlinked_roots] == ["skill/ghost"]
    assert scanned.symlinked_roots[0].destination == "../../nowhere/at/all"


def test_a_symlinked_agent_document_is_reported_as_a_root(tmp_path: Path) -> None:
    """A `FILE`-kind artifact root is a document, so a linked `agents/<name>.md` is a symlinked
    root exactly as a linked `skills/<name>/` is. Its name is the stem, which is the name the
    artifact would have had."""
    real = write(tmp_path / "elsewhere" / "scribe.md", AGENT_DOCUMENT)
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "scribe.md").symlink_to(real)

    scanned = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)

    assert scanned.artifacts == ()
    assert [(root.id, root.root_path) for root in scanned.symlinked_roots] == [
        ("agent/scribe", "agents/scribe.md")
    ]


def test_a_symlinked_non_document_in_the_agents_directory_is_not_a_root(tmp_path: Path) -> None:
    """**The control for the pair above.** Under a `FILE`-kind type only a `.md` child could ever
    have been an artifact, so a linked `agents/notes.txt` is passed over exactly as an unlinked
    one is — V11 must report a *missing artifact*, not every link in the tree.

    The second assertion is the positive control: a linked `.md` beside it *is* reported, so this
    is not passing by reporting nothing at all.
    """
    real = write(tmp_path / "elsewhere" / "notes.txt", "notes\n")
    document = write(tmp_path / "elsewhere" / "scribe.md", AGENT_DOCUMENT)
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "notes.txt").symlink_to(real)
    (tmp_path / "agents" / "scribe.md").symlink_to(document)

    scanned = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)

    assert [root.id for root in scanned.symlinked_roots] == ["agent/scribe"]


def test_a_skill_symlinked_to_another_skill_in_the_same_library_is_reported_once(
    tmp_path: Path,
) -> None:
    """**The alias case**, which nothing else in the register covers and which a reader will ask
    about: `skills/alias -> real`, where the destination is a skill this same library already
    holds.

    The two are separate answers to separate questions and neither interferes with the other.
    The real skill is scanned exactly once, under its own name, because it is reached through
    its own directory and never through the link. The alias is reported as a symlinked root like
    any other, because R6 has no special case for a destination that happens to be nearby — and
    it should not: the rule is about a root that was not read, not about where it pointed.

    Nothing is duplicated. The two artifact roots are different target paths, so no install
    writes one file twice, and the names differ so V8 has nothing to say either. What the user
    gets is the real skill installed and the alias named and skipped, which is the honest report
    of what their library actually holds.
    """
    write_skill(tmp_path, "real")
    (tmp_path / "skills" / "alias").symlink_to("real", target_is_directory=True)

    scanned = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)

    assert [raw.id for raw in scanned.artifacts] == ["skill/real"]
    assert [(root.id, root.destination) for root in scanned.symlinked_roots] == [
        ("skill/alias", "real")
    ]


def test_a_library_with_no_symlinked_root_reports_none(tmp_path: Path) -> None:
    """The floor, and the control for every assertion above: an ordinary library reports an empty
    tuple rather than something that merely looks empty."""
    write_skill(tmp_path, "real")

    assert scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS).symlinked_roots == ()


def test_a_library_with_no_type_directories_scans_to_nothing(tmp_path: Path) -> None:
    """A missing `skills/` is no skills, not a crash. Deciding a directory is not a library at all
    is the composition root's job (contract C-8) and it fails loudly there; a scanner that raised
    here could not scan a library holding only agents."""
    (tmp_path / "unrelated").mkdir()

    assert scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS) == LibraryScan()


def test_a_library_holding_only_agents_scans_normally(tmp_path: Path) -> None:
    """Positive control for the absence above."""
    write(tmp_path / "agents" / "scribe.md", "---\nname: scribe\ndescription: writes\n---\n")

    assert sorted(scan(tmp_path)) == ["agent/scribe"]


def test_an_unparseable_frontmatter_block_declares_nothing_rather_than_raising(
    tmp_path: Path,
) -> None:
    """The document exists, so `entry=None` would be a lie and V1 the wrong report; and charter §9
    forbids emitting an error code that is not in the contract, which "unparseable frontmatter" is
    not. So it is carried declaring nothing, which fires V5 for every required key. **Flagged.**"""
    write(tmp_path / "skills" / "broken-yaml" / "SKILL.md", "---\nname: [unclosed\n---\n\nBody.\n")

    raw = scan(tmp_path)["skill/broken-yaml"]

    assert raw.entry is not None
    assert dict(raw.entry.frontmatter) == {}
    assert "Body." in raw.entry.body


# ==================================================================================================
# Determinism — the precondition for every golden literal in this suite
# ==================================================================================================


def test_two_scans_of_one_library_produce_the_same_order(tmp_path: Path) -> None:
    """A report that reorders itself between two scans cannot be diffed or pinned. Children are
    sorted by name at every level, which is the same discipline V7, V8 and V9 already keep."""
    root = write_skill(tmp_path, "messy")
    for name in ("zulu.md", "alpha.md", "mike.md"):
        write(root / "references" / name, f"# {name}\n")
    write(root / "SKILL.md.swp", "swap\n")
    write(root / "node_modules" / "pkg" / "index.js", "1\n")

    first = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)
    second = scan_library(tmp_path, timestamps=FIXED_TIMESTAMPS)

    assert first == second
    assert paths(first.artifacts[0]) == [
        "SKILL.md",
        "references/alpha.md",
        "references/mike.md",
        "references/zulu.md",
    ]
    assert skips(first.artifacts[0]) == [
        ("SKILL.md.swp", SkipReason.EDITOR_SWAP),
        ("node_modules", SkipReason.VENDOR_TREE),
    ]


# ==================================================================================================
# The committed fixture library — P-4, walked as real bytes
# ==================================================================================================


def test_the_fixture_library_scans_into_the_expected_artifact_set(fixture_library: Path) -> None:
    """A golden literal. The committed tree is the regression suite for the reason this product
    exists (charter §10), so what it contains is asserted rather than counted."""
    assert sorted(scan(fixture_library)) == [
        "agent/nameless",
        "agent/scribe",
        "skill/broken-links",
        "skill/dangling-successor",
        "skill/delivery-lead",
        "skill/incomplete",
        "skill/legacy-ctg-pattern",
        "skill/legacy-orchestration",
        "skill/messy",
        "skill/misnamed",
        "skill/no-entry",
    ]


def test_the_fixture_library_reports_its_symlinked_root(fixture_library: Path) -> None:
    """A golden literal over the committed tree, the way the artifact set above is one.

    `skills/linked-skill` is a symlink to a skill kept in `tests/fixtures/outside/`. It is
    **absent from the artifact set above** — which is the fault — and present here, which is V11
    making the absence visible.
    """
    scanned = scan_library(fixture_library, timestamps=FIXED_TIMESTAMPS)

    assert [(root.id, root.root_path, root.destination) for root in scanned.symlinked_roots] == [
        ("skill/linked-skill", "skills/linked-skill", "../../outside/linked-skill")
    ]
    assert "skill/linked-skill" not in {raw.id for raw in scanned.artifacts}


def test_the_fixture_messy_skill_records_every_skip_the_charter_names(
    fixture_library: Path,
) -> None:
    """Charter §8's three named extraneous paths — a swap file, a vendor tree and a symlink — in
    one real directory, in scan order, against committed bytes."""
    raw = scan(fixture_library)["skill/messy"]

    assert skips(raw) == [
        ("SKILL.md.swp", SkipReason.EDITOR_SWAP),
        ("node_modules", SkipReason.VENDOR_TREE),
        ("references/elsewhere.md", SkipReason.SYMLINK),
    ]
    assert paths(raw) == ["SKILL.md", "references/diagram.png"]


def test_the_fixture_library_derives_a_timezone_aware_timestamp_for_every_artifact(
    fixture_library: Path,
) -> None:
    """Ruling R5's one assertion against the committed tree, and deliberately the only one.

    The fixture lives inside this repository, so it is dirty while uncommitted and clean once the
    delivery lead commits it — an `updated_at` value or an `is_dirty` flag asserted here would flip
    at the commit boundary and fail for whoever came next. R5 itself is proven in
    `test_timestamps.py`, in a repository whose commit dates the test owns.
    """
    for raw in scan_library(fixture_library).artifacts:
        assert raw.updated_at.tzinfo is not None, raw.id
