"""`UninstallArtifact` — removing one artifact's installed files, and nothing that sits beside them.

**This is where "we never touch what we did not write" stops being a claim about install and
becomes a claim about deletion.** Every other refusal in this initiative protects a file by
declining to overwrite it; this one has to protect it while actively removing its neighbours.
Removing one file too many is the worst thing this tool can do, and the mechanism that stops it is
not a rule, a filter or an exclusion list — it is where the list of paths comes from.

## The list comes from the manifest, and from nothing else

`manifest.artifacts[...].files`, joined onto the target with `registry.target_path_of`. Not a walk
of the artifact's root, not a glob, not `scan()` narrowed by a prefix. A foreign file beside an
installed one — an editor swap file, a user's own note, anything under Claude Code's `synced/`
bucket — is not in the record, so it is not in the list, so it survives without anything here
having to know it exists.

That is also why ruling R44 needs no mention in this module. A named exclusion for `synced/` is
what a directory walk would have required; a record-driven list never sees the question.

A path the manifest records and the target no longer holds is passed over rather than raised on:
the file is already not there, which is the outcome uninstall exists to produce. `exists` is the
C-12 member for that question and a dangling symlink counts as present, so a link planted over an
installed path is unlinked as itself rather than followed (C-12's `delete`).

## Delete, then record — R63's rule, pointing the other way

Apply writes its manifest **first** because apply makes files appear, and a record written after
them can disown one that is still on disk. The rule underneath is *the manifest must never disown
a file that is still on disk*, and uninstall makes files disappear, so the record goes **last**.

A manifest written first would drop the artifact and then crash part-way through the deletes,
leaving the rest of its files claimed by nobody: `FOREIGN`, which install will not touch and
uninstall cannot remove — the unrecoverable state R63 exists to prevent, reached from the other
direction. Deleting first can only leave the record over-claiming files that are already gone,
which comes back `CREATE` on the next `hl diff` and is repaired by running uninstall again or by
reinstalling.

## The backup

Uninstall takes one, and refuses to run without it, for the reason apply does (F-9): a delete with
no way back is the failure mode this initiative exists to remove. It is also what makes `hl
rollback` able to undo an `hl uninstall`, which is the only thing that makes the pair coherent —
`BackupStore.create` records every path asked for and keeps bytes for the ones the target holds,
so restoring this backup puts every removed file back exactly as it was.

**A directory is never removed** (C-12). An artifact root emptied by an uninstall stays behind as
an empty directory, which is visible, harmless and removable by hand; removing it would mean
deciding that nothing else in it matters, which is the decision this module exists not to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_library.domain.backup import BackupStore
from harness_library.domain.errors import (
    ArtifactNotFoundError,
    BackupFailedError,
    RecordStaleError,
    TargetUnwritableError,
)
from harness_library.domain.identity import parse_artifact_id
from harness_library.domain.lock import WriteLock
from harness_library.domain.manifest import Manifest, ManifestArtifact, ManifestStore
from harness_library.domain.registry import target_path_of
from harness_library.domain.target import TargetRepository


@dataclass(frozen=True, slots=True)
class UninstallResult:
    """What one uninstall did. The value a caller turns into an exit status and a report.

    Attributes:
        artifact_id: the artifact that was removed from this target.
        manifest: the record now on disk, with that artifact's entry dropped. Written **after**
            the deletes — see the module docstring.
        backup_id: the backup taken before the first delete. `None` only when the artifact's
            record named no file at all, so the run had nothing to protect.
        removed: the target paths actually deleted, in the order the record names them.
        absent: the target paths the record named that the target did not hold. Reported rather
            than raised on, and reported rather than silently folded into `removed`: it is the
            one visible sign that the record and the target had drifted apart.
    """

    artifact_id: str
    manifest: Manifest
    backup_id: str | None = None
    removed: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()


def uninstall_artifact(
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    lock: WriteLock,
    manifest: Manifest,
    artifact_id: str,
    installed_at: datetime,
) -> UninstallResult:
    """Remove exactly the files this manifest records for `artifact_id`, and nothing else.

    Args:
        target: contract C-12. Only `exists` and `delete` are called — this use case never
            scans, because a scan is how a file nobody recorded gets into the removal list.
        backups: contract C-13. Every path this run will delete is copied first, and a backup
            that cannot be taken stops the run before anything is removed.
        manifests: contract C-15, where the new record goes.
        lock: charter §12, ruling R50 and C-16. Held around the backup, the deletes and the
            record. **Required, with no default**, for the reason `apply_install`'s is.
        manifest: contract C-11, what is recorded for this target. **Not optional**: a target
            with no manifest has nothing installed in it, so there is nothing to uninstall, and
            this is the only list of paths that may be acted on.
        artifact_id: the `<type>/<name>` to remove. Exactly one artifact — `--prune`, which
            removes what the *library* no longer holds, is a different question and is T-19's.
        installed_at: when this run happened, timezone-aware. A parameter and never a clock
            (R66), like `apply_install`'s.

    Returns:
        `UninstallResult`, naming what was removed and what the record had already lost.

    Raises:
        LockHeldError: another writer holds this target's lock. **Nothing was removed.**
        ArtifactNotFoundError: this manifest records no such artifact, so this target has nothing
            of it installed. Loud rather than a quiet no-op, which is charter §13's posture: an
            empty answer is a fact about a target and must never also be how a typo looks. The
            code says "the thing you asked for is not here", which is what a caller acts on; that
            it is the *manifest* and not the library that does not hold it is in the message.
        BackupFailedError: the backup could not be taken, so **nothing was removed**.
        TargetUnwritableError: a path could not be removed. The deletes before it stand and the
            manifest is **not** rewritten, so nothing on disk is disowned; the backup taken above
            is what puts the run back.
        RecordStaleError: the manifest could not be written, after deletes that succeeded.
            **Ruling R90** is the plan-level decision this docstring used to say it was waiting
            for. Deliberately not `ManifestWriteError`: under R63 that code means *nothing
            happened*, which is true of an apply and false here — the files are already gone, and
            a code carrying the wrong guarantee is worse than the builtin this used to raise.
    """
    with lock.hold():
        record = _record_of(manifest, artifact_id)
        paths = _target_paths_of(record)

        removed: list[str] = []
        absent: list[str] = []
        for path in paths:
            (removed if target.exists(path) else absent).append(path)

        backup_id = _take_backup(backups, tuple(removed))

        for path in removed:
            _delete(target, path)

        remaining = Manifest(
            target_path=manifest.target_path,
            installed_at=installed_at,
            # Carried over, unlike a rollback's: the artifacts still recorded here really did
            # come from that library state, and this run changed none of them.
            library_git_sha=manifest.library_git_sha,
            backup_id=backup_id,
            artifacts=tuple(
                other for other in manifest.artifacts if other.artifact_id != artifact_id
            ),
        )
        _write_record(manifests, remaining)

        return UninstallResult(
            artifact_id=artifact_id,
            manifest=remaining,
            backup_id=backup_id,
            removed=tuple(removed),
            absent=tuple(absent),
        )


def _record_of(manifest: Manifest, artifact_id: str) -> ManifestArtifact:
    """This manifest's record for one artifact, or a refusal.

    C-11 forbids two records for one id, so the first match is the only match — the duplicate
    guard is on `Manifest.__post_init__` precisely because "the files this manifest names for
    this artifact" is the question uninstall and prune both ask.
    """
    for record in manifest.artifacts:
        if record.artifact_id == artifact_id:
            return record
    raise ArtifactNotFoundError(artifact_id)


def _target_paths_of(record: ManifestArtifact) -> tuple[str, ...]:
    """Where this artifact's recorded files live inside the target. **The forward join, again.**

    `registry.target_path_of`, the same function the plan and the apply are built on (R73). Not
    an inverse of it and not a second implementation of the layout: install writing to one place
    and uninstall looking in another is the precise failure that ruling put the join in the
    registry to prevent, and it would surface as this module removing nothing while reporting
    that it had.

    Every id parses — ruling R74 guards `ManifestArtifact`'s constructor, so a manifest holding
    an unjoinable record can be neither built nor read back off disk. The narrowing below is for
    the type, not for a state.
    """
    identity = parse_artifact_id(record.artifact_id)
    if identity is None:  # pragma: no cover - R74 makes this unconstructible
        return ()
    artifact_type, name = identity
    return tuple(target_path_of(artifact_type, name, file.path) for file in record.files)


def _take_backup(backups: BackupStore, paths: tuple[str, ...]) -> str | None:
    """Copy every path this run will delete, before it deletes one. `None` when there are none.

    Raises:
        BackupFailedError: the store could not take it. Nothing is removed — a delete with no way
            back is the failure mode this initiative exists to remove (F-9), and uninstall is the
            operation that does nothing but delete.
    """
    if not paths:
        return None
    try:
        return backups.create(paths)
    except OSError as error:
        raise BackupFailedError(str(error)) from error


def _write_record(manifests: ManifestStore, record: Manifest) -> None:
    """Record what is left, **after the last delete**. Charter §13b.

    Raises:
        RecordStaleError: it could not be written (R90). The files are already gone, so this is
            the opposite of `ManifestWriteError`'s guarantee and needs a code that says so.
    """
    try:
        manifests.write(record)
    except OSError as error:
        raise RecordStaleError("uninstall", str(error)) from error


def _delete(target: TargetRepository, path: str) -> None:
    """Remove one recorded path.

    Raises:
        TargetUnwritableError: it could not be removed. The same code apply's failed write
            carries, and the same guarantee: the paths before this one are gone and the record
            still names them, so nothing has been disowned.
    """
    try:
        target.delete(path)
    except OSError as error:
        raise TargetUnwritableError(path, str(error)) from error


__all__ = ["UninstallResult", "uninstall_artifact"]
