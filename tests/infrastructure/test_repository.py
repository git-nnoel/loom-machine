"""Contract C-4 against the committed fixture library. The layer where the two halves meet.

Everything above this point is provably correct against literals and provably blind to the disk.
`tests/domain/test_assembly.py` proves that a recorded `SkippedPath` becomes a V6 warning and says,
in its own docstring, that it **cannot** prove a real symlink is ever recorded as one.
`tests/infrastructure/test_scanner.py` proves the recording. This module is where the two are
composed and the whole guarantee is finally observable: a real symlink, in a real directory, read
through the repository, arriving as a V6 warning on an assembled artifact.

That is also why the T-5 mutation is aimed here. A V6 test driven from a hand-built `SkippedPath`
list proves only that the assembler works, which T-3 already proved; the superseded plan shipped V6
entirely unwired precisely because nothing tested it against a filesystem.

What this layer is blind to: how `updated_at` is derived. The fixture library sits inside this
repository, so its dirtiness flips when the delivery lead commits it; ruling R5 is proven in
`test_timestamps.py`, against repositories whose commit dates those tests own.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness_library.domain.assembly import cited_reference_paths
from harness_library.domain.errors import LibraryYamlError
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.validation import Severity, ValidationCode
from harness_library.infrastructure.repository import FilesystemArtifactRepository
from harness_library.infrastructure.scanner import scan_library
from tests.infrastructure.conftest import FIXED_TIMESTAMPS, write, write_skill


def open_library(root: Path) -> FilesystemArtifactRepository:
    """A repository with ruling R5 held still — see this module's docstring."""
    return FilesystemArtifactRepository(root, timestamps=FIXED_TIMESTAMPS)


def codes(repository: FilesystemArtifactRepository, artifact_id: str) -> list[ValidationCode]:
    artifact = repository.get(artifact_id)
    assert artifact is not None, f"{artifact_id} is missing from the scan"
    return [finding.code for finding in artifact.findings]


@pytest.fixture
def library(fixture_library: Path) -> FilesystemArtifactRepository:
    return open_library(fixture_library)


# ==================================================================================================
# Contract C-4
# ==================================================================================================


def test_the_repository_satisfies_the_artifact_repository_protocol(
    library: FilesystemArtifactRepository,
) -> None:
    """Ruling R14: the protocol stays in `domain/repository.py` and is satisfied structurally, so
    `domain/` keeps knowing nothing about who implements it."""
    repository: ArtifactRepository = library
    assert isinstance(repository, ArtifactRepository)


def test_list_all_returns_every_artifact_including_the_broken_ones(
    library: FilesystemArtifactRepository,
) -> None:
    """An artifact that is invisible because it is broken is the failure this product exists to
    close. Ruling R8: superseded artifacts are here too, never dropped, only ranked later."""
    assert sorted(artifact.id for artifact in library.list_all()) == [
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
    invalid = [artifact.id for artifact in library.list_all() if not artifact.is_valid]
    assert "skill/no-entry" in invalid, "the skill with no SKILL.md is listed, carrying its finding"


def test_get_returns_one_artifact_and_none_for_an_unknown_id(
    library: FilesystemArtifactRepository,
) -> None:
    found = library.get("skill/delivery-lead")
    assert found is not None
    assert found.path == "skills/delivery-lead"
    assert found.description == "Coordinate specialists, rule on scope, and keep the plan honest."
    assert library.get("skill/never-existed") is None


def test_list_collections_returns_declarations_in_order_with_unresolvable_members_intact(
    library: FilesystemArtifactRepository,
) -> None:
    """A member resolving to nothing is a V7 finding, not a reason to hide the collection or
    quietly edit its member list."""
    assert [(c.key, c.title, c.members) for c in library.list_collections()] == [
        (
            "delivery",
            "Delivery",
            ("skill/delivery-lead", "agent/scribe", "skill/also-never-existed"),
        ),
        ("housekeeping", "Housekeeping", ("skill/messy",)),
    ]


def test_the_snapshot_is_taken_once_and_held(library: FilesystemArtifactRepository) -> None:
    """Contract C-4's snapshot semantics. `get()` disagreeing with `list_all()` inside one CLI run
    is the failure this closes; a new repository is a new snapshot."""
    first = library.list_all()
    second = library.list_all()

    assert [a.id for a in first] == [a.id for a in second]
    assert library.get("skill/messy") is next(a for a in first if a.id == "skill/messy")


def test_the_library_metadata_reaches_the_artifacts(library: FilesystemArtifactRepository) -> None:
    """`library.yaml` exercised end to end: tags on two artifacts, supersession on three."""
    delivery_lead = library.get("skill/delivery-lead")
    assert delivery_lead is not None
    assert delivery_lead.tags == ("process", "planning")

    stub = library.get("skill/legacy-orchestration")
    assert stub is not None
    assert stub.superseded_by == "skill/delivery-lead"

    untagged = library.get("skill/misnamed")
    assert untagged is not None
    assert untagged.tags == ()


# ==================================================================================================
# The mutation target — V6 above the fake
# ==================================================================================================


def test_a_real_symlink_becomes_a_v6_warning_on_the_assembled_artifact(
    library: FilesystemArtifactRepository,
) -> None:
    """**The named assertion of the T-5 mutation check.** Stop the scanner recording skipped paths
    and this fails.

    Every part of it is real: a symlink committed into `tests/fixtures/library/`, walked off a real
    filesystem, recorded as a `SkippedPath`, and turned into a V6 WARNING by the assembler. No
    `SkippedPath` is constructed anywhere in this test — that is the whole point, and it is the gap
    that let the superseded plan ship V6 entirely unwired.
    """
    messy = library.get("skill/messy")
    assert messy is not None

    symlink_findings = [
        finding
        for finding in messy.findings
        if finding.code is ValidationCode.V6 and finding.path == "references/elsewhere.md"
    ]

    (finding,) = symlink_findings
    assert finding.severity is Severity.WARNING
    assert "symlink" in finding.message
    assert ".." in finding.message, "the escaping target is in the report, which is the diagnosis"
    assert messy.is_valid is True, "charter §8 — a V6 never blocks an install"


def test_every_extraneous_path_the_charter_names_becomes_a_v6_warning(
    library: FilesystemArtifactRepository,
) -> None:
    """Charter §8's three named cases — a swap file, a vendor tree and a symlink — as real files
    under one real artifact root, reported in scan order and none of them blocking."""
    messy = library.get("skill/messy")
    assert messy is not None

    assert [f.path for f in messy.findings if f.code is ValidationCode.V6] == [
        "SKILL.md.swp",
        "node_modules",
        "references/elsewhere.md",
    ]
    assert messy.errors == ()
    assert len(messy.warnings) == 3


def test_a_clean_artifact_in_the_same_library_produces_no_findings(
    library: FilesystemArtifactRepository,
) -> None:
    """The positive control every "this rule does not fire" assertion in this module leans on: the
    whole composed pipeline is capable of returning a clean artifact off a real disk, so an empty
    finding list elsewhere is evidence rather than a rule that never ran."""
    clean = library.get("skill/delivery-lead")
    assert clean is not None
    assert clean.findings == ()
    assert clean.is_valid is True
    assert [file.path for file in clean.files] == ["SKILL.md", "references/checklist.md"]


# ==================================================================================================
# Charter §8's register, fired against real files
# ==================================================================================================


def test_the_fixture_library_produces_exactly_these_findings(
    library: FilesystemArtifactRepository,
) -> None:
    """A golden literal over the whole committed tree. Every rule that can be decided about a real
    artifact root, decided about one — and, just as load-bearing, the artifacts where **no** rule
    fires listed with an empty set."""
    assert {artifact.id: codes(library, artifact.id) for artifact in library.list_all()} == {
        "skill/broken-links": [ValidationCode.V3, ValidationCode.V3],
        "skill/dangling-successor": [ValidationCode.V4],
        "skill/delivery-lead": [],
        "skill/incomplete": [ValidationCode.V5],
        "skill/legacy-ctg-pattern": [],
        "skill/legacy-orchestration": [],
        "skill/messy": [ValidationCode.V6, ValidationCode.V6, ValidationCode.V6],
        "skill/misnamed": [ValidationCode.V2],
        "skill/no-entry": [ValidationCode.V1],
        "agent/nameless": [ValidationCode.V5],
        "agent/scribe": [],
    }


def test_v1_fires_because_a_real_directory_really_has_no_entry_document(
    library: FilesystemArtifactRepository, fixture_library: Path
) -> None:
    """The end-to-end V1 the domain suite cannot reach. Observed twice on the real library, both
    times loading silently as nothing — and the case §4 exists to serve, which the superseded plan
    crashed on."""
    broken = library.get("skill/no-entry")
    assert broken is not None
    assert not (fixture_library / "skills" / "no-entry" / "SKILL.md").exists()

    (finding,) = broken.findings
    assert finding.code is ValidationCode.V1
    assert finding.severity is Severity.ERROR
    assert finding.path == "SKILL.md"
    assert broken.is_valid is False


def test_v3_deduplicates_a_path_the_real_body_cites_twice(
    library: FilesystemArtifactRepository,
) -> None:
    """`skills/broken-links/SKILL.md` cites `references/missing.md` twice and
    `references/also-missing.md` once, and cites `references/present.md`, which is really there."""
    artifact = library.get("skill/broken-links")
    assert artifact is not None

    assert [f.path for f in artifact.findings] == [
        "references/missing.md",
        "references/also-missing.md",
    ]


def test_v7_fires_for_a_library_yaml_id_and_a_collection_member_that_resolve_to_nothing(
    library: FilesystemArtifactRepository,
) -> None:
    """V7 and V9 are faults of the *document*, so they have no artifact to hang on. Reaching them
    is what `library_findings()` is for — additive, and not a change to contract C-4."""
    findings = library.library_findings()

    assert [f.code for f in findings] == [ValidationCode.V7, ValidationCode.V7]
    assert "skill/never-existed" in findings[0].message
    assert "skill/also-never-existed" in findings[1].message
    assert all(f.severity is Severity.ERROR for f in findings)


# ==================================================================================================
# The seven-finding redirect-stub case, against the real fixture (lesson L5)
# ==================================================================================================


def test_the_two_redirect_stubs_produce_no_v3_findings(
    library: FilesystemArtifactRepository,
) -> None:
    """Charter §8's exemption, against real committed bodies. Both stubs cite their successor's
    reference paths as prose and neither of those paths exists here — that is correct writing, not
    a broken link."""
    for stub_id in ("skill/legacy-orchestration", "skill/legacy-ctg-pattern"):
        stub = library.get(stub_id)
        assert stub is not None
        assert stub.superseded_by == "skill/delivery-lead"
        assert [f for f in stub.findings if f.code is ValidationCode.V3] == []


def test_the_two_redirect_stubs_would_produce_seven_v3_findings_without_the_exemption(
    fixture_library: Path,
) -> None:
    """Lesson L5's seven, measured off the real fixture rather than asserted as a number.

    This is the positive control for the absence above: without it, "no V3 findings" would pass
    just as happily against two stubs that cite nothing at all, and the exemption would be
    guarding nothing. Made deterministic the way L12 requires — each stub's missing-path list is a
    **golden literal** and its count is asserted separately, so seven is the sum of two pinned
    parts rather than a number that happened to come out right.
    """
    scanned = {raw.id: raw for raw in scan_library(fixture_library, timestamps=FIXED_TIMESTAMPS)}

    def missing_citations(artifact_id: str) -> list[str]:
        raw = scanned[artifact_id]
        assert raw.entry is not None, "a redirect stub has a real entry document"
        return [
            cited for cited in cited_reference_paths(raw.entry.body) if cited not in raw.file_paths
        ]

    stub_a = missing_citations("skill/legacy-orchestration")
    stub_b = missing_citations("skill/legacy-ctg-pattern")

    assert stub_a == [
        "references/palette.md",
        "references/typography.md",
        "references/components.md",
        "references/charts.md",
        "references/voice-and-tone.md",
        "references/logo-usage.md",
    ]
    assert len(stub_a) == 6, "one of these is cited twice in the body and deduplicated to one"
    assert stub_b == ["references/persistence.md"]
    assert len(stub_b) == 1
    assert len(stub_a) + len(stub_b) == 7


# ==================================================================================================
# V8 and V9 — real files, built here rather than committed. See tests/fixtures/README.md.
# ==================================================================================================


def test_two_real_directories_differing_only_by_case_are_a_v8_error(tmp_path: Path) -> None:
    """Charter §8's V8, off a real filesystem.

    Not in the committed fixture on purpose: two directories differing only by case **cannot be
    checked out on a case-insensitive filesystem at all**, so committing them would make this
    repository unusable on macOS. `tmp_path` files are real files, so the guarantee is identical.
    """
    write_skill(tmp_path, "formatter")
    write_skill(tmp_path, "Formatter")
    if not (tmp_path / "skills" / "Formatter" / "SKILL.md").exists():  # pragma: no cover
        pytest.fail("this filesystem is case-insensitive, so V8 cannot be reproduced on it")

    repository = open_library(tmp_path)

    for artifact_id, other in [
        ("skill/formatter", "skill/Formatter"),
        ("skill/Formatter", "skill/formatter"),
    ]:
        artifact = repository.get(artifact_id)
        assert artifact is not None
        (finding,) = [f for f in artifact.findings if f.code is ValidationCode.V8]
        assert other in finding.message, "a fault reported one way sends the reader hunting"
        assert artifact.is_valid is False


def test_a_single_artifact_produces_no_v8(tmp_path: Path) -> None:
    """Positive control for the assertion above — V8 is capable of not firing."""
    write_skill(tmp_path, "formatter")

    artifact = open_library(tmp_path).get("skill/formatter")
    assert artifact is not None
    assert [f for f in artifact.findings if f.code is ValidationCode.V8] == []


def test_a_real_library_yaml_declaring_a_key_twice_is_a_v9_error(tmp_path: Path) -> None:
    """V9 off a real file. Not in the committed fixture because it would put a duplicated key in
    the one `library.yaml` whose tags and collections the rest of this suite reads as a golden
    literal."""
    write_skill(tmp_path, "delivery-lead")
    write(
        tmp_path / "library.yaml",
        "artifacts:\n"
        "  skill/delivery-lead:\n"
        "    tags: [first]\n"
        "  skill/delivery-lead:\n"
        "    tags: [second]\n",
    )

    findings = open_library(tmp_path).library_findings()

    assert [f.code for f in findings] == [ValidationCode.V9]
    assert "skill/delivery-lead" in findings[0].message
    # The surviving value is the last one written — unchanged, which is why the ERROR is the answer
    # rather than a cleverer merge.
    artifact = open_library(tmp_path).get("skill/delivery-lead")
    assert artifact is not None
    assert artifact.tags == ("second",)


def test_a_library_yaml_declaring_each_key_once_produces_no_v9(tmp_path: Path) -> None:
    """Positive control for the assertion above."""
    write_skill(tmp_path, "delivery-lead")
    write(tmp_path / "library.yaml", "artifacts:\n  skill/delivery-lead:\n    tags: [only]\n")

    assert open_library(tmp_path).library_findings() == []


# ==================================================================================================
# Reading file content — bytes, text, and everything that must be refused
# ==================================================================================================


def test_read_bytes_returns_a_real_binary_file_that_is_not_valid_utf_8(
    library: FilesystemArtifactRepository, fixture_library: Path
) -> None:
    """Contract C-4: `read_bytes` alongside `read_text` is not redundancy. Initiative 02 installs
    binary files and initiative 03 exports zips, and a text-only surface forecloses both."""
    data = library.read_bytes("skill/messy", "references/diagram.png")

    assert data == (fixture_library / "skills/messy/references/diagram.png").read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")

    messy = library.get("skill/messy")
    assert messy is not None
    binary = next(f for f in messy.files if f.path == "references/diagram.png")
    assert binary.is_text is False
    assert binary.size == len(data)


def test_read_text_raises_on_that_same_binary_file(
    library: FilesystemArtifactRepository,
) -> None:
    """Charter §7 — binary is stored, hashed, exported and installed, never searched or diffed.
    Returning mojibake here would make a binary file look searchable."""
    with pytest.raises(UnicodeDecodeError):
        library.read_text("skill/messy", "references/diagram.png")


def test_read_text_returns_a_real_reference_file(
    library: FilesystemArtifactRepository,
) -> None:
    """Positive control for the two raises above."""
    assert "Dispatch checklist" in library.read_text(
        "skill/delivery-lead", "references/checklist.md"
    )


def test_read_bytes_on_a_file_kind_artifact_addresses_it_by_its_own_basename(
    library: FilesystemArtifactRepository,
) -> None:
    """A `FILE`-kind artifact *is* its entry document: the root is the file, so joining a path onto
    it would address a file inside a file."""
    assert b"name: scribe" in library.read_bytes("agent/scribe", "scribe.md")


@pytest.mark.parametrize(
    "path",
    [
        "../messy/SKILL.md",
        "references/../../misnamed/SKILL.md",
        "../../../etc/passwd",
        "/etc/passwd",
        "",
    ],
)
def test_a_path_climbing_out_of_the_artifact_root_is_refused(
    library: FilesystemArtifactRepository, path: str
) -> None:
    """Checked on the string, before anything touches the disk — so the guarantee holds on a
    machine where the escaped-to file happens not to exist, and so the refusal is a property of the
    repository rather than an accident of the filesystem underneath it."""
    with pytest.raises(ValueError, match="artifact root"):
        library.read_bytes("skill/delivery-lead", path)


def test_a_path_inside_the_artifact_root_is_not_refused(
    library: FilesystemArtifactRepository,
) -> None:
    """Positive control for the five refusals above: the same method, on the same artifact, with a
    path that stays inside, returns bytes."""
    assert library.read_bytes("skill/delivery-lead", "references/checklist.md")


def test_a_skipped_symlink_cannot_be_read_through_the_repository(
    library: FilesystemArtifactRepository,
) -> None:
    """Ruling R6 is not only about hashing. A `read_bytes` that followed the link would be the same
    escape by another door — and it is the door initiative 02 walks through when it installs."""
    with pytest.raises(FileNotFoundError):
        library.read_bytes("skill/messy", "references/elsewhere.md")


def test_reading_a_path_the_artifact_does_not_have_raises(
    library: FilesystemArtifactRepository,
) -> None:
    with pytest.raises(FileNotFoundError):
        library.read_bytes("skill/delivery-lead", "references/absent.md")


def test_reading_from_an_unknown_artifact_raises(
    library: FilesystemArtifactRepository,
) -> None:
    with pytest.raises(KeyError):
        library.read_bytes("skill/never-existed", "SKILL.md")


def test_a_file_outside_any_artifact_is_unreachable_even_when_it_exists(tmp_path: Path) -> None:
    """The traversal refusal, aimed at a target that is really there — so the raise is the guard
    speaking and not a missing file."""
    write_skill(tmp_path, "one")
    write_skill(tmp_path, "two")
    assert (tmp_path / "skills" / "two" / "SKILL.md").exists()

    with pytest.raises(ValueError, match="artifact root"):
        open_library(tmp_path).read_bytes("skill/one", "../two/SKILL.md")


def test_a_symlink_planted_after_the_scan_is_still_refused(tmp_path: Path) -> None:
    """Defence in depth. The membership check would already refuse this path; the containment and
    symlink checks are the stage that still holds if a later change loosens it."""
    outside = write(tmp_path / "outside" / "secret.md", "SECRET\n")
    root = write_skill(tmp_path, "one")
    write(root / "references" / "note.md", "# Note\n")
    repository = open_library(tmp_path)
    repository.list_all()

    (root / "references" / "note.md").unlink()
    (root / "references" / "note.md").symlink_to(os.path.relpath(outside, root / "references"))

    with pytest.raises(ValueError, match="symlink"):
        repository.read_bytes("skill/one", "references/note.md")


# ==================================================================================================
# Opening a library
# ==================================================================================================


def test_opening_a_directory_that_does_not_exist_fails_loudly(tmp_path: Path) -> None:
    """Charter §13 — resolution fails loudly on a directory that is not a library, rather than
    silently returning an empty list. The composition root (contract C-8) does the richer
    diagnosis; this is the floor beneath it."""
    with pytest.raises(FileNotFoundError):
        FilesystemArtifactRepository(tmp_path / "absent")


def test_opening_an_empty_directory_succeeds_and_lists_nothing(tmp_path: Path) -> None:
    """Positive control, and the boundary: an empty *directory* is not the same fault as an absent
    one, and a library that legitimately holds nothing is not an error."""
    assert open_library(tmp_path).list_all() == []


def test_a_malformed_library_yaml_propagates_the_taxonomy_error(tmp_path: Path) -> None:
    """`LibraryYamlError` is in the contract (charter §9), so it travels unchanged rather than
    being flattened into an empty result — which would make a typo look like "no tags"."""
    write_skill(tmp_path, "one")
    write(tmp_path / "library.yaml", "artifacts:\n  skill/one:\n   tags: [a\n")

    with pytest.raises(LibraryYamlError):
        open_library(tmp_path).list_all()


# ==================================================================================================
# Observed on the real library during T-9 acceptance
# ==================================================================================================


UNQUOTED_COLON_FRONTMATTER = (
    "name: frontend-system-pattern\n"
    "description: Use when writing frontend code. Covers every brand: the project's brand "
    "reference is the visual authority."
)
"""The exact shape found in `~/.claude/skills/frontend-system-pattern/SKILL.md`.

A plain YAML scalar containing `": "` is a `ScannerError`, so the whole block fails to parse even
though both keys are plainly present to a human reader.
"""


def test_a_colon_in_an_unquoted_description_loses_the_whole_frontmatter(tmp_path: Path) -> None:
    """Characterisation, not endorsement: this is what the software does today, and T-9 found it
    doing it to real content on the first run.

    `_parse_entry` treats any parse failure as "this document declares nothing", so a single
    unquoted `": "` inside a description silently discards `name` and `description` together. The
    user then reads *required frontmatter key 'name' is missing* about a file whose second line is
    `name:`, which is a true finding with a false diagnosis. Pinned so that a future dedicated code
    for "unparseable frontmatter" changes this test deliberately rather than by accident.
    """
    write_skill(tmp_path, "frontend-system-pattern", frontmatter=UNQUOTED_COLON_FRONTMATTER)

    repository = open_library(tmp_path)
    artifact = repository.get("skill/frontend-system-pattern")

    assert artifact is not None
    assert codes(repository, "skill/frontend-system-pattern") == [
        ValidationCode.V5,
        ValidationCode.V5,
    ]
    assert artifact.description is None
    assert dict(artifact.frontmatter) == {}


def test_quoting_the_same_description_makes_the_artifact_clean(tmp_path: Path) -> None:
    """The positive control for the test above.

    Without it, "two V5 findings" would be indistinguishable from a helper that never writes usable
    frontmatter at all. One character — the quoting — is the whole difference.
    """
    quoted = (
        "name: frontend-system-pattern\n"
        "description: \"Use when writing frontend code. Covers every brand: the project's brand "
        'reference is the visual authority."'
    )
    write_skill(tmp_path, "frontend-system-pattern", frontmatter=quoted)

    repository = open_library(tmp_path)
    artifact = repository.get("skill/frontend-system-pattern")

    assert artifact is not None
    assert artifact.findings == ()
    assert artifact.description is not None
    assert "Covers every brand:" in artifact.description
