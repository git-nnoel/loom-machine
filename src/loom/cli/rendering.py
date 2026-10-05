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

from loom.application.read import (
    ArtifactDetail,
    ArtifactListPayload,
    CollectionDetail,
    CollectionListPayload,
    FindingPayload,
    Payload,
    SearchResults,
    ValidationReport,
)
from loom.cli.payloads import (
    BackupsPayload,
    CleanPayload,
    ExportPayload,
    InstallPayload,
    PlanEntryPayload,
    PlanPayload,
    ResolutionPayload,
    RollbackPayload,
    UninstallPayload,
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
        # Declared and absent. Each is also a V7 ERROR in `loom validate`; it is repeated here so a
        # user reading one collection is not required to validate the whole library to discover
        # that part of it is missing.
        stream.write(f"\nunresolved members ({len(payload.unresolved_member_ids)})\n")
        for member_id in payload.unresolved_member_ids:
            stream.write(f"  {member_id}  [MISSING]\n")


# ------------------------------------------------------------------------------------------------
# The write path (T-22). Same rule as everything above: presentation, never contract (R7)
# ------------------------------------------------------------------------------------------------


def render_plan(payload: PlanPayload, stream: TextIO) -> None:
    """What install would do about every path. Contract C-10, as a table. `loom diff`'s whole view.

    **The verdict leads every row**, because it is the branchable value and the one thing a user
    scans for. The counts line is written from `counts`, which arrived dense over all nine
    verdicts (R62); the zero rows are dropped here rather than in the payload, which is the
    whole difference between a rendering and a contract.
    """
    if _plan_table(payload, stream):
        _refused(
            [entry for entry in payload.entries if entry.reason is not None],
            stream,
            heading="reasons",
        )


def _plan_table(payload: PlanPayload, stream: TextIO) -> bool:
    """The table and the counts line, with no reasons. False when there was nothing to show.

    Split out because `render_install` prints the same table and then its **own** list of what
    was left alone — which is the one a user acts on, is a different set from "every entry that
    carries a reason", and includes a `local_edit`, which carries none. Printing both would say
    the same sentences twice and leave the reader working out which of the two lists is the one
    they are being asked about.
    """
    if not payload.entries:
        stream.write("Nothing here: the library, the manifest and the target are all empty.\n")
        return False
    rows = [
        (entry.verdict.value, entry.path, entry.artifact_id or NOT_SET) for entry in payload.entries
    ]
    _table(("VERDICT", "PATH", "ARTIFACT"), rows, stream)
    stream.write(f"\n{payload.total} path(s) in {payload.target_path}: {_counts(payload)}.\n")
    return True


def render_install(payload: InstallPayload, stream: TextIO) -> None:
    """What one install did, or — with `--dry-run` — what it would have done. Features F-9, F-15.

    The refusals are printed **last and in full**, with the reason each entry carries, because
    they are the part the user has to act on and `INCOMPLETE = 6` is the status that sends them
    here. Everything above them is a receipt.
    """
    if payload.dry_run:
        stream.write("DRY RUN — nothing was written.\n\n")
    _plan_table(payload.plan, stream)

    if not payload.dry_run:
        stream.write("\n")
        _paths("written", payload.written, stream)
        if payload.prune:
            _paths("removed (--prune)", payload.deleted, stream)
        _field("backup", payload.backup_id or NOT_SET, stream)

    if payload.resolution is not None:
        render_resolution(payload.resolution, stream)

    _refused(payload.left_alone, stream, heading="left alone")
    stream.write(
        "\nComplete: everything was applied.\n"
        if payload.is_complete
        else "\nINCOMPLETE: the entries above were left alone. Nothing was destroyed — decide "
        "each one with loom install --resolve library|target|edit <artifact>.\n"
    )


def render_resolution(payload: ResolutionPayload, stream: TextIO) -> None:
    """What `--resolve` did to one artifact. Feature F-15, ruling R54."""
    stream.write(f"\nresolve {payload.side}: {payload.artifact_id}\n")
    _paths("written", payload.written, stream)
    _paths("record repaired", payload.repaired, stream)
    _paths("dropped from the record", payload.dropped, stream)
    _paths("shown in $EDITOR", payload.compared, stream)
    if payload.backup_id is not None:
        _field("backup", payload.backup_id, stream)
    if payload.side == "target" and payload.repaired:
        # Ruling R100, said out loud where the user is looking. The record now agrees with the
        # disk, which is what clears the refusal — and which also makes the library's next
        # version an ordinary `update`.
        stream.write(
            "  note           the refusal is settled, the file is NOT pinned: the next\n"
            "                 loom install writes the library's version over the copy you kept.\n"
        )
    _refused(payload.left_alone, stream, heading="still refused")


def render_uninstall(payload: UninstallPayload, stream: TextIO) -> None:
    """What one uninstall removed. Feature F-12."""
    stream.write(f"{payload.artifact_id}\n")
    _field("target", payload.target_path, stream)
    _field("backup", payload.backup_id or NOT_SET, stream)
    _paths("removed", payload.removed, stream)
    _paths("already gone", payload.absent, stream)
    stream.write(
        f"\n{len(payload.removed)} file(s) removed. Anything this tool did not install is "
        "untouched.\n"
    )


def render_rollback(payload: RollbackPayload, stream: TextIO) -> None:
    """What one rollback put back. Feature F-11, and ruling R112's other outcome.

    **A rollback with nothing to put back is reported here, not raised.** It reaches this
    function as a payload naming no backup, and it leaves as a sentence on stdout and exit 0 —
    the shape `INCOMPLETE` already uses for "a run that did not fail and did not do everything".
    """
    if payload.backup_id is None:
        stream.write(f"nothing to roll back in {payload.target_path}\n")
        stream.write(
            "\nNo backup of this target exists and the record claims none: the last run wrote "
            "nothing, so there is nothing to undo. A run that writes takes a backup first.\n"
        )
        return
    stream.write(f"backup {payload.backup_id}\n")
    _field("target", payload.target_path, stream)
    _paths("restored", payload.restored, stream)
    _paths("removed again", payload.removed, stream)
    stream.write(f"\n{len(payload.restored)} file(s) restored, {len(payload.removed)} removed.\n")


def render_backups(payload: BackupsPayload, stream: TextIO) -> None:
    """Every rollback point this target has. Ruling R113.

    **The id column is the whole point** — it is what `loom rollback` takes — so it is first, and
    it is printed verbatim rather than abbreviated: a truncated id is not an id.
    """
    stream.write(f"backups of {payload.target_path}\n")
    if not payload.backups:
        stream.write(
            "\nNo backups. One is taken before anything is written, removed or restored; a run "
            "that changed no file took none.\n"
        )
        return
    _table(
        ("BACKUP ID", "TAKEN", "PATHS", "BYTES", "LINKS"),
        (
            (
                backup.backup_id,
                backup.created_at,
                str(backup.described),
                str(backup.kept),
                str(backup.links),
            )
            for backup in payload.backups
        ),
        stream,
    )
    stream.write(
        f"\n{len(payload.backups)} backup(s), oldest first. Put one back with "
        f"loom rollback {payload.backups[-1].backup_id} — or with no id for the most recent.\n"
    )


def render_clean(payload: CleanPayload, stream: TextIO) -> None:
    """The listing, then what came of it. Features F-10 and F-12, ruling R96.

    **The listing is printed first and in full, always** — before the removals and whether or not
    anything was removed. That is not a layout choice: with `--remove` it is the statement the
    user is being shown of what went, and without it, it is the statement they authorise.
    """
    subject = "foreign paths" if payload.mode == "foreign" else "paths the library has dropped"
    stream.write(f"{subject} in {payload.target_path}\n")
    _paths("listed", payload.listed, stream)
    _paths("already gone", payload.absent, stream)
    if not payload.removed_requested:
        stream.write(
            f"\n{len(payload.listed)} path(s) listed. Nothing was removed — pass --remove to "
            "delete them.\n"
        )
        return
    _paths("removed", payload.removed, stream)
    _field("backup", payload.backup_id or NOT_SET, stream)
    stream.write(f"\n{len(payload.removed)} path(s) removed. Roll back with loom rollback.\n")


def render_export(payload: ExportPayload, stream: TextIO) -> None:
    """One collection as an archive. Feature F-16."""
    stream.write(f"{payload.key} -> {payload.output}\n")
    _field("entries", str(len(payload.entries)), stream)
    _field("size", f"{payload.size} bytes", stream)
    for entry in payload.entries:
        stream.write(f"  {entry}\n")
    if payload.unresolved_member_ids:
        # Also a V7 ERROR in `loom validate`. Repeated here so a user does not have to validate the
        # whole library to discover that part of their archive is missing (ruling R27's posture).
        stream.write(f"\nunresolved members ({len(payload.unresolved_member_ids)})\n")
        for member_id in payload.unresolved_member_ids:
            stream.write(f"  {member_id}  [MISSING]\n")


def _counts(payload: PlanPayload) -> str:
    """The non-zero verdict counts, in C-9's declaration order. Presentation only."""
    present = [f"{verdict.value} {count}" for verdict, count in payload.counts.items() if count > 0]
    return ", ".join(present) if present else "nothing"


def _paths(label: str, paths: Sequence[str], stream: TextIO) -> None:
    """One labelled path list, omitted entirely when it is empty."""
    if not paths:
        return
    stream.write(f"  {label} ({len(paths)})\n")
    for path in paths:
        stream.write(f"    {path}\n")


def _refused(entries: Sequence[PlanEntryPayload], stream: TextIO, *, heading: str) -> None:
    """Every entry given, with its reason when it carries one.

    **Every entry, not only the explained ones.** C-10 requires a reason on `conflict` and
    `skipped` and leaves it optional elsewhere, so a `local_edit` left alone arrives here with
    `reason` null — and dropping it would hide from the user one of the two things they have to
    decide about. The verdict is the explanation in that case, which is why it leads the line.

    Reasons are printed in full and never truncated: the user is being asked to decide
    something, and a reason cut short is a decision they cannot make.
    """
    if not entries:
        return
    stream.write(f"\n{heading} ({len(entries)})\n")
    for entry in entries:
        stream.write(f"  {entry.verdict.value}  {entry.path}\n")
        if entry.reason is not None:
            stream.write(f"    {entry.reason}\n")


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
