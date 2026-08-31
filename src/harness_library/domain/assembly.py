"""Charter §8's validation register, as pure functions. Every rule V1-V7 lives here.

This module is the reason the initiative was recut (DEC-1). The superseded plan built the repository
first and retrofitted validation into it, so two of eight tasks existed only to reopen a third. Here
the rules come *before* the repository: they are total functions over `RawArtifact` values, they
touch no filesystem, and every one of them is tested from a literal.

Each rule closes a failure observed in a real library — a skill directory that silently never
loaded, a skill documenting another skill's path, references cited into an empty directory, editor
swap files destroyed by a copy. Charter §8 is the register; this is its enforcement.

**Two levels, because two rules need more than one artifact.** `assemble_artifact` decides
everything that is a property of a single artifact root: V1, V2, V3, V5, V6. `assemble_library`
runs it over the whole scan and then answers the questions that need the set of ids that exist:
V4 (`superseded_by` resolves) and V7 (a `library.yaml` entry or a collection member resolves).
The brief singles out V7;
V4 has the identical information need, so it lives at the same level rather than in a per-artifact
function that would have to be handed the answer it is supposed to compute.

**Severity is never chosen here.** `ValidationFinding.for_code` reads it from the register (R13).

**Nothing is ever dropped** (R8). A superseded artifact, an invalid artifact and an artifact with no
entry document all come back — an artifact that is invisible because it is broken is precisely the
failure this product exists to close.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from harness_library.domain.artifact import Artifact
from harness_library.domain.hashing import content_hash_of_files
from harness_library.domain.metadata import LibraryMetadata
from harness_library.domain.raw import RawArtifact, RawEntry, SkipReason
from harness_library.domain.validation import ValidationCode, ValidationFinding

REFERENCE_DIRECTORY = "references"
"""The directory whose citations V3 checks. Charter §8 names it explicitly."""

_CITATION_PATTERN = re.compile(rf"{REFERENCE_DIRECTORY}/[A-Za-z0-9._/-]*[A-Za-z0-9_/-]")
"""A cited `references/…` path in prose.

Deliberately loose about *how* it is cited — a markdown link, a backticked path and a bare
mention in a sentence are all citations, and the real library uses all three. Deliberately strict
about the last character, so `see references/foo.md.` cites `references/foo.md` and not a path
ending in a full stop.
"""

_SKIP_REASON_PHRASES: Mapping[SkipReason, str] = {
    SkipReason.SYMLINK: "a symlink, which is never followed, hashed or installed (ruling R6)",
    SkipReason.EDITOR_SWAP: "an editor swap file",
    SkipReason.VENDOR_TREE: "a vendored dependency tree",
    SkipReason.OTHER: "not readable as artifact content",
}


@dataclass(frozen=True, slots=True)
class AssembledLibrary:
    """Every artifact the scan found, plus the findings that belong to no single artifact.

    Attributes:
        artifacts: one per input `RawArtifact`, in input order, each carrying its own findings.
            Never filtered — not by validity, not by supersession (R8).
        findings: the library-level findings. V7 only: a `library.yaml` entry or a
            `collections[].members` id that resolves to nothing is a fault of the *document*, not of
            any artifact, and there is by definition no artifact to hang it on.
    """

    artifacts: tuple[Artifact, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()

    @property
    def by_id(self) -> Mapping[str, Artifact]:
        """The artifacts keyed by `<type>/<name>`."""
        return {artifact.id: artifact for artifact in self.artifacts}


def assemble_library(raws: Iterable[RawArtifact], metadata: LibraryMetadata) -> AssembledLibrary:
    """Turn a whole scan into finished artifacts. The entry point T-5 calls.

    Runs `assemble_artifact` over every raw value, then makes the two passes that need the whole
    library in view: V4 against each artifact's own `superseded_by`, and V7 against `library.yaml`.
    """
    assembled = [assemble_artifact(raw, metadata) for raw in raws]
    known_ids = frozenset(artifact.id for artifact in assembled)
    resolved = tuple(_apply_v4(artifact, known_ids) for artifact in assembled)
    return AssembledLibrary(artifacts=resolved, findings=_check_v7(metadata, known_ids))


def assemble_artifact(raw: RawArtifact, metadata: LibraryMetadata) -> Artifact:
    """Turn one scanned root into an `Artifact` carrying its findings.

    Implements V1, V2, V3, V5 and V6 — every rule decidable without seeing the rest of the library.
    V4 needs the set of ids that exist and is applied by `assemble_library`.
    """
    declared = metadata.for_artifact(raw.id)
    superseded_by = _resolve_superseded_by(raw.entry, declared.superseded_by)

    findings: list[ValidationFinding] = []
    findings.extend(_check_v1(raw))
    findings.extend(_check_v5(raw))
    findings.extend(_check_v2(raw))
    findings.extend(_check_v3(raw, superseded_by))
    findings.extend(_check_v6(raw))

    frontmatter: Mapping[str, Any] = raw.entry.frontmatter if raw.entry else {}
    return Artifact(
        type=raw.type,
        name=raw.name,
        kind=raw.kind,
        path=raw.root_path,
        content_hash=content_hash_of_files(raw.files),
        updated_at=raw.updated_at,
        is_dirty=raw.is_dirty,
        description=_text_or_none(frontmatter.get("description")),
        frontmatter=frontmatter,
        superseded_by=superseded_by,
        tags=declared.tags,
        files=raw.files,
        findings=tuple(findings),
    )


# --------------------------------------------------------------------------------------------
# The rules
# --------------------------------------------------------------------------------------------


def _check_v1(raw: RawArtifact) -> list[ValidationFinding]:
    """V1 — the entry document is absent.

    Charter §8 states this as "a skill directory with no `SKILL.md`". It is implemented against the
    type registry rather than against that filename, so the rule stays total when a type is added:
    every artifact type has an entry document, and an artifact without one loads as nothing. This
    was observed twice on the real library, both times silently.
    """
    if raw.entry is not None:
        return []
    return [
        ValidationFinding.for_code(
            ValidationCode.V1,
            f"no {raw.entry_path} under {raw.root_path}: the artifact loads as nothing",
            raw.entry_path,
        )
    ]


def _check_v2(raw: RawArtifact) -> list[ValidationFinding]:
    """V2 — frontmatter `name` disagrees with the on-disk name.

    Silent when `name` is missing or empty: that is V5's fault, and reporting one omission as both a
    missing key and a disagreement makes the report read as two faults. Compared case-sensitively,
    charter §7 — the install target's filesystem may disagree with this one about whether two names
    are the same path.
    """
    if raw.entry is None:
        return []
    declared = _text_or_none(raw.entry.frontmatter.get("name"))
    if declared is None or declared == raw.name:
        return []
    return [
        ValidationFinding.for_code(
            ValidationCode.V2,
            f"frontmatter name {declared!r} disagrees with the directory name {raw.name!r}",
            raw.entry_path,
        )
    ]


def _check_v3(raw: RawArtifact, superseded_by: str | None) -> list[ValidationFinding]:
    """V3 — the entry body cites a `references/…` path that the artifact does not contain.

    **Exempt while `superseded_by` is set** (charter §8, L5). A redirect stub's whole body is prose
    about its successor, including that successor's reference paths; on the real library the two
    stubs cite seven such paths between them, and every one of them is correct prose rather than a
    broken link. The exemption is keyed on being a stub, not on the citation looking unusual.

    Citations are deduplicated and reported in first-appearance order, so a body that mentions the
    same missing path twice is one fault, not two.
    """
    if raw.entry is None or superseded_by is not None:
        return []
    present = raw.file_paths
    return [
        ValidationFinding.for_code(
            ValidationCode.V3,
            f"{raw.entry_path} cites {cited}, which does not exist under {raw.root_path}",
            cited,
        )
        for cited in cited_reference_paths(raw.entry.body)
        if cited not in present
    ]


def _apply_v4(artifact: Artifact, known_ids: frozenset[str]) -> Artifact:
    """V4 — `superseded_by` names an artifact the library does not have.

    Library-level, because "resolves" is a statement about the set of ids that exist. Note what this
    rule must *not* do: R8 says a superseded artifact stays visible and is only ranked lower, so a
    dangling successor adds a finding and never removes anything.
    """
    successor = artifact.superseded_by
    if successor is None or successor in known_ids:
        return artifact
    finding = ValidationFinding.for_code(
        ValidationCode.V4,
        f"superseded_by names {successor!r}, which is not an artifact in this library",
    )
    return replace(artifact, findings=(*artifact.findings, finding))


def _check_v5(raw: RawArtifact) -> list[ValidationFinding]:
    """V5 — a required frontmatter key is missing or empty.

    The key list belongs to the type registry, not here. Silent when V1 fired: a missing entry
    document means every required key is missing, and reporting one fault as three buries it.
    """
    if raw.entry is None:
        return []
    frontmatter = raw.entry.frontmatter
    return [
        ValidationFinding.for_code(
            ValidationCode.V5,
            f"required frontmatter key {key!r} is "
            f"{'missing' if key not in frontmatter else 'empty'}",
            raw.entry_path,
        )
        for key in raw.spec.required_frontmatter_keys
        if _is_absent_or_empty(frontmatter.get(key))
    ]


def _check_v6(raw: RawArtifact) -> list[ValidationFinding]:
    """V6 — an extraneous path under the artifact root. WARNING, never blocking.

    The scanner decided what to skip and why; this turns each decision into a report. Ruling R6 in
    particular: a symlink is skipped, reported, and never followed — a link resolving outside the
    artifact root is how a copy writes outside its target. Nothing here consults a filesystem, and
    nothing here deletes anything.
    """
    return [
        ValidationFinding.for_code(
            ValidationCode.V6,
            f"{skipped.path} was skipped: {_SKIP_REASON_PHRASES[skipped.reason]}"
            + (f" ({skipped.detail})" if skipped.detail else ""),
            skipped.path,
        )
        for skipped in raw.skipped
    ]


def _check_v7(
    metadata: LibraryMetadata, known_ids: frozenset[str]
) -> tuple[ValidationFinding, ...]:
    """V7 — a `library.yaml` entry or a `collections[].members` id that resolves to nothing.

    A fault of the document rather than of any artifact, which is why it has nowhere to live except
    the library level: there is by construction no artifact to attach it to. The collection is still
    returned carrying its members; nothing is filtered.

    `library.yaml` keys are reported in declaration order, then each collection's members in
    declaration order, so two scans of one library produce the same report.
    """
    findings: list[ValidationFinding] = [
        ValidationFinding.for_code(
            ValidationCode.V7,
            f"library.yaml declares {artifact_id!r}, which is not an artifact in this library",
        )
        for artifact_id in metadata.artifacts
        if artifact_id not in known_ids
    ]
    findings.extend(
        ValidationFinding.for_code(
            ValidationCode.V7,
            f"collection {collection.key!r} lists member {member!r}, "
            "which is not an artifact in this library",
        )
        for collection in metadata.collections
        for member in _unique(collection.members)
        if member not in known_ids
    )
    return tuple(findings)


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def cited_reference_paths(body: str) -> tuple[str, ...]:
    """Every distinct `references/…` path cited in `body`, in first-appearance order.

    Public because V3's behaviour is easier to pin down one layer at a time: what counts as a
    citation is a separate question from what happens to one that does not resolve.
    """
    return _unique(_CITATION_PATTERN.findall(body))


def _resolve_superseded_by(entry: RawEntry | None, declared: str | None) -> str | None:
    """The successor id, `library.yaml` first and the entry's frontmatter second.

    `library.yaml` is authoritative because that is where `ArtifactMetadata` puts it. The
    frontmatter fallback exists because V3's exemption is a property of *being a stub*, and a
    library with no `library.yaml` at all still has stubs — without the fallback, V3 would flood
    exactly the case charter §8 carves out. An unparseable value is ignored rather than raised on:
    it is user-authored data, and V4 reports it as unresolvable.
    """
    if declared is not None:
        return declared
    if entry is None:
        return None
    return _text_or_none(entry.frontmatter.get("superseded_by"))


def _is_absent_or_empty(value: object) -> bool:
    """Whether a frontmatter value counts as missing for V5.

    `None`, a blank string and an empty collection are all "the key is there but says nothing",
    which is the fault V5 names — charter §8 says *missing or empty*, not merely absent.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | tuple | set | dict):
        return not value
    return False


def _text_or_none(value: object) -> str | None:
    """A frontmatter value as trimmed text, or `None` when it says nothing or is not text."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """The distinct values, in first-appearance order."""
    return tuple(dict.fromkeys(values))


__all__ = [
    "REFERENCE_DIRECTORY",
    "AssembledLibrary",
    "assemble_artifact",
    "assemble_library",
    "cited_reference_paths",
]
