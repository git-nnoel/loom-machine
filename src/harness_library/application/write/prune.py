"""`PruneTarget` — removing the installed files of what the library no longer holds.

**This is the one removal whose list nobody chose.** Uninstall is told an artifact id and rollback
is told a backup id; prune is told nothing, and works out for itself which of the user's files
this tool put there and the library has since dropped. The verdict rule already decides it, one
path at a time, and this module does not re-derive it: a `PRUNE` entry is a path the manifest
records, the library no longer holds, **and the target still holds exactly what was installed**
(C-9). The third clause is the whole safety: a path whose target copy was edited after the install
comes back `CONFLICT`, not `PRUNE`, so nothing here can remove somebody's work.

## Why this is a use case and not a mode of apply

`apply --prune` removes the same paths, and the two cannot be one function, for a reason that is
not a matter of taste: **they record at opposite ends of the run.** Apply makes files appear and
writes its manifest first (R63); prune only makes files disappear and writes its manifest last
(charter §13b, R86). A mode would make apply hold two orderings and pick between them at runtime,
which is the one thing R63's position in that function exists to make impossible.

Nor is it a mode of `uninstall_artifact`. That one is given an id and removes everything recorded
for it; this one is given no id and removes the recorded paths the *library* dropped — which may
be some of an artifact's files, or all of them, across every artifact at once.

**What the two do share is the definition of "pruned", and it has one spelling.**
`pruned_entries` lives here and `install.py` imports it. The verdict itself is C-9's, decided in
`domain/install_plan.py`, and neither module restates it.

## Delete, then record — charter §13b, and the case that makes it matter most

The rule is *the manifest must never disown a file that is still on disk*, and prune is the
sharpest instance of it in the whole initiative, because **disowning is exactly what prune's
record does**: the pruned paths are dropped from it. Written before the deletes, a crash part-way
through leaves the remaining pruned files on disk claimed by nobody — `FOREIGN`, which install
will not touch, uninstall cannot remove, and only `clean --foreign` can reach.

Deleting first can only leave the record over-claiming files that are already gone, which comes
back `CREATE` on the next `hl diff` and is repaired by running the prune again.

## The backup

Prune takes one and refuses to run without it, for the reason apply and uninstall do (F-9, R88).
The files it removes were installed by this tool, so the manifest could in principle rebuild them
from a library — but the library is precisely what no longer holds them, which makes this the one
removal in the project that **nothing else can undo**. The backup is the only way back.

**A directory is never removed** (C-12). An artifact root emptied by a prune stays behind as an
empty directory, which is visible, harmless and removable by hand; removing it would mean deciding
that nothing else in it matters, which is the decision this module exists not to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_library.domain.artifact import ArtifactFile
from harness_library.domain.backup import BackupStore
from harness_library.domain.errors import (
    BackupFailedError,
    RecordStaleError,
    TargetUnwritableError,
)
from harness_library.domain.hashing import content_hash_of_files
from harness_library.domain.identity import parse_artifact_id
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.lock import WriteLock
from harness_library.domain.manifest import Manifest, ManifestArtifact, ManifestStore
from harness_library.domain.registry import target_path_of
from harness_library.domain.target import TargetRepository


def pruned_entries(plan: InstallPlan) -> tuple[PlanEntry, ...]:
    """Every entry this plan judges `PRUNE`, in plan order. **One spelling, two callers.**

    `apply_install` calls it behind its own `prune` parameter and `prune_target` calls it as its
    whole input. A second `verdict is Verdict.PRUNE` comprehension would be a second answer to
    "what does `--prune` remove", and the two would agree until the day one of them grew a
    narrowing the other did not — at which point `hl install --prune` and `hl prune` would remove
    different files from the same target and both would report success.

    Not in `domain/install_plan.py`: selecting entries from a plan is not a rule about a path, and
    `BLOCKING_VERDICTS` is a register the plan's own predicate reads, not a filter over entries.
    """
    return tuple(entry for entry in plan.entries if entry.verdict is Verdict.PRUNE)


@dataclass(frozen=True, slots=True)
class PruneResult:
    """What one prune did. The value a caller turns into an exit status and a report.

    Attributes:
        manifest: the record now on disk, with every pruned path dropped from it and every
            artifact left with no file dropped entirely. Written **after** the deletes — see the
            module docstring, where that ordering matters more than anywhere else in this
            initiative.
        backup_id: the backup taken before the first delete. `None` only when the plan judged
            nothing `PRUNE`, so the run had nothing to protect.
        removed: the target paths actually deleted, in plan order.
        absent: the target paths the plan named that the target no longer held. Reported rather
            than raised on, and reported rather than folded into `removed`: a `PRUNE` verdict says
            the target held exactly what was installed, so a path missing here means the target
            changed between the plan and this run, and that is worth a line in the report.
    """

    manifest: Manifest
    backup_id: str | None = None
    removed: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()


def prune_target(
    plan: InstallPlan,
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    lock: WriteLock,
    manifest: Manifest,
    installed_at: datetime,
) -> PruneResult:
    """Remove the installed files of everything the library has dropped, and nothing else.

    Args:
        plan: what the library, the manifest and the target say, decided already. Only the
            `PRUNE` entries are read. Prune does **not** re-scan: a second snapshot disagreeing
            with the first is how a path gets removed on the strength of a verdict decided about
            a different file.
        target: contract C-12. Only `exists` and `delete` are called.
        backups: contract C-13. Every path this run will delete is copied first, and a backup
            that cannot be taken stops the run before anything is removed (F-9, R88).
        manifests: contract C-15, where the new record goes.
        lock: charter §12, ruling R50 and C-16. Held around the backup, the deletes and the
            record. **Required, with no default**, for the reason `apply_install`'s is.
        manifest: contract C-11, what is recorded for this target. **Not optional**: a target
            with no manifest has nothing installed in it, so there is nothing to prune, and this
            is the record the pruned paths are dropped from.
        installed_at: when this run happened, timezone-aware. A parameter and never a clock
            (R66), like every other write use case's.

    Returns:
        `PruneResult`, naming what was removed and what the target had already lost.

    Raises:
        LockHeldError: another writer holds this target's lock. **Nothing was removed.**
        BackupFailedError: the backup could not be taken, so **nothing was removed**.
        TargetUnwritableError: a path could not be removed. The deletes before it stand and the
            manifest is **not** rewritten, so nothing on disk is disowned; the backup taken above
            is what puts the run back.
        RecordStaleError: the deletes finished and the record could not be written (R90). The
            files are gone and the manifest still names them, so they report `CREATE` until it
            catches up. Deliberately not `ManifestWriteError`, whose code promises that nothing
            happened — under this ordering that promise would be exactly false.
        ValueError: the manifest records an `artifact_id` that is not a `<type>/<name>` identity.
            Unconstructible since ruling R74; the narrowing below is for the type, not a state.
    """
    with lock.hold():
        entries = pruned_entries(plan)

        removed: list[str] = []
        absent: list[str] = []
        for entry in entries:
            (removed if target.exists(entry.path) else absent).append(entry.path)

        backup_id = _take_backup(backups, tuple(removed) + tuple(absent))

        for path in removed:
            _delete(target, path)

        record = _manifest_after_prune(
            manifest,
            pruned=frozenset(entry.path for entry in entries),
            backup_id=backup_id,
            installed_at=installed_at,
        )
        _write_record(manifests, record)

        return PruneResult(
            manifest=record,
            backup_id=backup_id,
            removed=tuple(removed),
            absent=tuple(absent),
        )


def _take_backup(backups: BackupStore, paths: tuple[str, ...]) -> str | None:
    """Copy every path this run will delete, before it deletes one. `None` when there are none.

    The `absent` paths go in too, deliberately, and that is not a copy of nothing: C-13 records a
    path the target does not hold and keeps no bytes for it, so restoring the backup *removes* it
    again (R79, R92). Leaving them out would make a rollback of this prune put back only some of
    what the run changed, and it is the one difference between a backup that describes the run
    and a backup that describes part of it.

    Raises:
        BackupFailedError: the store could not take it. Nothing is removed — a delete with no way
            back is the failure mode this initiative exists to remove (F-9, R88), and a prune is
            the one removal in this project that no library can rebuild.
    """
    paths = tuple(dict.fromkeys(paths))
    if not paths:
        return None
    try:
        return backups.create(paths)
    except OSError as error:
        raise BackupFailedError(str(error)) from error


def _delete(target: TargetRepository, path: str) -> None:
    """Remove one pruned path.

    Raises:
        TargetUnwritableError: it could not be removed. The same code apply's failed write
            carries, and the same guarantee: the paths before this one are gone and the record
            still names them, so nothing has been disowned.
    """
    try:
        target.delete(path)
    except OSError as error:
        raise TargetUnwritableError(path, str(error)) from error


def _write_record(manifests: ManifestStore, record: Manifest) -> None:
    """Record what is left, **after the last delete**. Charter §13b.

    Raises:
        RecordStaleError: it could not be written (R90). The files are already gone, so this is
            the opposite of `ManifestWriteError`'s guarantee and needs a code that says so.
    """
    try:
        manifests.write(record)
    except OSError as error:
        raise RecordStaleError("prune", str(error)) from error


def _manifest_after_prune(
    previous: Manifest,
    *,
    pruned: frozenset[str],
    backup_id: str | None,
    installed_at: datetime,
) -> Manifest:
    """What the manifest says once the pruned paths have gone.

    One rule, per file: **keep it unless this run pruned its target path.** An artifact left with
    no file is dropped rather than left as a record claiming nothing, which is the same decision
    apply's `_manifest_after` and rollback's composition both make.

    The digests of the files that stay are the ones the previous record carried, unchanged. This
    run touched none of them, and re-deriving them from anywhere else would be a claim about
    bytes nothing here read — the rule
    `what-the-manifest-records-for-a-path-apply-did-not-write` states for install and that holds
    here for the same reason: the manifest says what this tool put there, and a path it did not
    touch still holds whatever it last put there.

    `content_hash` **is** recomputed, over the files that remain. It describes the record, and a
    record that has lost a file has lost it from its hash too; carrying the old value over would
    make the whole-artifact comparison answer "unchanged" about an artifact the run just changed.

    The **`absent`** paths are dropped along with the removed ones. They are not on disk, so
    dropping them disowns nothing, and keeping them would leave the record naming files nothing
    holds — reported `CREATE` on every diff from now until somebody reinstalls.

    `library_git_sha` is **carried over**, unlike a rollback's: the artifacts still recorded here
    really did come from that library state, and this run changed none of them. What moved on is
    the library, and this record does not claim to describe it.
    """
    artifacts: list[ManifestArtifact] = []
    for record in previous.artifacts:
        identity = parse_artifact_id(record.artifact_id)
        if identity is None:  # pragma: no cover - R74 makes this unconstructible
            continue
        artifact_type, name = identity
        kept: list[ArtifactFile] = [
            file
            for file in record.files
            if target_path_of(artifact_type, name, file.path) not in pruned
        ]
        if kept:
            artifacts.append(
                ManifestArtifact(
                    artifact_id=record.artifact_id,
                    content_hash=content_hash_of_files(kept),
                    files=tuple(kept),
                )
            )

    return Manifest(
        target_path=previous.target_path,
        installed_at=installed_at,
        library_git_sha=previous.library_git_sha,
        backup_id=backup_id,
        artifacts=tuple(artifacts),
    )


__all__ = ["PruneResult", "prune_target", "pruned_entries"]
