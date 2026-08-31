"""Charter §8's register, rule by rule. Every case is driven from a `RawArtifact` literal.

Nothing here touches a disk — that is the point of T-3. What this layer is blind to is stated once,
here, so no later task mistakes a green run for proof of it: these tests cannot prove that the
scanner *records* a symlink as skipped, only that a recorded skip becomes a V6 warning. Plan §9 puts
that mutation at the repository level (T-5) for exactly that reason.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from harness_library.domain.artifact import Artifact, ArtifactFile
from harness_library.domain.assembly import (
    assemble_artifact,
    assemble_library,
    cited_reference_paths,
)
from harness_library.domain.hashing import content_hash_of_files, hash_bytes
from harness_library.domain.identity import ArtifactType
from harness_library.domain.metadata import (
    ArtifactMetadata,
    Collection,
    LibraryMetadata,
)
from harness_library.domain.raw import RawArtifact, RawEntry, SkippedPath, SkipReason
from harness_library.domain.validation import Severity, ValidationCode

SCANNED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
NO_METADATA = LibraryMetadata.empty()


def artifact_file(path: str, content: bytes = b"x", *, is_text: bool = True) -> ArtifactFile:
    return ArtifactFile(path=path, sha256=hash_bytes(content), size=len(content), is_text=is_text)


def raw_skill(
    name: str,
    *,
    body: str = "prose",
    frontmatter: dict[str, object] | None = None,
    extra_files: tuple[ArtifactFile, ...] = (),
    skipped: tuple[SkippedPath, ...] = (),
    has_entry: bool = True,
) -> RawArtifact:
    """A scanned skill root. Defaults are a *valid* artifact, so each test perturbs one thing."""
    resolved: dict[str, object] = {"name": name, "description": f"what {name} does"}
    resolved.update(frontmatter or {})
    return RawArtifact(
        type=ArtifactType.SKILL,
        name=name,
        updated_at=SCANNED_AT,
        files=((artifact_file("SKILL.md"),) if has_entry else ()) + extra_files,
        skipped=skipped,
        entry=RawEntry(frontmatter=resolved, body=body) if has_entry else None,
    )


def codes(artifact: Artifact) -> list[ValidationCode]:
    return [finding.code for finding in artifact.findings]


def findings_for(artifact: Artifact, code: ValidationCode) -> list[str | None]:
    return [finding.path for finding in artifact.findings if finding.code is code]


# ==============================================================================================
# The baseline the perturbations are measured against
# ==============================================================================================


def test_a_well_formed_skill_produces_no_findings() -> None:
    """The positive control every 'this rule does not fire' assertion below leans on: the assembler
    is capable of returning a clean artifact, so an empty finding list elsewhere is evidence rather
    than a rule that never ran."""
    assembled = assemble_artifact(raw_skill("delivery-lead"), NO_METADATA)

    assert assembled.findings == ()
    assert assembled.is_valid is True
    assert assembled.id == "skill/delivery-lead"
    assert assembled.path == "skills/delivery-lead"
    assert assembled.description == "what delivery-lead does"


def test_the_artifact_carries_what_library_yaml_declares() -> None:
    metadata = LibraryMetadata(
        artifacts={"skill/delivery-lead": ArtifactMetadata(tags=("process", "planning"))}
    )

    assembled = assemble_artifact(raw_skill("delivery-lead"), metadata)

    assert assembled.tags == ("process", "planning")


def test_the_content_hash_covers_the_scanned_files() -> None:
    raw = raw_skill("delivery-lead", extra_files=(artifact_file("references/one.md", b"one"),))

    assert assemble_artifact(raw, NO_METADATA).content_hash == content_hash_of_files(raw.files)


# ==============================================================================================
# V1 — a skill directory with no SKILL.md
# ==============================================================================================


def test_a_skill_with_no_entry_document_is_a_v1_error() -> None:
    """Observed twice on the real library; both directories loaded silently as nothing."""
    assembled = assemble_artifact(raw_skill("ghost", has_entry=False), NO_METADATA)

    assert findings_for(assembled, ValidationCode.V1) == ["SKILL.md"]
    assert assembled.is_valid is False


def test_an_agent_with_no_entry_document_is_also_a_v1_error() -> None:
    """The rule is stated against the type registry, not against the string `SKILL.md`."""
    raw = RawArtifact(type=ArtifactType.AGENT, name="reviewer", updated_at=SCANNED_AT)

    assembled = assemble_artifact(raw, NO_METADATA)

    assert findings_for(assembled, ValidationCode.V1) == ["reviewer.md"]


def test_a_missing_entry_document_does_not_also_report_every_required_key() -> None:
    """Absence assertion: V1 suppresses V5, so one fault reads as one fault.

    Positive control in the same test — the identical artifact *with* an entry that omits the same
    keys does report V5, which proves the suppression is a decision and not a rule that never runs.
    """
    silent = assemble_artifact(raw_skill("ghost", has_entry=False), NO_METADATA)
    assert ValidationCode.V5 not in codes(silent)

    present = assemble_artifact(
        raw_skill("ghost", frontmatter={"name": None, "description": None}), NO_METADATA
    )
    assert ValidationCode.V5 in codes(present), "positive control: V5 must be able to fire"


# ==============================================================================================
# V2 — frontmatter name disagreeing with the directory name
# ==============================================================================================


def test_a_frontmatter_name_disagreeing_with_the_directory_is_a_v2_error() -> None:
    """The failure this closes: a skill documenting another skill's identity, so the harness loads
    one name and the library reports another."""
    assembled = assemble_artifact(
        raw_skill("delivery-lead", frontmatter={"name": "developers-orchestration"}), NO_METADATA
    )

    assert findings_for(assembled, ValidationCode.V2) == ["SKILL.md"]


def test_names_differing_only_by_case_disagree() -> None:
    """Charter §7 — compared case-sensitively, because the install target's filesystem may disagree
    with this one about whether the two are the same path."""
    assembled = assemble_artifact(
        raw_skill("delivery-lead", frontmatter={"name": "Delivery-Lead"}), NO_METADATA
    )

    assert ValidationCode.V2 in codes(assembled)


def test_a_missing_name_key_is_v5_alone_and_not_also_a_v2_disagreement() -> None:
    """Absence assertion with its positive control: an omitted key is one fault, not two.

    The sibling assertion proves V2 is live for this artifact shape — remove the suppression and
    the first assertion fails while the second still passes.
    """
    omitted = assemble_artifact(raw_skill("delivery-lead", frontmatter={"name": ""}), NO_METADATA)
    assert ValidationCode.V5 in codes(omitted)
    assert ValidationCode.V2 not in codes(omitted)

    wrong = assemble_artifact(
        raw_skill("delivery-lead", frontmatter={"name": "other"}), NO_METADATA
    )
    assert ValidationCode.V2 in codes(wrong), "positive control: V2 must be able to fire"


# ==============================================================================================
# V3 — a cited references/… path that does not exist
# ==============================================================================================

LIVE_BODY = "Read `references/persistence.md` before touching a query."


def test_a_missing_reference_on_a_live_artifact_is_a_v3_error() -> None:
    """Named in advance as the assertion that must STAY GREEN under the T-3 mutation.

    If removing the `superseded_by` exemption turns this red as well, the exemption was implemented
    as 'skip V3 entirely' for the wrong set of artifacts.
    """
    assembled = assemble_artifact(raw_skill("backend-charter", body=LIVE_BODY), NO_METADATA)

    assert findings_for(assembled, ValidationCode.V3) == ["references/persistence.md"]
    assert assembled.is_valid is False


def test_a_reference_that_exists_is_not_a_finding() -> None:
    raw = raw_skill(
        "backend-charter",
        body=LIVE_BODY,
        extra_files=(artifact_file("references/persistence.md", b"# persistence"),),
    )

    assembled = assemble_artifact(raw, NO_METADATA)

    assert ValidationCode.V3 not in codes(assembled)
    assert raw.file_paths == {"SKILL.md", "references/persistence.md"}


def test_a_path_cited_twice_is_reported_once() -> None:
    body = "See references/testing.md. Always references/testing.md."

    assembled = assemble_artifact(raw_skill("backend-charter", body=body), NO_METADATA)

    assert findings_for(assembled, ValidationCode.V3) == ["references/testing.md"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("[the guide](references/testing.md)", ("references/testing.md",)),
        ("`references/testing.md`", ("references/testing.md",)),
        ("see references/testing.md.", ("references/testing.md",)),
        ("references/nested/deep-file.md,", ("references/nested/deep-file.md",)),
        ("no citation here", ()),
    ],
)
def test_citation_extraction_is_pinned(body: str, expected: tuple[str, ...]) -> None:
    """Golden literals rather than a computed comparison (L12): a rule about *which* text is a
    citation is invisible to a test that recomputes the same extraction on both sides."""
    assert cited_reference_paths(body) == expected


# ----------------------------------------------------------------------------------------------
# V3's exemption — the redirect stubs (L5)
# ----------------------------------------------------------------------------------------------

STUB_A_NAME = "developers-orchestration"
STUB_A_SUCCESSOR = "delivery-lead"
STUB_A_BODY = """
Renamed to delivery-lead — do not use this entry.

The successor's topic references are, in order:
`references/persistence.md`, `references/schema-evolution.md`, `references/concurrency.md`,
`references/contracts.md`, `references/ai-integration.md` and `references/observability.md`.
Read `references/persistence.md` first; it is cited twice in this stub on purpose.
"""
STUB_A_CITATIONS = (
    "references/persistence.md",
    "references/schema-evolution.md",
    "references/concurrency.md",
    "references/contracts.md",
    "references/ai-integration.md",
    "references/observability.md",
)

STUB_B_NAME = "frontend-ctg-system-pattern"
STUB_B_SUCCESSOR = "frontend-system-pattern"
STUB_B_BODY = """
Superseded by frontend-system-pattern, which now carries the CTG brand as a reference at
references/ctg-brand.md; this entry only redirects there.
"""
STUB_B_CITATIONS = ("references/ctg-brand.md",)

STUB_METADATA = LibraryMetadata(
    artifacts={
        f"skill/{STUB_A_NAME}": ArtifactMetadata(superseded_by=f"skill/{STUB_A_SUCCESSOR}"),
        f"skill/{STUB_B_NAME}": ArtifactMetadata(superseded_by=f"skill/{STUB_B_SUCCESSOR}"),
    }
)


def stub_library() -> tuple[RawArtifact, ...]:
    """The two redirect stubs and the two successors they point at — the real library's shape.

    The successors exist so that V4 stays silent and the run isolates V3.
    """
    return (
        raw_skill(STUB_A_NAME, body=STUB_A_BODY),
        raw_skill(STUB_B_NAME, body=STUB_B_BODY),
        raw_skill(STUB_A_SUCCESSOR),
        raw_skill(STUB_B_SUCCESSOR),
        raw_skill("backend-charter", body=LIVE_BODY),
    )


def test_redirect_stubs_produce_seven_v3_findings_without_the_exemption() -> None:
    """Named in advance as the assertion that MUST FAIL under the T-3 mutation, with seven findings.

    Seven is not asserted as a magic number: each stub's citation list is pinned as a golden
    literal and its size asserted separately (six and one), and the total is the sum of the two
    pinned parts. Stub A repeats one path so that deduplication cannot inflate the count into
    agreeing by accident.

    Charter §8 exempts an artifact with `superseded_by` set, because a redirect stub's body is prose
    about its successor — including that successor's reference paths. Every one of these seven
    citations is correct prose, not a broken link (L5). Do not debug the regex.
    """
    assert cited_reference_paths(STUB_A_BODY) == STUB_A_CITATIONS
    assert cited_reference_paths(STUB_B_BODY) == STUB_B_CITATIONS
    assert len(STUB_A_CITATIONS) == 6
    assert len(STUB_B_CITATIONS) == 1
    would_fire = len(STUB_A_CITATIONS) + len(STUB_B_CITATIONS)
    assert would_fire == 7

    library = assemble_library(stub_library(), STUB_METADATA)
    stubs = [library.by_id[f"skill/{name}"] for name in (STUB_A_NAME, STUB_B_NAME)]

    for stub, cited in zip(stubs, (STUB_A_CITATIONS, STUB_B_CITATIONS), strict=True):
        assert stub.superseded_by is not None, "the exemption's precondition must actually hold"
        held = {file.path for file in stub.files}
        assert set(cited).isdisjoint(held), (
            "positive control: none of the cited paths may exist, or there is nothing to exempt"
        )

    unexempted = [finding.path for stub in stubs for finding in stub.errors]
    assert unexempted == [], (
        f"the two redirect stubs would report {would_fire} V3 findings without charter §8's "
        "superseded_by exemption"
    )

    live = library.by_id["skill/backend-charter"]
    assert findings_for(live, ValidationCode.V3) == ["references/persistence.md"], (
        "positive control: V3 ran in this very assembly and fired on the non-superseded artifact"
    )


def test_the_exemption_also_applies_when_only_the_frontmatter_declares_a_successor() -> None:
    """A library with no `library.yaml` still has redirect stubs. Without this the exemption would
    miss exactly the case charter §8 carves out."""
    raw = raw_skill(
        STUB_A_NAME, body=STUB_A_BODY, frontmatter={"superseded_by": f"skill/{STUB_A_SUCCESSOR}"}
    )

    assembled = assemble_artifact(raw, NO_METADATA)

    assert assembled.superseded_by == f"skill/{STUB_A_SUCCESSOR}"
    assert ValidationCode.V3 not in codes(assembled)


def test_library_yaml_outranks_the_frontmatter_for_supersession() -> None:
    raw = raw_skill(STUB_A_NAME, frontmatter={"superseded_by": "skill/stale"})

    assembled = assemble_artifact(raw, STUB_METADATA)

    assert assembled.superseded_by == f"skill/{STUB_A_SUCCESSOR}"


# ==============================================================================================
# V4 — superseded_by that does not resolve
# ==============================================================================================


def test_a_successor_that_is_not_in_the_library_is_a_v4_error() -> None:
    metadata = LibraryMetadata(
        artifacts={"skill/old": ArtifactMetadata(superseded_by="skill/never-written")}
    )

    library = assemble_library([raw_skill("old")], metadata)

    assert findings_for(library.by_id["skill/old"], ValidationCode.V4) == [None]


def test_a_successor_that_is_in_the_library_is_not_a_finding() -> None:
    metadata = LibraryMetadata(artifacts={"skill/old": ArtifactMetadata(superseded_by="skill/new")})

    library = assemble_library([raw_skill("old"), raw_skill("new")], metadata)

    assert ValidationCode.V4 not in codes(library.by_id["skill/old"])
    assert library.by_id["skill/old"].superseded_by == "skill/new"


def test_a_superseded_artifact_is_never_dropped_from_the_library() -> None:
    """Ruling R8 — superseded artifacts stay visible; they are only ranked. A dangling successor
    adds a finding and still removes nothing."""
    metadata = LibraryMetadata(
        artifacts={"skill/old": ArtifactMetadata(superseded_by="skill/never-written")}
    )

    library = assemble_library([raw_skill("old"), raw_skill("new")], metadata)

    assert [artifact.id for artifact in library.artifacts] == ["skill/old", "skill/new"]


# ==============================================================================================
# V5 — missing or empty required frontmatter key
# ==============================================================================================


@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_a_required_key_that_says_nothing_is_a_v5_error(value: object) -> None:
    """Charter §8 says *missing or empty*: a key that is present and blank is the same fault as a
    key that is absent."""
    assembled = assemble_artifact(
        raw_skill("delivery-lead", frontmatter={"description": value}), NO_METADATA
    )

    assert findings_for(assembled, ValidationCode.V5) == ["SKILL.md"]


def test_every_required_key_is_reported_in_registry_order() -> None:
    raw = RawArtifact(
        type=ArtifactType.SKILL,
        name="delivery-lead",
        updated_at=SCANNED_AT,
        files=(artifact_file("SKILL.md"),),
        entry=RawEntry(frontmatter={}),
    )

    assembled = assemble_artifact(raw, NO_METADATA)

    assert [f.message for f in assembled.findings if f.code is ValidationCode.V5] == [
        "required frontmatter key 'name' is missing",
        "required frontmatter key 'description' is missing",
    ]


def test_a_non_string_required_value_is_present_enough_for_v5() -> None:
    """V5 asks whether the key says anything, not whether it says the right kind of thing."""
    assembled = assemble_artifact(
        raw_skill("delivery-lead", frontmatter={"description": 42}), NO_METADATA
    )

    assert ValidationCode.V5 not in codes(assembled)


# ==============================================================================================
# V6 — an extraneous path under the artifact root
# ==============================================================================================


def test_a_symlink_is_reported_as_a_v6_warning_and_never_blocks() -> None:
    """Ruling R6. The assembler is handed the skip; it never discovers one — no filesystem is
    reachable from this layer, which is what makes that guarantee structural rather than a promise.
    """
    raw = raw_skill(
        "delivery-lead",
        skipped=(
            SkippedPath("references/elsewhere.md", SkipReason.SYMLINK, detail="-> /etc/passwd"),
        ),
    )

    assembled = assemble_artifact(raw, NO_METADATA)

    (finding,) = assembled.findings
    assert finding.code is ValidationCode.V6
    assert finding.severity is Severity.WARNING
    assert finding.path == "references/elsewhere.md"
    assert "/etc/passwd" in finding.message
    assert assembled.is_valid is True


def test_every_skipped_path_is_reported_in_scan_order() -> None:
    raw = raw_skill(
        "delivery-lead",
        skipped=(
            SkippedPath("SKILL.md.swp", SkipReason.EDITOR_SWAP),
            SkippedPath("node_modules", SkipReason.VENDOR_TREE),
            SkippedPath("socket", SkipReason.OTHER),
        ),
    )

    assembled = assemble_artifact(raw, NO_METADATA)

    assert findings_for(assembled, ValidationCode.V6) == [
        "SKILL.md.swp",
        "node_modules",
        "socket",
    ]


def test_a_skipped_path_is_not_part_of_the_artifact() -> None:
    """Charter §7 — skipped paths are excluded from the hash and from `files`. Absence assertion;
    the sibling below is its positive control."""
    skipped = SkippedPath("references/elsewhere.md", SkipReason.SYMLINK)

    assembled = assemble_artifact(raw_skill("delivery-lead", skipped=(skipped,)), NO_METADATA)
    assert [file.path for file in assembled.files] == ["SKILL.md"]

    taken = assemble_artifact(
        raw_skill(
            "delivery-lead", extra_files=(artifact_file("references/elsewhere.md", b"real"),)
        ),
        NO_METADATA,
    )
    assert [file.path for file in taken.files] == ["SKILL.md", "references/elsewhere.md"], (
        "positive control: a path that is *not* skipped does reach the artifact"
    )


# ==============================================================================================
# V7 — a library.yaml entry or collection member that resolves to nothing
# ==============================================================================================


def test_a_library_yaml_entry_for_no_artifact_is_a_v7_error() -> None:
    metadata = LibraryMetadata(artifacts={"skill/deleted-last-week": ArtifactMetadata()})

    library = assemble_library([raw_skill("delivery-lead")], metadata)

    assert [f.code for f in library.findings] == [ValidationCode.V7]
    assert "skill/deleted-last-week" in library.findings[0].message
    assert library.findings[0].severity is Severity.ERROR


def test_a_collection_member_that_resolves_to_nothing_is_a_v7_error() -> None:
    metadata = LibraryMetadata(
        collections=(
            Collection(key="backend", members=("skill/delivery-lead", "skill/never-written")),
        )
    )

    library = assemble_library([raw_skill("delivery-lead")], metadata)

    assert [f.code for f in library.findings] == [ValidationCode.V7]
    assert "skill/never-written" in library.findings[0].message


def test_v7_findings_belong_to_the_library_and_not_to_any_artifact() -> None:
    """There is by construction no artifact to hang them on — that is why the level exists."""
    metadata = LibraryMetadata(artifacts={"skill/never-written": ArtifactMetadata()})

    library = assemble_library([raw_skill("delivery-lead")], metadata)

    assert library.findings
    assert library.by_id["skill/delivery-lead"].findings == ()


def test_a_library_whose_declarations_all_resolve_reports_nothing() -> None:
    """Absence assertion; the two tests above are its positive controls, and the declarations here
    are deliberately non-empty so a silently ignored `library.yaml` cannot pass as green."""
    metadata = LibraryMetadata(
        artifacts={"skill/delivery-lead": ArtifactMetadata(tags=("process",))},
        collections=(Collection(key="backend", members=("skill/delivery-lead",)),),
    )

    library = assemble_library([raw_skill("delivery-lead")], metadata)

    assert metadata.artifacts and metadata.collections
    assert library.findings == ()


def test_an_empty_library_yaml_produces_no_v7_findings() -> None:
    library = assemble_library([raw_skill("delivery-lead")], NO_METADATA)

    assert library.findings == ()
    assert library.artifacts[0].tags == ()


# ==============================================================================================
# Severity is never chosen by the emitter (R13)
# ==============================================================================================


def test_every_finding_takes_its_severity_from_the_register() -> None:
    metadata = LibraryMetadata(
        artifacts={
            "skill/ghost": ArtifactMetadata(superseded_by="skill/never-written"),
            "skill/never-declared": ArtifactMetadata(),
        }
    )
    library = assemble_library(
        [
            raw_skill("ghost", has_entry=False),
            raw_skill(
                "backend-charter",
                body=LIVE_BODY,
                frontmatter={"name": "wrong", "description": ""},
                skipped=(SkippedPath("SKILL.md.swp", SkipReason.EDITOR_SWAP),),
            ),
        ],
        metadata,
    )

    emitted = {finding.code for artifact in library.artifacts for finding in artifact.findings} | {
        finding.code for finding in library.findings
    }
    assert emitted == set(ValidationCode), "every rule V1-V7 must be reachable from this layer"

    for finding in [f for a in library.artifacts for f in a.findings] + list(library.findings):
        assert finding.severity is finding.code.severity
