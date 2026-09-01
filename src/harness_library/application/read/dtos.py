"""Contract C-7 — the one serialisation of a library, and every adapter renders from it.

Charter §3 puts these here rather than in `api/dtos/` because `mcp/` may not import `api/`. That
constraint is the whole reason this module exists: the CLI's `--json`, the MCP tool payloads and
initiative 03's HTTP responses are the *same* bytes, produced once. An adapter that builds its own
dict from an `Artifact` has created a second wire format that nothing will keep in step.

**These fields are frozen.** Initiative 04's SPA branches on them; a rename later is a rewrite of
finished work, not a local fix. Two consequences are load-bearing:

* **Every finding carries its machine `code`.** `message` is prose and may be reworded without
  notice. A consumer that branched on the sentence would break silently the first time someone
  improved the wording, which is precisely the failure C-3 was frozen to prevent.
* **Nullable fields are present-and-null, never omitted.** A consumer that has to distinguish
  "absent" from "null" is a consumer with two code paths where the domain has one.

Pydantic here and frozen dataclasses in `domain/` is not an inconsistency: `domain/` imports nothing
and owns the entities, this layer owns the boundary where an entity becomes a payload, and that is
exactly where charter §3 says Pydantic belongs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from harness_library.domain.artifact import Artifact, ArtifactFile, ArtifactKind
from harness_library.domain.identity import ArtifactType
from harness_library.domain.metadata import Collection
from harness_library.domain.validation import Severity, ValidationCode, ValidationFinding


class Payload(BaseModel):
    """Base of every wire model. Frozen, and closed to fields nobody declared.

    `extra="forbid"` is not defensive dressing: these models are constructed in Python by the use
    cases, so a stray keyword is a typo that would otherwise ship a silently missing field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class FindingPayload(Payload):
    """One validation finding. Contract C-3 on the wire.

    Attributes:
        code: the rule that fired, `V1` to `V9`. **This is the branchable value.**
        severity: `error` or `warning`. Ruling R13 — it comes from the register, never from a
            caller, so it cannot disagree with `code`.
        message: a human sentence. Not contract.
        path: the file the finding is about, relative to the artifact root, or null when the
            finding is about the artifact as a whole.
    """

    code: ValidationCode
    severity: Severity
    message: str
    path: str | None

    @classmethod
    def of(cls, finding: ValidationFinding) -> FindingPayload:
        return cls(
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            path=finding.path,
        )


class FilePayload(Payload):
    """One file belonging to an artifact. Contract C-1 on the wire.

    Attributes:
        path: relative to the artifact root.
        sha256: lowercase hex digest of the file's bytes.
        size: bytes.
        is_text: whether the file is searchable and diffable (charter §7).
    """

    path: str
    sha256: str
    size: int
    is_text: bool

    @classmethod
    def of(cls, file: ArtifactFile) -> FilePayload:
        return cls(path=file.path, sha256=file.sha256, size=file.size, is_text=file.is_text)


class ArtifactSummary(Payload):
    """An artifact as it appears in a listing. Contract C-2, minus the bulky parts.

    An **invalid** artifact appears here like any other, carrying its findings. Nothing in this
    model can make a broken artifact unrepresentable — a skill with no `SKILL.md` has no
    description, no frontmatter and one file fewer, and it still lists.

    Attributes:
        id: the canonical `<type>/<name>` identity.
        type: skill or agent.
        name: the on-disk name.
        kind: directory or file.
        path: the artifact root, relative to the library root.
        description: the frontmatter `description`, or null.
        tags: from `library.yaml`; empty when none are declared.
        superseded_by: the id of the artifact replacing this one, or null. Ruling R8 requires this
            on **every** payload: a consumer must always be able to see that it is looking at a
            superseded artifact, since nothing ever hides one.
        content_hash: over the artifact's files.
        updated_at: timezone-aware. Ruling R5 decides git or mtime.
        is_dirty: true when `updated_at` came from the mtime fallback rather than from git.
        is_valid: no ERROR finding. Ruling R22 — a WARNING never makes this false.
        findings: everything validation reported about this artifact.
        file_count: how many files the artifact holds.
        total_size: the sum of their sizes, in bytes. The `size` sort key reads this.
    """

    id: str
    type: ArtifactType
    name: str
    kind: ArtifactKind
    path: str
    description: str | None
    tags: tuple[str, ...]
    superseded_by: str | None
    content_hash: str
    updated_at: datetime
    is_dirty: bool
    is_valid: bool
    findings: tuple[FindingPayload, ...]
    file_count: int
    total_size: int

    @classmethod
    def of(cls, artifact: Artifact) -> ArtifactSummary:
        return cls(**_summary_fields(artifact))


class ArtifactDetail(ArtifactSummary):
    """One artifact in full — what `hl show` and the MCP `get_artifact` tool render.

    Extends the summary rather than restating it, so a field added to a listing cannot go missing
    from the detail view.

    Attributes:
        frontmatter: the parsed frontmatter mapping. Empty when the entry document is missing or
            has none — never null, because "no frontmatter" and "no entry document" are already
            distinguishable from `entry_text` and the V1 finding.
        entry_path: where the entry document lives, relative to the artifact root, whether or not
            it exists. A consumer showing "expected SKILL.md, found nothing" needs the name.
        entry_text: the entry document's text, or null when the artifact has no entry document
            (V1) or it is not decodable. Feature F-2: an invalid artifact is *shown with its
            findings*, never raised on.
        files: every file the scan kept, in scan order.
    """

    frontmatter: dict[str, Any]
    entry_path: str
    entry_text: str | None
    files: tuple[FilePayload, ...]

    @classmethod
    def of_artifact(
        cls, artifact: Artifact, *, entry_path: str, entry_text: str | None
    ) -> ArtifactDetail:
        return cls(
            **_summary_fields(artifact),
            frontmatter=dict(artifact.frontmatter),
            entry_path=entry_path,
            entry_text=entry_text,
            files=tuple(FilePayload.of(file) for file in artifact.files),
        )


class ArtifactListPayload(Payload):
    """A listing.

    Attributes:
        artifacts: in the requested order, ruling R8 applied above the sort key.
        total: how many artifacts the filter matched. Equal to `len(artifacts)` today; present
            because initiative 03 will page a listing and a pager needs a total that is not the
            length of the page.
        sort: the key the order was produced by, echoed so a client rendering a sorted table knows
            which column to mark without tracking its own request.
    """

    artifacts: tuple[ArtifactSummary, ...]
    total: int
    sort: str


class FileContent(Payload):
    """One file inside an artifact — what the MCP `get_reference` tool renders.

    It carries no parent entry text and no sibling list on purpose: F-6 requires `get_reference` to
    return one reference *without* its parent's entry text, and a payload that cannot carry the
    parent's text cannot leak it.

    Attributes:
        artifact_id: the artifact the file belongs to.
        path: the file, relative to the artifact root.
        sha256: the digest recorded by the scan.
        size: bytes.
        is_text: whether the file is text (charter §7).
        text: the decoded text, or null for a binary file. Binary content is never rendered as
            mojibake — `FILE_NOT_TEXT` is the code for asking anyway.
    """

    artifact_id: str
    path: str
    sha256: str
    size: int
    is_text: bool
    text: str | None


class SearchSkipReason(StrEnum):
    """Why a file inside a searched artifact was not searched. Closed.

    **Ruling R25 governs the wording.** The reason a file is skipped is that it is *not a markdown
    reference* — never that it is "binary". The fixture library's 184 KB HTML asset is valid UTF-8
    and is still not searched, so "binary" would be both wrong and unfalsifiable as a diagnosis.
    """

    NOT_A_MARKDOWN_REFERENCE = "not_a_markdown_reference"
    """Ruling R4: only the entry document and `.md` files under `references/` are searched.

    This is decided from the path alone, **before** anything is read, so it is the reason every
    non-markdown file gets — the HTML asset and the PNG alike — and no file can ever be reported
    as undecodable when the real reason is that nothing would have searched it anyway.
    """

    UNREADABLE_AS_TEXT = "unreadable_as_text"
    """A file that *is* a markdown reference by path but does not decode as UTF-8.

    Reachable only after the path test has passed, which is what keeps it from becoming the
    "binary" reason R25 rejects. A scan marking a `.md` file as text that later fails to decode is
    a torn read (charter §7); reporting it is how the omission stays visible.
    """


class SkippedFile(Payload):
    """One file a search passed over, reported so the omission is visible rather than silent.

    Ruling R4 requires every skipped file to be reported. A search that quietly declines to look
    inside half a library and says nothing is the failure this product exists to eliminate.

    Attributes:
        artifact_id: the artifact holding the file.
        path: the file, relative to the artifact root.
        reason: the closed reason code. Consumers branch on this.
        message: the human sentence. Not contract.
    """

    artifact_id: str
    path: str
    reason: SearchSkipReason
    message: str


class SearchMatch(Payload):
    """One line matching the query.

    Attributes:
        artifact_id: the artifact the match is in.
        path: the file, relative to the artifact root.
        line_number: 1-based, matching what an editor shows.
        line_text: the whole matching line, with trailing whitespace stripped. This is the context
            feature F-3 asks for; it is the line and not a byte window so that a consumer can show
            it without re-reading the file.
    """

    artifact_id: str
    path: str
    line_number: int
    line_text: str


class SearchResults(Payload):
    """What a search returns. Contract C-5.

    Attributes:
        query: echoed, so a client rendering results out of band knows what produced them.
        matches: in library order, capped at `limit`.
        truncated: **true when the cap was reached and matching stopped.** A caller that ignores
            this reports a partial answer as a complete one.
        limit: the cap in force for this search.
        skipped: every file inside a searched artifact that was not searched, with its reason.
    """

    query: str
    matches: tuple[SearchMatch, ...]
    truncated: bool
    limit: int
    skipped: tuple[SkippedFile, ...]


class ArtifactValidation(Payload):
    """One artifact's validation verdict, for the report.

    Deliberately lighter than `ArtifactSummary`: a validation report is about faults, and a caller
    that also wants the artifact's metadata already has `list_artifacts`.

    Attributes:
        id: the artifact.
        path: its root, relative to the library root, so a report can be read as a file list.
        is_valid: no ERROR finding (ruling R22).
        findings: every finding on this artifact, warnings included.
    """

    id: str
    path: str
    is_valid: bool
    findings: tuple[FindingPayload, ...]


class ValidationReport(Payload):
    """The whole library's verdict. Contract C-5.

    Attributes:
        is_valid: true when **no** ERROR finding exists anywhere — on an artifact or on the library
            itself. Ruling R22: a WARNING never makes this false, and V6 alone never blocks.
        artifact_count: how many artifacts were checked, including the clean ones.
        error_count: ERROR findings across artifacts and the library.
        warning_count: WARNING findings across artifacts and the library.
        artifacts: **only the artifacts carrying at least one finding**, in library order. A clean
            artifact is absent, which is what makes "this rule does not fire on a clean artifact"
            an assertion a test can make.
        library_findings: V7 and V9 — faults of the `library.yaml` document itself, which have no
            artifact to hang them on. Ruling R23: these two rules are reachable *only* here, so a
            report that omitted them would leave two rows of charter §8 unable to fail anything.
    """

    is_valid: bool
    artifact_count: int
    error_count: int
    warning_count: int
    artifacts: tuple[ArtifactValidation, ...]
    library_findings: tuple[FindingPayload, ...]


class CollectionSummary(Payload):
    """A collection as it appears in a listing.

    Attributes:
        key: the identifier `hl list --collection` takes.
        title: a human name, or null.
        description: prose, or null.
        member_ids: the declared member ids, in declaration order, **including ones that resolve
            to nothing**. The declaration is what the document says; V7 is what is wrong with it.
        member_count: how many ids are declared.
    """

    key: str
    title: str | None
    description: str | None
    member_ids: tuple[str, ...]
    member_count: int

    @classmethod
    def of(cls, collection: Collection) -> CollectionSummary:
        return cls(
            key=collection.key,
            title=collection.title,
            description=collection.description,
            member_ids=collection.members,
            member_count=len(collection.members),
        )


class CollectionDetail(Payload):
    """One collection with its members resolved.

    Attributes:
        key: the collection.
        title: a human name, or null.
        description: prose, or null.
        members: the members that resolve, as summaries, in declaration order.
        unresolved_member_ids: the declared ids that resolve to nothing, in declaration order.
            Each is also a V7 ERROR in the validation report; it is repeated here because a caller
            showing one collection should not have to validate the whole library to discover that
            a third of it is missing.
    """

    key: str
    title: str | None
    description: str | None
    members: tuple[ArtifactSummary, ...]
    unresolved_member_ids: tuple[str, ...]


class CollectionListPayload(Payload):
    """Every collection the library declares, in declaration order.

    Attributes:
        collections: the summaries.
        total: how many there are.
    """

    collections: tuple[CollectionSummary, ...]
    total: int


def _summary_fields(artifact: Artifact) -> dict[str, Any]:
    """The summary half of an artifact, as keyword arguments.

    One function so `ArtifactDetail` cannot drift from `ArtifactSummary` by forgetting a field.
    """
    return {
        "id": artifact.id,
        "type": artifact.type,
        "name": artifact.name,
        "kind": artifact.kind,
        "path": artifact.path,
        "description": artifact.description,
        "tags": artifact.tags,
        "superseded_by": artifact.superseded_by,
        "content_hash": artifact.content_hash,
        "updated_at": artifact.updated_at,
        "is_dirty": artifact.is_dirty,
        "is_valid": artifact.is_valid,
        "findings": tuple(FindingPayload.of(finding) for finding in artifact.findings),
        "file_count": len(artifact.files),
        "total_size": sum(file.size for file in artifact.files),
    }


__all__ = [
    "ArtifactDetail",
    "ArtifactListPayload",
    "ArtifactSummary",
    "ArtifactValidation",
    "CollectionDetail",
    "CollectionListPayload",
    "CollectionSummary",
    "FileContent",
    "FilePayload",
    "FindingPayload",
    "Payload",
    "SearchMatch",
    "SearchResults",
    "SearchSkipReason",
    "SkippedFile",
    "ValidationReport",
]
