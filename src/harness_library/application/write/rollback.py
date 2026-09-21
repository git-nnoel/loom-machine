"""`RollbackInstall` — putting a target back the way it was, and saying so in the record.

**This is the feature every other decision in initiative 02 leans on.** Apply may leave a target
part-written (R80, F-9), the backup is mandatory (F-9, `BACKUP_FAILED`), and a failed manifest
write aborts before the first byte (R63) — all three are acceptable only because the target can be
put back. If this module is subtly wrong, each of those was the wrong call, and nobody finds out
until the day somebody needs it.

## What a rollback is, and what it is not

It is **not an uninstall**. Uninstall removes what this tool installed; rollback puts back what was
*there*, whoever put it there. C-13's backup answers that second question and the manifest answers
the first, which is why `domain/backup.py` and `domain/manifest.py` are two modules and why this
one reads a backup and never a library.

**It removes as well as writes** — ruling R79, and it is the half that makes rollback more than an
overwrite. A backup describes every path the run it protected would write or delete, including the
paths the target did **not** hold, recorded with no bytes. Restoring one therefore *deletes* those
again, which is what makes the very first install into an empty target undoable. A rollback that
only overwrote would leave every created file behind and call the target restored.

The mechanism is `BackupStore.restore`, a unit and not a loop this module drives: C-13 owns what a
backup id means and nothing outside the store may parse one.

## Ruling R63's rule, pointing the other way

Apply writes its manifest **first**, because apply makes files appear and a record written after
them can disown one that is on disk — a disowned path reads `FOREIGN`, which install will not
touch and uninstall cannot remove. The rule underneath that ordering is:

> **the manifest must never disown a file that is still on disk.**

Rollback makes files *disappear*, and reinstates older bytes for the rest, so the same rule sends
the record to the **end**: restore, then scan, then write. A crash in between leaves the manifest
still claiming the post-apply digests, so every restored path comes back `LOCAL_EDIT` or
`CONFLICT` and every removed path comes back `CREATE` — each of them a decision the user is asked
about, and none of them a file nothing can reach. The opposite order is not merely unsafe here, it
is impossible: the restored disk is the only source for the digests the new record names, and it
does not exist until the restore has run.

## Where the new manifest's digests come from

From the target, after the restore, and from nowhere else. The manifest that described the
pre-apply state is gone — apply overwrote it and `ManifestStore` has one member (C-15) — so this
module reads the restored bytes back rather than keeping a second record in step with the first.

That reproduces the previous record exactly where it matters. A path the backup restored held,
before the apply, precisely what the last install put there: `UPDATE` means the target held what
the manifest recorded, and `CREATE` means it held nothing at all. A path whose pre-apply content
was a user's *edit* is never in a backup, because apply leaves `LOCAL_EDIT` and `CONFLICT` alone
and so never backs them up — so reading the disk back cannot turn somebody's edit into something
this tool claims to have installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_library.domain.artifact import ArtifactFile
from harness_library.domain.backup import BackupStore
from harness_library.domain.errors import BackupNotFoundError, RestoreFailedError
from harness_library.domain.hashing import content_hash_of_files
from harness_library.domain.identity import parse_artifact_id
from harness_library.domain.lock import WriteLock
from harness_library.domain.manifest import Manifest, ManifestArtifact, ManifestStore
from harness_library.domain.registry import target_path_of
from harness_library.domain.target import TargetFile, TargetRepository


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """What one rollback did. The value a caller turns into an exit status and a report.

    Attributes:
        manifest: the record now on disk, describing the **restored** state. Written after the
            restore, which is the whole ordering — see the module docstring.
        backup_id: the backup that was put back.
        restored: every target path whose bytes changed, or that appeared, in path order. The
            paths the user gets back.
        removed: every target path that the restore took away, in path order. The paths a first
            install created and R79 exists to undo.
    """

    manifest: Manifest
    backup_id: str
    restored: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


def rollback_install(
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    lock: WriteLock,
    manifest: Manifest,
    backup_id: str,
    installed_at: datetime,
) -> RollbackResult:
    """Put `backup_id` back into this target, then record the state it left behind.

    Args:
        target: contract C-12. Scanned twice — once either side of the restore — and never
            written by this module: the writing is the backup store's, which knows where the
            bytes it kept are. The first scan is for the report and the second is what the new
            manifest's digests are read from.
        backups: contract C-13. `restore` is the mechanism and this use case is the decision to
            run it, exactly as `domain/backup.py` says.
        manifests: contract C-15, where the record goes. The seam exists because `application/`
            may not import `infrastructure/`.
        lock: charter §12, ruling R50 and C-16. Held around the restore **and** the record, and
            released however the run ends. **Required, with no default** — for the reason
            `apply_install`'s is: a lock a caller may forget is a lock that is not there, and
            every gate stays green without one.
        manifest: contract C-11, what is recorded for this target now. **Not optional**: a target
            with no manifest was never installed into, so no apply ever ran and no backup of it
            can exist. It is the list of paths the new record is composed from.
        backup_id: which backup to put back. **Required, with no default** rather than taken from
            `manifest.backup_id`: `BackupStore.list()` offers the older ones too, and a caller
            choosing is the difference between undoing the last install and undoing three.
        installed_at: when this run happened, timezone-aware. A parameter and never a clock — the
            composition root owns the instant (R66), and a use case reading the wall clock would
            make every assertion about the record it writes depend on when the suite ran.

    Returns:
        `RollbackResult`, naming the backup and what moved.

    Raises:
        LockHeldError: another writer holds this target's lock. **Nothing was restored.**
        BackupNotFoundError: no backup has this id, so there is nothing to put back. Nothing was
            restored and nothing was recorded.
        RestoreFailedError: the target would not take the write. The restore may have got part of
            the way; the manifest is **not** rewritten, so nothing on disk is disowned, and
            running the same rollback again completes it — see the class.
        OSError: the manifest could not be written, after a restore that succeeded. Deliberately
            **not** `ManifestWriteError`: that code says "nothing happened", which under R63's
            ordering is what it means for an apply and is exactly false here — the target has
            already been put back. Raising a code carrying the wrong guarantee is worse than
            raising the builtin, and giving this failure a code of its own is a C-6 amendment and
            therefore a plan-level decision.
    """
    with lock.hold():
        before = _by_path(target)
        _restore(backups, backup_id)
        after = _by_path(target)

        record = _manifest_after_rollback(manifest, held=after, installed_at=installed_at)
        manifests.write(record)

        return RollbackResult(
            manifest=record,
            backup_id=backup_id,
            restored=tuple(
                path
                for path, file in sorted(after.items())
                if path not in before or before[path].sha256 != file.sha256
            ),
            removed=tuple(sorted(set(before) - set(after))),
        )


def _restore(backups: BackupStore, backup_id: str) -> None:
    """Run C-13's restore, with its two failures given codes. Ruling R83, both halves.

    `KeyError` is a judgement the store alone can make — a directory with no readable record is
    not a backup — and `OSError` is a plain OS fact. Both arrive here as builtins because the
    store raising this project's errors itself would make the translation untestable by
    pre-supplying its result (ruling R24).
    """
    try:
        backups.restore(backup_id)
    except KeyError as error:
        raise BackupNotFoundError(backup_id) from error
    except OSError as error:
        raise RestoreFailedError(backup_id, str(error)) from error


def _by_path(target: TargetRepository) -> dict[str, TargetFile]:
    """One scan, keyed by target-relative path — the key `target_path_of` produces.

    Taken twice, either side of the restore, and each one is a point-in-time snapshot (C-12): the
    *second* is what the new record's digests are read from, and the pair is what the report's
    `restored` and `removed` are derived from. A symlink carries no digest (R6), which compares
    equal to itself across the two, so a link nobody touched is not reported as restored.
    """
    return {file.path: file for file in target.scan()}


def _manifest_after_rollback(
    previous: Manifest,
    *,
    held: dict[str, TargetFile],
    installed_at: datetime,
) -> Manifest:
    """What the manifest says once the target has been put back.

    One rule, applied per file: **keep it if the target still holds it, at the digest the target
    now holds.** A path the restore removed is dropped, an artifact left with no file is dropped,
    and every kept digest is read off the disk rather than carried over from a record that
    described the state we have just undone.

    `is_text` is the one field taken from the previous record. C-12 gives a target no such field
    on purpose — a target's content is written and hashed, never searched — and charter §7 wants
    one implementation of that decision, so this does not become a second one.

    A **symlink** now sitting at a recorded path is dropped rather than recorded. `TargetFile`
    carries no digest for one (R6, R68) and `<unhashed>` is a plan-time sentinel that exists so
    the verdict rule can call a link present without calling it equal to anything; putting either
    into `ArtifactFile.sha256` would make the manifest claim a digest that nothing has.
    """
    artifacts: list[ManifestArtifact] = []
    for record in previous.artifacts:
        identity = parse_artifact_id(record.artifact_id)
        if identity is None:  # pragma: no cover - R74 makes this unconstructible
            continue
        artifact_type, name = identity
        kept: list[ArtifactFile] = []
        for file in record.files:
            found = held.get(target_path_of(artifact_type, name, file.path))
            if found is None or found.sha256 is None:
                continue
            kept.append(
                ArtifactFile(
                    path=file.path,
                    sha256=found.sha256,
                    size=found.size,
                    is_text=file.is_text,
                )
            )
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
        # `None`, not the previous value: the restored bytes came from a library state this run
        # cannot name, and C-11 makes `None` an honest answer to "which version is this" rather
        # than a missing one. Carrying the apply's sha over would name the version we just undid.
        library_git_sha=None,
        # Rollback takes no backup of its own. The way forward from a rolled-back target is an
        # install, which takes one; recording the backup we just consumed would name the state
        # this run came *from* in the field that means "the state before this run".
        backup_id=None,
        artifacts=tuple(artifacts),
    )


__all__ = ["RollbackResult", "rollback_install"]
