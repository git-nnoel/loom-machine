"""The `--json` contract for the six write-path commands. Ruling **R7**.

`--json` is contract and the human columnar format is not, which is the line `cli/rendering.py`
is built around and the reason these models exist at all: a command that assembled a dictionary
by hand would create a second wire format, and the second one is always the one that drifts.
Every model here is Pydantic, frozen and closed to fields nobody declared, and subclasses
`application.read.Payload` so `rendering.emit_json` stays one function over one base type.

**Why they are in `cli/` and not in `application/read/dtos.py`, where C-7's are.** Charter §3
puts shared presentation DTOs in the application layer so that `mcp/` can reach the same
serialisation the CLI uses — and `mcp/` may not reach the write path at all (`mcp-is-read-only`),
so none of these is shared with it today. T-22's territory is `cli/**`. **Initiative 03 renders
C-9 and C-10 as a drift view**, so `PlanEntryPayload` and `PlanPayload` are the two that will
want to move; when they do, they move as they are, because everything here is a projection of a
frozen entity and holds no judgement of its own.

**Nothing here computes.** Every verdict, every count, every `is_complete` and every path list
arrived decided by a use case. `InstallPlan.counts` is already dense over all nine verdicts
(R62) and is copied rather than re-tallied; `is_complete` is read, never recomputed from the
entries beside it. A payload that re-derived either would be a second implementation of C-10's
predicate, disagreeing with the first exactly where it mattered.
"""

from __future__ import annotations

from collections.abc import Sequence

from loom.application.read import ExportedCollection, Payload
from loom.application.write import (
    ApplyResult,
    CleanResult,
    ComparisonResult,
    PruneResult,
    ResolveResult,
    RollbackResult,
    UninstallResult,
)
from loom.domain.backup import BackupRecord
from loom.domain.install_plan import (
    BLOCKING_VERDICTS,
    InstallPlan,
    PlanEntry,
    Verdict,
)


class PlanEntryPayload(Payload):
    """One path, its three digests and what install intends to do about it. Contract C-10.

    Attributes:
        artifact_id: the `<type>/<name>` this path belongs to, or null for a foreign path under
            no artifact root at all (R60) — `settings.json`, and every path of Claude Code's
            `synced/` bucket.
        path: relative to the target root.
        verdict: **the branchable value.** One of C-9's nine.
        library_sha: the library's digest, or null when the library does not hold this path.
            Null is absence, never "a digest that did not match".
        manifest_sha: what the manifest recorded at the last install, or null.
        target_sha: what is on the target's disk now, or null when the target does not hold it.
            The literal `<unhashed>` means the target holds the path and its content was never
            read — a symlink, which ruling R6 never follows (R72). Three states, not two.
        reason: why, for the verdicts that need explaining. Always set on `conflict` and
            `skipped`; prose, never contract.
    """

    artifact_id: str | None
    path: str
    verdict: Verdict
    library_sha: str | None
    manifest_sha: str | None
    target_sha: str | None
    reason: str | None

    @classmethod
    def of(cls, entry: PlanEntry) -> PlanEntryPayload:
        return cls(
            artifact_id=entry.artifact_id,
            path=entry.path,
            verdict=entry.verdict,
            library_sha=entry.library_sha,
            manifest_sha=entry.manifest_sha,
            target_sha=entry.target_sha,
            reason=entry.reason,
        )


class PlanPayload(Payload):
    """Everything one install would do, decided before anything is written. Contract C-10.

    Attributes:
        target_path: the directory the plan is about.
        entries: one per path any of the three sides holds, in path order.
        counts: how many entries carry each verdict — **every** verdict, including the zeros
            (R62). A consumer that had to guard each lookup would forget one.
        is_complete: false when any entry awaits a human decision. Read from the plan, never
            recomputed here.
        total: how many entries there are, so a summary needs no arithmetic.
    """

    target_path: str
    entries: tuple[PlanEntryPayload, ...]
    counts: dict[Verdict, int]
    is_complete: bool
    total: int

    @classmethod
    def of(cls, plan: InstallPlan, *, target_path: str) -> PlanPayload:
        return cls(
            target_path=target_path,
            entries=tuple(PlanEntryPayload.of(entry) for entry in plan.entries),
            counts=dict(plan.counts),
            is_complete=plan.is_complete,
            total=len(plan.entries),
        )


class ResolutionPayload(Payload):
    """What one `--resolve` did to one artifact, whichever of the three ways it was spelled.

    Attributes:
        artifact_id: the artifact whose refused paths this settled. **One artifact, never a run**
            (R54): another artifact's conflict is still refused.
        side: `library`, `target` or `edit` — the flag's three spellings. `edit` shows both
            versions and decides nothing, so everything below it is empty but `compared`.
        written: the target paths written, for `library`.
        repaired: the target paths whose record now carries the **target's** digest, for
            `target`.
        dropped: the target paths dropped from the record because the target no longer holds
            them.
        compared: the target paths handed to `$EDITOR`, for `edit`.
        backup_id: the backup taken before the first write, or null. Always null for `target`,
            which writes no file and so has nothing to protect (R88).
        left_alone: every refused entry this side could not take, with the reason. A V11
            `skipped` artifact keeps its own reason — `--resolve` does not lift it (R99).
        is_complete: whether every refused path of this artifact was decided.
    """

    artifact_id: str
    side: str
    written: tuple[str, ...] = ()
    repaired: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    compared: tuple[str, ...] = ()
    backup_id: str | None = None
    left_alone: tuple[PlanEntryPayload, ...] = ()
    is_complete: bool = False

    @classmethod
    def of_resolution(cls, result: ResolveResult) -> ResolutionPayload:
        return cls(
            artifact_id=result.artifact_id,
            side=result.resolution.value,
            written=result.written,
            repaired=result.repaired,
            dropped=result.dropped,
            backup_id=result.backup_id,
            left_alone=tuple(PlanEntryPayload.of(entry) for entry in result.left_alone),
            is_complete=result.is_complete,
        )

    @classmethod
    def of_comparison(cls, result: ComparisonResult, *, side: str) -> ResolutionPayload:
        return cls(
            artifact_id=result.artifact_id,
            side=side,
            compared=result.compared,
            left_alone=tuple(PlanEntryPayload.of(entry) for entry in result.left_alone),
            # Never complete: a comparison decides nothing, so every path it showed is still
            # refused and the run still owes the user a decision (`INCOMPLETE = 6`, R57).
            is_complete=False,
        )


class InstallPayload(Payload):
    """What one `loom install` did, or — with `--dry-run` — what it would have done.

    Attributes:
        target_path: the directory installed into.
        dry_run: true when nothing was written. The plan below is then the whole answer.
        prune: whether `--prune` was asked for. Install never removes a path otherwise.
        force: whether `--force` was asked for. It lifts R75's refusal of an artifact that does
            not validate and **does not lift V11's** (R46, R99).
        plan: what was decided. With `--resolve` this is the plan the apply ran, *before* the
            resolution changed anything.
        written: the target paths written, in plan order.
        deleted: the target paths removed, in plan order. Empty unless `--prune`.
        left_alone: every entry apply refused to act on, with its reason — the list the user is
            being asked to decide about.
        backup_id: the backup taken before the first byte, or null when there was nothing to
            protect.
        resolution: what `--resolve` did afterwards, or null.
        is_complete: **the value the exit status comes from.** False means `INCOMPLETE = 6`
            (R57) — not a failure: everything safe was written and nothing was destroyed.
    """

    target_path: str
    dry_run: bool
    prune: bool
    force: bool
    plan: PlanPayload
    written: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    left_alone: tuple[PlanEntryPayload, ...] = ()
    backup_id: str | None = None
    resolution: ResolutionPayload | None = None
    is_complete: bool = True

    @classmethod
    def of_plan(cls, plan: PlanPayload, *, prune: bool, force: bool) -> InstallPayload:
        """A `--dry-run`. Nothing was written, so the plan is the whole payload.

        `left_alone` is filled in anyway, so a dry run and a real run have the same shape and a
        caller reads one field to find out what needs deciding. It is selected through
        **`BLOCKING_VERDICTS`**, the register `InstallPlan.is_complete` itself reads, rather than
        by restating its three members here — a second spelling of "what makes a plan
        incomplete" would agree with the first until one of them grew a member.
        """
        return cls(
            target_path=plan.target_path,
            dry_run=True,
            prune=prune,
            force=force,
            plan=plan,
            left_alone=tuple(entry for entry in plan.entries if entry.verdict in BLOCKING_VERDICTS),
            is_complete=plan.is_complete,
        )

    @classmethod
    def of_apply(
        cls,
        result: ApplyResult,
        plan: PlanPayload,
        *,
        prune: bool,
        force: bool,
        left_alone: tuple[PlanEntry, ...],
        resolution: ResolutionPayload | None,
        is_complete: bool,
    ) -> InstallPayload:
        """What the run did, with `left_alone` handed in rather than read off `result`.

        **Because a resolution can settle some of it.** `ApplyResult.left_alone` is what the
        apply refused, and with `--resolve` the command then goes on to decide one artifact's
        share of that list — so reporting the apply's own list would show the user a `conflict`
        two lines under the sentence saying it had just been settled. The caller subtracts what
        the resolution took on and the resolution's own payload reports whatever it could not
        take, so every refused path still appears exactly once.
        """
        return cls(
            target_path=plan.target_path,
            dry_run=False,
            prune=prune,
            force=force,
            plan=plan,
            written=result.written,
            deleted=result.deleted,
            left_alone=tuple(PlanEntryPayload.of(entry) for entry in left_alone),
            backup_id=result.backup_id,
            resolution=resolution,
            is_complete=is_complete,
        )


class UninstallPayload(Payload):
    """What one `loom uninstall` removed, and what the record had already lost.

    Attributes:
        target_path: the directory uninstalled from.
        artifact_id: the artifact removed. **Exactly what the manifest recorded for it and
            nothing beside it** — a foreign file in the same directory survives (F-12).
        removed: the target paths deleted, in the order the record names them.
        absent: the target paths the record named that the target did not hold. Reported rather
            than folded into `removed`: it is the one visible sign that the record and the disk
            had drifted apart.
        backup_id: the backup taken before the first delete, or null when the record named no
            file at all.
    """

    target_path: str
    artifact_id: str
    removed: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    backup_id: str | None = None

    @classmethod
    def of(cls, result: UninstallResult, *, target_path: str) -> UninstallPayload:
        return cls(
            target_path=target_path,
            artifact_id=result.artifact_id,
            removed=result.removed,
            absent=result.absent,
            backup_id=result.backup_id,
        )


class RollbackPayload(Payload):
    """What one `loom rollback` put back, and what it took away again.

    Attributes:
        target_path: the directory restored.
        backup_id: the backup that was put back, or **null when there was nothing to put back**
            (ruling R112). A run that wrote nothing takes no backup — a `MANIFEST_REPAIR`-only
            install is the ordinary case — and rolling one back is a fact about this target
            rather than a failure of this command. The nullability is what a script branches on:
            `restored` and `removed` are empty in that case, and so they are for a rollback that
            genuinely moved nothing.
        restored: every path whose bytes changed or that reappeared, in path order.
        removed: every path the restore took away — what a first install created, undone (R79).
    """

    target_path: str
    backup_id: str | None = None
    restored: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @classmethod
    def of(cls, result: RollbackResult, *, target_path: str) -> RollbackPayload:
        return cls(
            target_path=target_path,
            backup_id=result.backup_id,
            restored=result.restored,
            removed=result.removed,
        )

    @classmethod
    def of_nothing(cls, *, target_path: str) -> RollbackPayload:
        """No backup of this target exists and the record claims none. **Ruling R112.**

        Not built from a `RollbackResult` because there was no rollback: no lock was taken, no
        restore ran and the record was not rewritten. The payload says so by naming no backup.
        """
        return cls(target_path=target_path, backup_id=None)


class BackupSummary(Payload):
    """One backup, as a listing shows it. Contract C-13's record, projected. **Ruling R113.**

    Attributes:
        backup_id: **what `loom rollback` takes as its argument.** The whole reason this listing
            exists: the id is opaque, the store chooses its spelling, and before R113 a user had
            no way to discover one but to list the state directory by hand.
        created_at: when it was taken, ISO-8601 and timezone-aware, so two backups order the
            same way here as they do in the store.
        described: how many paths it would act on — restored, or removed again.
        kept: how many of those it holds bytes for. The rest were **absent** when it was taken,
            and restoring it takes them away again (R79), which is what makes a first install
            undoable and is not obvious from a count of paths alone.
        links: how many were symlinks, recorded by destination and recreated as links (R94).
    """

    backup_id: str
    created_at: str
    described: int
    kept: int
    links: int

    @classmethod
    def of(cls, record: BackupRecord) -> BackupSummary:
        return cls(
            backup_id=record.backup_id,
            created_at=record.created_at.isoformat(),
            described=len(record.paths),
            kept=len(record.kept),
            links=len(record.links),
        )


class BackupsPayload(Payload):
    """Every rollback point one target has, oldest first. **Ruling R113.**

    Attributes:
        target_path: the target these backups are of. Every other target's are filtered out
            (R43) — one state root holds them all, and rolling one target back over another is
            the mistake the filter exists to prevent.
        backups: the records, **oldest first**, so the last row is what `loom rollback` with no id
            would choose. Empty is a value and not a failure: a target nothing was ever backed
            up from has no rollback point, which is the same fact R112 reports from the other
            command.
    """

    target_path: str
    backups: tuple[BackupSummary, ...] = ()

    @classmethod
    def of(cls, records: Sequence[BackupRecord], *, target_path: str) -> BackupsPayload:
        return cls(
            target_path=target_path,
            backups=tuple(BackupSummary.of(record) for record in records),
        )


class CleanPayload(Payload):
    """What one `loom clean` listed, and — only when asked — removed.

    One payload for both selectors, because a caller reads them the same way: here is the list,
    here is what went, here is the way back. `mode` is what tells them apart.

    Attributes:
        target_path: the directory cleaned.
        mode: `foreign` — paths neither the library nor the manifest knows — or `prune`, the
            installed paths the library has since dropped.
        removed_requested: whether `--remove` was passed. **False is the default and the point**
            (R96): the listing is the safety model, and the user authorises it before anything
            goes.
        listed: the whole statement, complete before a single file was touched.
        removed: what actually went, in listing order. Empty without `--remove`.
        absent: paths the plan named that the target no longer held. Neither listed nor removed:
            asking a user to authorise the destruction of something that is not there is not a
            question.
        backup_id: the backup taken before the first delete, or null. **For `foreign`, the only
            way back that will ever exist** — no library and no manifest describes such a path.
    """

    target_path: str
    mode: str
    removed_requested: bool
    listed: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    backup_id: str | None = None

    @classmethod
    def of_clean(
        cls, result: CleanResult, *, target_path: str, removed_requested: bool
    ) -> CleanPayload:
        return cls(
            target_path=target_path,
            mode="foreign",
            removed_requested=removed_requested,
            listed=result.listed,
            removed=result.removed,
            absent=result.absent,
            backup_id=result.backup_id,
        )

    @classmethod
    def of_prune(cls, result: PruneResult, *, target_path: str) -> CleanPayload:
        return cls(
            target_path=target_path,
            mode="prune",
            removed_requested=True,
            # The listing is the union the run acted on: what went, and what had already gone.
            # `PruneResult` reports the two apart, and the listing is what the user authorised.
            listed=result.removed + result.absent,
            removed=result.removed,
            absent=result.absent,
            backup_id=result.backup_id,
        )

    @classmethod
    def of_prunable(cls, entries: tuple[PlanEntry, ...], *, target_path: str) -> CleanPayload:
        """The listing alone — `clean --prune` without `--remove`, which removes nothing."""
        return cls(
            target_path=target_path,
            mode="prune",
            removed_requested=False,
            listed=tuple(entry.path for entry in entries),
        )


class ExportPayload(Payload):
    """One collection as an archive on disk. Feature F-16.

    Attributes:
        key: the collection exported.
        output: where the archive was written, as text.
        size: how many bytes it is.
        entries: the archive's entry names in write order — **target-relative paths** (R73), so
            it unzips over a harness and lands where the same artifacts would have installed.
        unresolved_member_ids: members that resolve to no artifact, in declaration order. Each is
            also a V7 error in `loom validate`; naming them here spares a caller validating the
            whole library to discover a third of their archive is missing.
    """

    key: str
    output: str
    size: int
    entries: tuple[str, ...] = ()
    unresolved_member_ids: tuple[str, ...] = ()

    @classmethod
    def of(cls, exported: ExportedCollection, *, output: str) -> ExportPayload:
        return cls(
            key=exported.key,
            output=output,
            size=len(exported.data),
            entries=exported.entries,
            unresolved_member_ids=exported.unresolved_member_ids,
        )


__all__ = [
    "BackupSummary",
    "BackupsPayload",
    "CleanPayload",
    "ExportPayload",
    "InstallPayload",
    "PlanEntryPayload",
    "PlanPayload",
    "ResolutionPayload",
    "RollbackPayload",
    "UninstallPayload",
]
