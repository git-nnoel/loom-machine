"""Contract C-7 — the wire shape, pinned.

These are the least interesting tests in the suite and the most expensive ones to be missing.
Initiative 03 serves these payloads over HTTP and initiative 04's SPA branches on their fields, so
a renamed field is a rewrite of finished work rather than a local fix. The field sets below are
**golden literals**: a rename, an addition or a removal fails here, in the layer that owns the
contract, instead of failing months later in a frontend nobody has opened yet.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from harness_library.application.read import (
    ArtifactDetail,
    ArtifactListPayload,
    ArtifactSummary,
    ArtifactValidation,
    CollectionDetail,
    CollectionListPayload,
    CollectionSummary,
    FileContent,
    FilePayload,
    FindingPayload,
    SearchMatch,
    SearchResults,
    SkippedFile,
    ValidationReport,
    get_artifact,
    list_artifacts,
    validate_library,
)
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.validation import ValidationCode
from tests.application.fakes import FakeArtifactRepository, finding, make_artifact, skill_with_entry

EXPECTED_FIELDS: dict[type[BaseModel], list[str]] = {
    FindingPayload: ["code", "severity", "message", "path"],
    FilePayload: ["path", "sha256", "size", "is_text"],
    ArtifactSummary: [
        "id",
        "type",
        "name",
        "kind",
        "path",
        "description",
        "tags",
        "superseded_by",
        "content_hash",
        "updated_at",
        "is_dirty",
        "is_valid",
        "findings",
        "file_count",
        "total_size",
    ],
    ArtifactDetail: [
        "id",
        "type",
        "name",
        "kind",
        "path",
        "description",
        "tags",
        "superseded_by",
        "content_hash",
        "updated_at",
        "is_dirty",
        "is_valid",
        "findings",
        "file_count",
        "total_size",
        "frontmatter",
        "entry_path",
        "entry_text",
        "files",
    ],
    ArtifactListPayload: ["artifacts", "total", "sort"],
    FileContent: ["artifact_id", "path", "sha256", "size", "is_text", "text"],
    SearchMatch: [
        "artifact_id",
        "path",
        "line_number",
        "line_text",
        "line_before",
        "line_after",
    ],
    SkippedFile: ["artifact_id", "path", "reason", "message"],
    SearchResults: ["query", "matches", "truncated", "limit", "skipped"],
    ArtifactValidation: ["id", "path", "is_valid", "findings"],
    ValidationReport: [
        "is_valid",
        "artifact_count",
        "error_count",
        "warning_count",
        "artifacts",
        "library_findings",
    ],
    CollectionSummary: ["key", "title", "description", "member_ids", "member_count"],
    CollectionDetail: ["key", "title", "description", "members", "unresolved_member_ids"],
    CollectionListPayload: ["collections", "total"],
}


def test_every_payload_field_set_is_what_initiatives_03_and_04_were_promised() -> None:
    """The freeze, as one assertion. Changing a field here is a plan-level decision."""
    actual = {model: list(model.model_fields) for model in EXPECTED_FIELDS}

    assert actual == EXPECTED_FIELDS


def test_a_finding_serialises_its_machine_code_and_not_only_its_sentence() -> None:
    """The one field initiative 04 branches on. A human message would let a rename pass silently."""
    payload = FindingPayload.of(finding(ValidationCode.V3, "cites references/gone.md", "SKILL.md"))

    assert json.loads(payload.model_dump_json()) == {
        "code": "V3",
        "severity": "error",
        "message": "cites references/gone.md",
        "path": "SKILL.md",
    }


def test_a_null_field_is_present_and_null_rather_than_omitted() -> None:
    """A consumer that had to distinguish "absent" from "null" would need two code paths."""
    payload = FindingPayload.of(finding(ValidationCode.V1, "no SKILL.md"))

    assert json.loads(payload.model_dump_json())["path"] is None


def test_enums_serialise_as_their_wire_strings() -> None:
    artifact, contents = skill_with_entry("delivery-lead", tags=("process",))
    repository = FakeArtifactRepository([artifact], contents=contents)

    summary = json.loads(list_artifacts(repository).artifacts[0].model_dump_json())

    assert (summary["type"], summary["kind"]) == ("skill", "directory")
    assert summary["id"] == "skill/delivery-lead"


def test_the_whole_listing_round_trips_through_json() -> None:
    """The CLI's `--json`, the MCP payload and initiative 03's response are these bytes."""
    artifact = make_artifact("broken", findings=(finding(ValidationCode.V1, "no SKILL.md"),))
    repository = FakeArtifactRepository([artifact])

    document = json.loads(list_artifacts(repository).model_dump_json())

    assert document["total"] == 1
    assert document["sort"] == "name"
    assert document["artifacts"][0]["findings"][0]["code"] == "V1"


def test_a_validation_report_round_trips_through_json() -> None:
    repository = FakeArtifactRepository(
        [make_artifact("alpha")], library_findings=[finding(ValidationCode.V7, "ghost")]
    )

    document = json.loads(validate_library(repository).model_dump_json())

    assert document["is_valid"] is False
    assert document["library_findings"][0]["code"] == "V7"


def test_a_detail_payload_carries_every_summary_field() -> None:
    """`ArtifactDetail` extends the summary, so a field added to a listing cannot go missing."""
    artifact, contents = skill_with_entry("delivery-lead")
    repository = FakeArtifactRepository([artifact], contents=contents)

    detail = get_artifact(repository, "skill/delivery-lead")

    assert set(ArtifactSummary.model_fields) <= set(type(detail).model_fields)
    assert detail.total_size == artifact.files[0].size


def test_payloads_are_frozen() -> None:
    """A payload an adapter can mutate is a payload two adapters can disagree about."""
    payload = FindingPayload.of(finding(ValidationCode.V1))

    try:
        payload.message = "reworded"
    except Exception as error:
        assert "frozen" in str(error).lower()
    else:  # pragma: no cover - reached only if the models stop being frozen
        raise AssertionError("FindingPayload accepted a mutation")


def test_a_search_match_reports_a_file_edge_as_null_and_a_blank_line_as_empty() -> None:
    """Ruling R36's whole point, on the wire. `None` and `""` are different answers, and both are
    *present*: a consumer that had to tell "absent" from "null" would need two code paths where
    the domain has one (this module's docstring), and one that saw `""` for a file edge would
    render a blank line where there is no line at all.
    """
    edge = SearchMatch(
        artifact_id="skill/one",
        path="SKILL.md",
        line_number=1,
        line_text="the only line",
        line_before=None,
        line_after=None,
    )
    blank = edge.model_copy(update={"line_before": "", "line_after": ""})

    assert json.loads(edge.model_dump_json()) == {
        "artifact_id": "skill/one",
        "path": "SKILL.md",
        "line_number": 1,
        "line_text": "the only line",
        "line_before": None,
        "line_after": None,
    }
    assert json.loads(blank.model_dump_json())["line_before"] == ""
    assert json.loads(blank.model_dump_json())["line_after"] == ""


def test_the_fake_satisfies_contract_c_4() -> None:
    """Substitutability by construction: what the use cases are tested against is the protocol
    the real repository implements, `library_findings()` included (ruling R23)."""
    repository: ArtifactRepository = FakeArtifactRepository([])

    assert isinstance(repository, ArtifactRepository)
