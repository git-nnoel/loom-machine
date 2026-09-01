"""Two renderings of one payload: `--json`, which is contract, and the human table, which is not.

**Ruling R7 draws the line this module is built around.** `--json` is
`payload.model_dump_json()` — the frozen C-7 model, serialised by Pydantic, with nothing added and
nothing reshaped. An adapter that assembled its own dictionary from an `Artifact` would have
created a second wire format, and the second one is always the one that drifts. The human format
is free to change with taste; the JSON is not free to change at all.

**Nothing here computes.** Ordering, ruling R8's ranking, the search cap and the validity verdict
all arrived decided. In particular the artifact list is written out in the order it was handed
over: re-sorting it here would silently overrule R8, and it would do so in a way that only shows up
as "the CLI and the MCP server disagree" long after both look finished.

**Ruling R27: every omission is visible.** A search prints its skipped files with their reasons. A
result set that hit the cap says so. A rendering that quietly dropped either would turn a partial
answer into an apparently complete one, which is the failure this product exists to eliminate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TextIO

from harness_library.application.read import (
    ArtifactDetail,
    ArtifactListPayload,
    CollectionDetail,
    CollectionListPayload,
    FindingPayload,
    Payload,
    SearchResults,
    ValidationReport,
)

NOT_SET = "-"
"""What an absent optional value looks like in a table.

Never an empty cell, which reads as a rendering bug rather than as a fact.
"""


def emit_json(payload: Payload, stream: TextIO) -> None:
    """The contract rendering. Ruling R7.

    One line, so a shell loop over several invocations produces JSON Lines without any extra
    ceremony, and `jq` reads it either way.
    """
    stream.write(payload.model_dump_json())
    stream.write("\n")


def render_artifact_list(payload: ArtifactListPayload, stream: TextIO) -> None:
    """A listing, in the order it arrived. Feature F-1."""
    if not payload.artifacts:
        stream.write("No artifacts matched.\n")
        return
    rows = [
        (
            artifact.id,
            artifact.kind.value,
            "ok" if artifact.is_valid else "INVALID",
            ", ".join(artifact.tags) or NOT_SET,
            # Ruling R8: a superseded artifact is ranked below its successor and *labelled*. It is
            # never hidden, and a reader who cannot see that it is retired has been misled.
            artifact.superseded_by or NOT_SET,
            str(artifact.file_count),
        )
        for artifact in payload.artifacts
    ]
    _table(("ID", "KIND", "STATUS", "TAGS", "SUPERSEDED BY", "FILES"), rows, stream)
    stream.write(f"\n{payload.total} artifact(s), sorted by {payload.sort}.\n")


def render_artifact_detail(payload: ArtifactDetail, stream: TextIO) -> None:
    """One artifact in full. Feature F-2.

    An artifact with findings is rendered *with* them. A skill with no `SKILL.md` reaches here with
    `entry_text` null and a V1 finding attached, and printing that is the entire point of F-2 — the
    superseded plan raised on this case, which is the one case the validation system exists for.
    """
    stream.write(f"{payload.id}\n")
    _field("name", payload.name, stream)
    _field("type", payload.type.value, stream)
    _field("kind", payload.kind.value, stream)
    _field("path", payload.path, stream)
    _field("description", payload.description or NOT_SET, stream)
    _field("tags", ", ".join(payload.tags) or NOT_SET, stream)
    _field("superseded by", payload.superseded_by or NOT_SET, stream)
    _field("content hash", payload.content_hash, stream)
    _field("updated", payload.updated_at.isoformat(), stream)
    _field("dirty", "yes" if payload.is_dirty else "no", stream)
    _field("valid", "yes" if payload.is_valid else "no", stream)

    stream.write(f"\nfiles ({payload.file_count}, {payload.total_size} bytes)\n")
    for file in payload.files:
        marker = "" if file.is_text else "  [binary]"
        stream.write(f"  {file.path} ({file.size} bytes){marker}\n")

    if payload.frontmatter:
        stream.write("\nfrontmatter\n")
        for key, value in payload.frontmatter.items():
            stream.write(f"  {key}: {value}\n")

    _findings(payload.findings, stream, heading=f"findings ({len(payload.findings)})")

    stream.write(f"\nentry document: {payload.entry_path}\n")
    if payload.entry_text is None:
        stream.write("  (no readable entry document — see the findings above)\n")
    else:
        stream.write("\n")
        stream.write(
            payload.entry_text if payload.entry_text.endswith("\n") else payload.entry_text + "\n"
        )


def render_search_results(payload: SearchResults, stream: TextIO) -> None:
    """Matches, then the omissions. Feature F-3, rulings R25 and R27."""
    if payload.matches:
        for match in payload.matches:
            stream.write(
                f"{match.artifact_id}:{match.path}:{match.line_number}: {match.line_text}\n"
            )
    else:
        stream.write(f"No matches for {payload.query!r}.\n")

    stream.write(f"\n{len(payload.matches)} match(es)")
    if payload.truncated:
        # Never inferred from len(matches) == limit: a search finding exactly `limit` matches and
        # no more is complete, and calling it truncated would be a different wrong answer.
        stream.write(f", TRUNCATED at the limit of {payload.limit}")
    stream.write(".\n")

    if payload.skipped:
        # Ruling R27 and charter §4's R4: a file that was not searched is reported, with a reason
        # that is never the word "binary". Hiding this is how a search comes to cover half a
        # library while looking exhaustive.
        stream.write(f"\n{len(payload.skipped)} file(s) not searched:\n")
        for skipped in payload.skipped:
            stream.write(f"  {skipped.artifact_id}:{skipped.path} — {skipped.reason.value}\n")


def render_validation_report(payload: ValidationReport, stream: TextIO) -> None:
    """The library's verdict. Feature F-4.

    The exit status is decided from `payload.is_valid` by the caller, never recomputed from what
    this function happens to print.
    """
    for artifact in payload.artifacts:
        status = "ok" if artifact.is_valid else "INVALID"
        stream.write(f"\n{artifact.id}  [{status}]  {artifact.path}\n")
        _findings(artifact.findings, stream, heading=None)

    if payload.library_findings:
        # Ruling R23: V7 and V9 belong to `library.yaml` itself and have no artifact to hang on. A
        # report that printed only the artifact loop would leave two rows of charter §8 unable to
        # fail anything.
        stream.write("\nlibrary.yaml\n")
        _findings(payload.library_findings, stream, heading=None)

    verdict = "valid" if payload.is_valid else "INVALID"
    stream.write(
        f"\n{payload.artifact_count} artifact(s) checked: {verdict}. "
        f"{payload.error_count} error(s), {payload.warning_count} warning(s).\n"
    )
    if payload.error_count == 0 and payload.warning_count:
        # Ruling R22, said out loud. A stray editor swap file is a V6 WARNING; a user who sees
        # warnings and a zero exit status should be told that is deliberate, not a near miss.
        stream.write("Warnings never block: this library is valid.\n")


def render_collection_list(payload: CollectionListPayload, stream: TextIO) -> None:
    """Every declared collection, in declaration order. Feature F-5."""
    if not payload.collections:
        stream.write("This library declares no collections.\n")
        return
    rows = [
        (
            collection.key,
            collection.title or NOT_SET,
            str(collection.member_count),
            collection.description or NOT_SET,
        )
        for collection in payload.collections
    ]
    _table(("KEY", "TITLE", "MEMBERS", "DESCRIPTION"), rows, stream)
    stream.write(f"\n{payload.total} collection(s).\n")


def render_collection_detail(payload: CollectionDetail, stream: TextIO) -> None:
    """One collection with its members resolved. Feature F-5."""
    stream.write(f"{payload.key}\n")
    _field("title", payload.title or NOT_SET, stream)
    _field("description", payload.description or NOT_SET, stream)

    stream.write(f"\nmembers ({len(payload.members)})\n")
    for member in payload.members:
        status = "ok" if member.is_valid else "INVALID"
        stream.write(f"  {member.id}  [{status}]\n")

    if payload.unresolved_member_ids:
        # Declared and absent. Each is also a V7 ERROR in `hl validate`; it is repeated here so a
        # user reading one collection is not required to validate the whole library to discover
        # that part of it is missing.
        stream.write(f"\nunresolved members ({len(payload.unresolved_member_ids)})\n")
        for member_id in payload.unresolved_member_ids:
            stream.write(f"  {member_id}  [MISSING]\n")


def _findings(findings: Sequence[FindingPayload], stream: TextIO, *, heading: str | None) -> None:
    """A finding list. The `code` leads every line because it is the branchable value (C-3)."""
    if not findings:
        return
    if heading is not None:
        stream.write(f"\n{heading}\n")
    for finding in findings:
        location = f" ({finding.path})" if finding.path is not None else ""
        severity = finding.severity.value.upper()
        stream.write(f"  {finding.code.value} {severity}: {finding.message}{location}\n")


def _field(label: str, value: str, stream: TextIO) -> None:
    """One aligned `label: value` line of a detail view."""
    stream.write(f"  {label:<14} {value}\n")


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]], stream: TextIO) -> None:
    """A columnar table, sized to its contents. Presentation only — never contract (ruling R7)."""
    materialised = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in materialised:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    stream.write(
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)).rstrip()
    )
    stream.write("\n")
    for row in materialised:
        stream.write(
            "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip()
        )
        stream.write("\n")


__all__ = [
    "NOT_SET",
    "emit_json",
    "render_artifact_detail",
    "render_artifact_list",
    "render_collection_detail",
    "render_collection_list",
    "render_search_results",
    "render_validation_report",
]
