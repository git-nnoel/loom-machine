"""`CleanForeign` — the one command in this project that reaches outside what the tool wrote.

**Read this module docstring before changing a line of it.** Every other write in initiative 02
touches a file this tool put in the target: install writes what the library holds, uninstall
removes what the manifest records, prune removes what the manifest records and the library
dropped, rollback puts back what a backup copied. This one removes paths the library and the
manifest **both disown** — the user's `settings.json`, an editor swap file, Claude Code's own
`synced/` bucket, and whatever else lives in a real `~/.claude`. None of it is in any record this
tool keeps, and none of it can be rebuilt from one.

## The safety model is the listing, and it has two halves

**The parameter.** `remove` defaults to `False`, so the default call lists and removes nothing.
C-9 already fixes that for `FOREIGN`: *"only `clean --foreign` acts on one, and only when asked"*.
T-22's CLI shows the listing and asks; nothing here decides for the user.

**The ordering.** Inside a `remove=True` run the listing pass **finishes** before the first
delete. A run that deleted each path as it found it would produce the same report and the same
final directory, and would differ on exactly the case that matters: a failure part-way through
leaves the user with files gone and no complete statement of what was going to go. The listing is
what is handed back, the backup is taken against it, and neither is a summary written afterwards.

## The backup is the second half, and there is no third

R88, with more force than it had for uninstall. A path this tool installed can be reinstalled
from the library; a path it prunes can at least be named by the record it came from. A foreign
path can be recovered from **nothing** — so the backup taken before the first delete is the only
way back in the entire project, and a run that cannot take one does not run (`BACKUP_FAILED`).

## Ruling R44 — no named exclusion, here or anywhere

There is no `synced` in this module, no prefix test, no allow-list and no deny-list, and there
must never be one. The bucket is protected the same way the user's `settings.json` is: it appears
in the listing, the user sees it, the backup holds it, and the default removes nothing. A named
exclusion would protect one directory by name while silently hiding whatever else lands in it —
and would teach the next reader that this command has a list of things it is careful about, which
is the opposite of true.

## A foreign **directory** is never listed and never removed

C-12's scan reports files, and directories only as the prefixes of their paths. `synced/` is
therefore several leaf paths and never one tree, and `delete` refuses a directory outright. A
cleaned bucket leaves its empty directories behind — visible, harmless, removable by hand — which
is the same decision uninstall makes about an emptied artifact root. Removing a directory means
deciding that nothing else in it matters, and this is the module least entitled to decide that:
a directory that was empty a moment ago may not be by the time the removal reaches it.

## Delete, then record — charter §13b

Clean is the one run for which §13b's rule is *vacuous*: it disowns nothing, because nothing it
removes was ever owned. The record goes last anyway, and deliberately, for two reasons. It keeps
"a run that makes files disappear records last" a rule with no exceptions to remember, which is
worth more than a per-use-case judgement in a module this dangerous. And the record's `backup_id`
is a claim that this backup describes what the target held *before* this run — a claim that is
only true once the run has happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_library.domain.backup import BackupStore
from harness_library.domain.errors import (
    BackupFailedError,
    RecordStaleError,
    TargetUnwritableError,
)
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.lock import WriteLock
from harness_library.domain.manifest import Manifest, ManifestStore
from harness_library.domain.target import TargetRepository


def foreign_entries(plan: InstallPlan) -> tuple[PlanEntry, ...]:
    """Every entry this plan judges `FOREIGN`, in plan order.

    The whole of "which paths does clean act on", and it is a lookup rather than a rule: C-9's
    verdict is decided in `domain/install_plan.py`, where `FOREIGN` means *neither the library nor
    the manifest holds this path and the target does*. Nothing here narrows it, which is R44 —
    there is no name, no prefix and no exception in this function, and the one thing that keeps
    Claude Code's `synced/` bucket safe is that the user sees it in the listing first.
    """
    return tuple(entry for entry in plan.entries if entry.verdict is Verdict.FOREIGN)


@dataclass(frozen=True, slots=True)
class CleanResult:
    """What one `clean --foreign` did, or would do. The value a caller shows before it asks.

    Attributes:
        listed: **every foreign path the target holds, in plan order** — the whole statement,
            complete before a single file was touched. This is what T-22 prints and what the
            user authorises; `removed` is what came of it.
        removed: the paths actually deleted, in listing order. Empty when `remove` was `False`,
            which is the default and the safe one.
        absent: foreign paths the plan named that the target no longer held. Neither listed nor
            removed: the plan's snapshot had them and the disk does not, so naming them in the
            listing would ask the user to authorise the destruction of something that is not
            there.
        backup_id: the backup taken before the first delete, or `None` when nothing was removed.
            **The only way back from this command** — no library and no manifest describes a
            foreign path.
        manifest: the record this run wrote, or `None` when it removed nothing and therefore
            wrote none. A listing changes nothing and must leave no trace of having run.
    """

    listed: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    backup_id: str | None = None
    manifest: Manifest | None = None


def clean_foreign(
    plan: InstallPlan,
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    lock: WriteLock,
    manifest: Manifest,
    installed_at: datetime,
    remove: bool = False,
) -> CleanResult:
    """List every foreign path in the target, and — only when asked — remove them.

    Args:
        plan: what the library, the manifest and the target say, decided already. Only the
            `FOREIGN` entries are read. Clean does **not** re-scan the target: the listing the
            user authorised has to be the listing that is acted on, and a second snapshot is how
            a path nobody saw gets removed.
        target: contract C-12. Only `exists` and `delete` are called — never `scan`, which is
            the plan's job and already done.
        backups: contract C-13. Every listed path is copied before the first is removed, and a
            backup that cannot be taken stops the run (R88). Untouched when `remove` is `False`.
        manifests: contract C-15. Written once, **after** the last removal, and not at all when
            nothing was removed.
        lock: charter §12, ruling R50 and C-16. Held around the listing, the backup, the
            removals and the record. **Required, with no default**, for the reason
            `apply_install`'s is — and the listing is inside it too, because a listing taken
            while another writer is mid-apply would offer the user paths that are about to stop
            being foreign.
        manifest: contract C-11, what is recorded for this target. **Not optional**, exactly as
            uninstall's is not. A target with no manifest is not one this tool manages, and
            `clean --foreign` against it would mean "every path here is foreign, remove them
            all" — `rm -rf` reached through a plan. Answering that is the composition root's job
            and this function must not make it expressible.
        installed_at: when this run happened, timezone-aware. A parameter and never a clock
            (R66), like every other write use case's.
        remove: actually delete the listed paths. **`False` by default, which is the safe
            default and the point.** C-9 fixes it: a foreign path is acted on *only when asked*.

    Returns:
        `CleanResult`. With `remove=False` its `listed` is the answer and everything else is
        empty; with `remove=True` the two are the same set unless a removal failed.

    Raises:
        LockHeldError: another writer holds this target's lock. **Nothing was listed or
            removed** — the lock wraps the listing too.
        BackupFailedError: the backup could not be taken, so **nothing was removed**. The one
            refusal that matters most in this project: these paths have no other way back.
        TargetUnwritableError: a path could not be removed. The removals before it stand, the
            backup covers all of them, and the record is **not** written.
        RecordStaleError: the removals finished and the record could not be written (R90). The
            manifest still describes exactly what it did before — clean never disowns anything —
            so the only thing lost is the `backup_id` pointing at the way back, and
            `BackupStore.list()` still holds it.
    """
    with lock.hold():
        # 1. The listing, in full, before anything is touched. `exists` per path rather than
        #    trust in the plan's snapshot: this run is about to destroy files it cannot rebuild,
        #    so what it reports has to be a statement about what is there now.
        listed: list[str] = []
        absent: list[str] = []
        for entry in foreign_entries(plan):
            (listed if target.exists(entry.path) else absent).append(entry.path)

        if not remove or not listed:
            return CleanResult(listed=tuple(listed), absent=tuple(absent))

        # 2. The backup, against the listing exactly. R88.
        backup_id = _take_backup(backups, tuple(listed))

        # 3. The removals, in listing order.
        for path in listed:
            _delete(target, path)

        # 4. The record, last. Charter §13b; see the module docstring for why it is kept here
        #    even though clean is the one run that disowns nothing.
        record = Manifest(
            target_path=manifest.target_path,
            installed_at=installed_at,
            # Carried over: this run touched no installed file, so every artifact still recorded
            # here came from that library state and still does.
            library_git_sha=manifest.library_git_sha,
            backup_id=backup_id,
            artifacts=manifest.artifacts,
        )
        _write_record(manifests, record)

        return CleanResult(
            listed=tuple(listed),
            removed=tuple(listed),
            absent=tuple(absent),
            backup_id=backup_id,
            manifest=record,
        )


def _take_backup(backups: BackupStore, paths: tuple[str, ...]) -> str:
    """Copy every listed path before the first is removed.

    Returns a real id and never `None`, unlike prune's and uninstall's: this is only reached with
    a non-empty listing, and "the backup was skipped because there was nothing to protect" must
    not be a state a reader of this module has to hold in their head.

    Raises:
        BackupFailedError: the store could not take it. **Nothing is removed.** R88, and the
            strongest case of F-9 in the project: a foreign path is described by no library and
            no manifest, so this copy is the only record of it that will ever exist.
    """
    try:
        return backups.create(paths)
    except OSError as error:
        raise BackupFailedError(str(error)) from error


def _delete(target: TargetRepository, path: str) -> None:
    """Remove one foreign path.

    A symlink is unlinked as itself and never followed (C-12's `delete`, R6), which is what keeps
    a foreign link resolving out of the target from turning this command into a delete somewhere
    else on the machine entirely.

    Raises:
        TargetUnwritableError: it could not be removed — including a directory, which C-12
            refuses, and which nothing in the listing can be.
    """
    try:
        target.delete(path)
    except OSError as error:
        raise TargetUnwritableError(path, str(error)) from error


def _write_record(manifests: ManifestStore, record: Manifest) -> None:
    """Record the run, **after the last removal**. Charter §13b.

    Raises:
        RecordStaleError: it could not be written (R90). The files are already gone.
    """
    try:
        manifests.write(record)
    except OSError as error:
        raise RecordStaleError("clean", str(error)) from error


__all__ = ["CleanResult", "clean_foreign", "foreign_entries"]
