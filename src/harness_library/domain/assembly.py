"""Charter §8's validation register, as pure functions. Every rule V1-V11 lives here.

This module is the reason the initiative was recut (DEC-1). The superseded plan built the repository
first and retrofitted validation into it, so two of eight tasks existed only to reopen a third. Here
the rules come *before* the repository: they are total functions over `RawArtifact` values, they
touch no filesystem, and every one of them is tested from a literal.

Each rule closes a failure observed in a real library — a skill directory that silently never
loaded, a skill documenting another skill's path, references cited into an empty directory, editor
swap files destroyed by a copy. Charter §8 is the register; this is its enforcement.

**Two levels, because two rules need more than one artifact.** `assemble_artifact` decides
everything that is a property of a single artifact root: V1, V2, V3, V5, V6, V10. `assemble_library`
runs it over the whole scan and then answers the questions that need the set of ids that exist:
V4 (`superseded_by` resolves), V7 (a `library.yaml` entry or a collection member resolves), V8 (two
names collide case-insensitively) and V9 (`library.yaml` declares a key twice). **V11 is a third
kind**: it is decided about something that never became an artifact at all, so the scan hands it
across as a value and `assemble_library` turns that into a finding — the same seam `SkippedPath`
crosses to become V6.
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

from harness_library.domain.artifact import Artifact, ArtifactKind
from harness_library.domain.hashing import content_hash_of_files
from harness_library.domain.metadata import LibraryMetadata
from harness_library.domain.raw import RawArtifact, RawEntry, SkipReason, SymlinkedRoot
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
        findings: the library-level findings — **V7, V9 and V11**. V7 and V9 are faults of the
            `library.yaml` *document* rather than of any artifact, and there is by definition no
            artifact to hang them on. V11 is here for a different reason and reaches the same
            place: its subject is an artifact root that is a symlink, which R6 never follows and
            never scans, so no `Artifact` was ever produced for it — there is nothing to attach
            it to, and manufacturing one would fire V1 against a skill that loads perfectly.

            V8 is decided at this level too but is **not** here: a case collision has two real
            artifacts to attach itself to, and attaching it only to the library would leave
            `hl show skill/Foo` silent about it. That is the distinction — V8 has two artifacts
            and V11 has none.
    """

    artifacts: tuple[Artifact, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()

    @property
    def by_id(self) -> Mapping[str, Artifact]:
        """The artifacts keyed by `<type>/<name>`."""
        return {artifact.id: artifact for artifact in self.artifacts}


def assemble_library(
    raws: Iterable[RawArtifact],
    metadata: LibraryMetadata,
    *,
    symlinked_roots: Iterable[SymlinkedRoot] = (),
) -> AssembledLibrary:
    """Turn a whole scan into finished artifacts. The entry point T-5 calls.

    Runs `assemble_artifact` over every raw value, then makes the passes that need the whole library
    in view: V4 against each artifact's own `superseded_by`, V8 across the set of names, and V7 and
    V9 against `library.yaml`.

    Args:
        raws: what the scan walked.
        metadata: `library.yaml`, already read.
        symlinked_roots: what the scan found and refused to walk — one V11 WARNING each (R46).
            **Defaults to none**, unlike `plan_install`'s equivalent parameter, and the difference
            is the caller: this function has exactly one production call site, in
            `infrastructure/repository.py`, whose wiring is asserted at repository level against
            the committed fixture; `plan_install`'s caller is a composition root, where a
            parameter with a default is a parameter somebody forgets.
    """
    assembled = [assemble_artifact(raw, metadata) for raw in raws]
    known_ids = frozenset(artifact.id for artifact in assembled)
    resolved = tuple(_apply_v4(artifact, known_ids) for artifact in assembled)
    return AssembledLibrary(
        artifacts=_apply_v8(resolved),
        findings=_check_v7(metadata, known_ids) + _check_v9(metadata) + _check_v11(symlinked_roots),
    )


def assemble_artifact(raw: RawArtifact, metadata: LibraryMetadata) -> Artifact:
    """Turn one scanned root into an `Artifact` carrying its findings.

    Implements V1, V2, V3, V5, V6 and V10 — every rule decidable without seeing the rest of the
    library. V4 needs the set of ids that exist and is applied by `assemble_library`.

    **Two rules suppress others, and both suppressions are conditional.** V1 silences V5, because a
    document that is not there cannot be missing a key in any way worth three findings; V10 silences
    V2, V3 and V5, because a frontmatter block that did not parse supports no claim about what the
    document declares at all (R33, widened to V3 by R37). Neither is a blanket skip: remove the
    cause and the dependent rules fire again.
    """
    declared = metadata.for_artifact(raw.id)
    superseded_by = _resolve_superseded_by(raw.entry, declared.superseded_by)

    findings: list[ValidationFinding] = []
    findings.extend(_check_v1(raw))
    findings.extend(_check_v10(raw))
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

    Silent too when the frontmatter did not parse, which is V10's fault (R33). This rule compares a
    declared name against the directory; after a parse failure nothing was declared to compare.
    """
    if raw.entry is None or raw.entry.parse_error is not None:
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

    **DIRECTORY-kind artifacts only** (ruling R32, DEC-9). References belong to the skill that owns
    them, exactly as `skills/<name>/references/` models on disk. A FILE-kind artifact *is* its entry
    document — its one `ArtifactFile.path` is its own basename — so it can never own a `references/`
    folder, and a citation inside one is prose about *another* artifact's files rather than a claim
    about its own. Without the gate the `cited not in present` test below is unconditionally true
    for every FILE-kind artifact, which is not a strict rule but an unreachable one: T-9 acceptance
    measured it firing eight times on the real library with zero true positives, permanently
    invalidating both agents for citing paths that all exist under the skills they point at.

    This narrows the rule's scope and keeps its teeth. The failure that justified V3 — a skill
    citing references into its own empty directory — is a DIRECTORY-kind artifact and still fires.

    **Exempt while `superseded_by` is set** (charter §8, L5). A redirect stub's whole body is prose
    about its successor, including that successor's reference paths; on the real library the two
    stubs cite seven such paths between them, and every one of them is correct prose rather than a
    broken link. The exemption is keyed on being a stub, not on the citation looking unusual.

    **Silent when the frontmatter did not parse, which is V10's fault** (ruling R37). The exemption
    above is keyed on `superseded_by`, and `_resolve_superseded_by` falls back to the frontmatter
    whenever no `library.yaml` declares a successor — so after a parse failure nothing is known
    about whether this artifact is a stub, and the exemption silently stops applying to the very
    artifacts it exists for. One unquoted colon in a redirect stub would then flood V3 with the
    seven findings charter §8 carves out, burying the one true cause. Conditional, like V10's
    silencing of V2 and V5: an artifact that *parses* and cites a path it does not hold still
    reports V3.

    Citations are deduplicated and reported in first-appearance order, so a body that mentions the
    same missing path twice is one fault, not two.
    """
    if raw.kind is not ArtifactKind.DIRECTORY:
        return []
    if raw.entry is None or superseded_by is not None:
        return []
    if raw.entry.parse_error is not None:
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

    **Silent when V10 fired** (ruling R33), for a sharper reason than tidiness. V5 asserts that a
    key is absent from the document. When the frontmatter block failed to parse, the empty mapping
    is not evidence of absence — it is the absence of evidence, and the real library proved the
    difference: `frontend-system-pattern`'s second line is `name: frontend-system-pattern` and this
    rule reported that key missing. A finding the user can verify is false with their own eyes
    teaches them to distrust the whole report. The suppression is **conditional on the parse having
    failed**, never unconditional: a well-formed document that genuinely lacks a key still fires.
    """
    if raw.entry is None or raw.entry.parse_error is not None:
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


def _apply_v8(artifacts: tuple[Artifact, ...]) -> tuple[Artifact, ...]:
    """V8 — two artifacts of one type whose names differ only by case.

    Library-level, like V4 and V7: "these two collide" is a statement about the set of names that
    exist and cannot be decided from one artifact.

    Why it is a rule at all, beyond tidiness. This library is distributed by `git clone` and
    installed onto other machines, and on a case-insensitive filesystem `skills/Foo` and
    `skills/foo` are one directory — the second install silently overwrites the first, with no
    error anywhere. This scan is the only place the collision is visible, and it is cheap here.

    **Attached to every colliding artifact, not to the library**, and each finding names the whole
    colliding set: a user reading the report on one of them must be able to see what it collided
    with, and a fault reported in only one direction sends them hunting for the other half. The set
    is sorted so two scans of one library produce the same report.

    Two *different types* never collide: `skill/foo` and `agent/foo` are distinct artifacts under
    distinct directories, which is why the grouping key carries the type. Identical names are not
    this rule either — they do not "differ only by case", and a scan cannot produce two of them from
    one directory.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for artifact in artifacts:
        groups.setdefault((artifact.type.value, artifact.name.casefold()), []).append(artifact.id)

    colliding = {key: sorted(set(ids)) for key, ids in groups.items() if len(set(ids)) > 1}
    if not colliding:
        return artifacts

    return tuple(
        _with_v8(artifact, colliding.get((artifact.type.value, artifact.name.casefold()), []))
        for artifact in artifacts
    )


def _with_v8(artifact: Artifact, group: list[str]) -> Artifact:
    """Attach V8 to one member of a colliding group, naming the others."""
    others = [other for other in group if other != artifact.id]
    if not others:
        return artifact
    finding = ValidationFinding.for_code(
        ValidationCode.V8,
        f"{artifact.id} differs only by case from {', '.join(others)}; on a case-insensitive "
        "filesystem these are one path, and installing one silently overwrites the other",
    )
    return replace(artifact, findings=(*artifact.findings, finding))


def _check_v10(raw: RawArtifact) -> list[ValidationFinding]:
    """V10 — the entry document's frontmatter block did not parse (ruling R33).

    The document is there and its body is readable, so V1 would be a lie; but nothing it declares
    was understood, so every rule about its keys has nothing to stand on. This says that in one
    finding, **carrying the parser's own message and position** rather than a paraphrase: the user
    has to find one character in their own file, and `line 3, column 255` is the only part of the
    report that locates it.

    Observed on the real library at the first run against content nobody designed for. A single
    unquoted `": "` inside a description made a plain YAML scalar unparseable, and the tool told
    the user that `name` and `description` were missing from a file whose second line is
    `name: frontend-system-pattern`. Both messages were false and neither was actionable.

    Claude Code's own loader reads that same file successfully, so a leniency to match it was
    considered and rejected (R33): that parser is undocumented, and a lenient reader silently
    accepts files that break the moment anything strict reads them.
    """
    if raw.entry is None or raw.entry.parse_error is None:
        return []
    failure = raw.entry.parse_error
    position = failure.position
    return [
        ValidationFinding.for_code(
            ValidationCode.V10,
            f"the frontmatter of {raw.entry_path} does not parse"
            + (f" at {position}" if position else "")
            + f": {failure.message}",
            raw.entry_path,
        )
    ]


def _check_v9(metadata: LibraryMetadata) -> tuple[ValidationFinding, ...]:
    """V9 — `library.yaml` declares the same key twice.

    A fault of the document, so it sits beside V7 at the library level. The reader observed each
    repeat and recorded it with both line numbers; the severity and the sentence are decided here,
    because charter §8 is what says a duplicate key is an ERROR rather than something tolerated.

    A **finding and not a raise**, deliberately. The document parses and both blocks are understood,
    so it does not meet the reader's bar for "this file is unusable". Reported as a finding it joins
    every other fault in one `hl validate` run and still fails the library, because V9 is an ERROR
    and `is_valid` means no ERROR finding. Raised, it would report itself and nothing else — and a
    rule that can never appear in a report can never make `is_valid` false, which would make its row
    in the register decorative.
    """
    return tuple(
        ValidationFinding.for_code(
            ValidationCode.V9,
            f"library.yaml declares {duplicate.key!r} twice in {duplicate.within} "
            f"(line {duplicate.line} repeats line {duplicate.first_line}); "
            "the earlier declaration is discarded",
        )
        for duplicate in metadata.duplicate_keys
    )


def _check_v11(symlinked_roots: Iterable[SymlinkedRoot]) -> tuple[ValidationFinding, ...]:
    """V11 — an artifact root that is a symlink. WARNING, and the one warning that refuses.

    **The rule closes a silence, not a misbehaviour.** R6 never follows a link, so such a root is
    never walked: the artifact produces no files, no entry document and no `Artifact` at all, and
    before this rule it was simply missing from every listing, every search and every install
    with nothing anywhere saying so. A skill that would load perfectly, invisible. That is the
    failure this product exists to eliminate, and it was the last instance of it left.

    **Library-level, like V7 and V9, and for a stronger reason than either.** Those two have no
    artifact to hang on because their subject is the `library.yaml` document. This one has no
    artifact to hang on because there *is* no artifact — the root was never scanned. Attaching it
    to a manufactured one would fire V1 against a skill whose `SKILL.md` is right there behind
    the link, which is a false ERROR, and false ERRORs teach a user to distrust the whole report
    (the lesson V10 was written from).

    **A WARNING that nevertheless refuses an install**, which is the one exception R22 has.
    Charter §8 and spec §4 both state it. The justification is not that the artifact is broken —
    it may be perfect — but that neither thing install could do with it is safe: following the
    root would copy content from outside the library into the user's target, and writing over the
    root would destroy a development link the user made on purpose. So the artifact is reported
    here and refused in `application/write/install.py`, and the two do not read each other.

    Reported in scan order, so two scans of one library produce the same report.
    """
    return tuple(
        ValidationFinding.for_code(
            ValidationCode.V11,
            f"{root.root_path} is a symlink (-> {root.destination}), which is never followed or "
            f"scanned (ruling R6), so {root.id} is absent from this library. Install refuses this "
            "artifact and applies the rest",
            root.root_path,
        )
        for root in symlinked_roots
    )


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

    **The interaction this fallback has with V10, and where it is closed.** A stub whose
    frontmatter fails to parse declares no `superseded_by` here, so a library with no
    `library.yaml` would lose the exemption and V3 would flood — the precise case charter §8 carves
    out, reopened by one unquoted colon. It is not repaired here by synthesising a successor
    nobody declared: after a parse failure there is no evidence of one. Ruling R37 closes it in
    `_check_v3`, which is silent when the frontmatter did not parse, so V10 reports the one true
    cause and nothing downstream of it.
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
