"""`PlanInstall` and `ApplyInstall` — deciding what an install does, and doing it.

**This module is in `application/write/` and that placement is the whole guarantee.** The
`mcp-is-read-only` import contract forbids `mcp/` from reaching `application.write`, and the MCP
server imports `application.read` alone. A write use case sitting in `read/` keeps `mypy`, `ruff`
and `lint-imports` all green while quietly making a read-only session able to reach the write
path — nothing in the toolchain can see the mistake, so
`tests/test_architecture.py::test_every_write_use_case_is_defined_in_the_write_package` is the one
thing that does.

**Why `plan_install` is a separate symbol from `diff_against_target` rather than an alias.** They
answer the same question and share one implementation — the composition lives on the read side
because `read/` may not import `write/` (see `read/drift.py`). What differs is what they are
*for*: a drift report **describes**, and this is the value apply **executes**. Every narrowing
that belongs to acting rather than to describing lands here and must not reach the report.
Ruling R75 is the first of them: an artifact that does not validate is refused, as `SKIPPED` with
a reason naming the rule, and `force=True` is that narrowing simply not applied. T-20's V11
refusal and T-21's `--resolve` land in the same place. An alias would have nowhere to put them.

## Ruling R63 — back up, write the manifest, write the files

The order is the point of this module, and writing the manifest **last** is the failure it exists
to prevent.

A crash between the last file and the manifest leaves the target modified with no record of what
was put there. Every installed path then reads `FOREIGN` on the next scan: install will not touch
a foreign path and uninstall cannot remove one, so the user's harness holds files that nothing
this initiative ships can manage — an unrecoverable outcome produced by a power cut.

A manifest written first can only ever **over**-claim, and an over-claim is self-correcting. A
path the manifest names that was never written comes back `LOCAL_EDIT` or `CONFLICT` on the next
`hl diff`, which is a decision the user is *asked* to make rather than a file that quietly
escapes. Under this ordering `MANIFEST_UNWRITABLE` therefore always means **nothing happened**.

**There is no rollback here.** A failure part-way through leaves every file before it written
and the manifest already on disk — the accepted over-claim above. Undoing that is T-18's
rollback, from the backup this module refuses to run without.

## What is written, per verdict

| Verdict | Apply |
|---|---|
| `CREATE`, `UPDATE` | written |
| `MANIFEST_REPAIR` | **no file is touched**; only the manifest changes, which is the repair |
| `UNCHANGED` | nothing to do; recorded in the manifest as installed |
| `FOREIGN` | untouched and unrecorded, always (F-10, R44) |
| `LOCAL_EDIT`, `CONFLICT`, `SKIPPED` | left alone, named in the result; `INCOMPLETE` (R48, R57) |
| `PRUNE` | deleted **only** when pruning is asked for |

**What the new manifest records for a path apply did not write is what the previous manifest
recorded** — never the library's digest. Writing the library's digest for a conflicted path would
claim this tool installed something it did not, turning a three-way `CONFLICT` into a
two-way `LOCAL_EDIT` on the next run and losing the very fact the user has to resolve.

## Ruling R50 — one writer per target, and the lock wraps all of it

`apply_install` takes a `WriteLock` and holds it around **every** one of the five steps above,
the failures included. Two applies interleaving against one target can write half of each plan's
files and leave a manifest describing neither: a state no verdict in C-9 can express and no
command in this initiative can repair. The realistic case is `hl install` in two terminals.

The lock is a **required keyword-only parameter with no default**, for the reason `manifest` is:
a default would make running unlocked a typo rather than a decision, and the composition root is
not where this can live — T-18 adds two more write use cases and a lock a caller may forget is a
lock that is not there.

It is taken **before the backup**, which is the first thing this function does to a disk, and
released in a `finally` inside the lock's own context manager. A lock leaked on the error path is
worse than no lock, because it only bites after something has already gone wrong.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import NamedTuple

from harness_library.application.read._access import read_file_bytes
from harness_library.application.read.drift import diff_against_target
from harness_library.application.write.prune import pruned_entries
from harness_library.domain.artifact import Artifact, ArtifactFile
from harness_library.domain.backup import BackupStore
from harness_library.domain.errors import (
    BackupFailedError,
    ManifestWriteError,
    TargetUnwritableError,
)
from harness_library.domain.hashing import content_hash_of_files
from harness_library.domain.identity import parse_artifact_id
from harness_library.domain.install_plan import (
    BLOCKING_VERDICTS,
    InstallPlan,
    PlanEntry,
    Verdict,
)
from harness_library.domain.lock import WriteLock
from harness_library.domain.manifest import Manifest, ManifestArtifact, ManifestStore
from harness_library.domain.registry import target_path_of
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.target import TargetRepository

WRITTEN_VERDICTS: frozenset[Verdict] = frozenset({Verdict.CREATE, Verdict.UPDATE})
"""The verdicts whose file apply writes. Two, and neither of them is a judgement call.

`CREATE` is a path the target does not hold, and `UPDATE` is one holding exactly what this tool
last installed — so in both cases there is no edit of the user's to lose. Everything else is
either already correct (`UNCHANGED`), a manifest-only repair, someone else's file (`FOREIGN`), or
a decision the user has to make first. `MANIFEST_REPAIR` is deliberately absent: it is the one
verdict whose whole point is that the files are already right.
"""

RECORDED_VERDICTS: frozenset[Verdict] = frozenset(
    {Verdict.CREATE, Verdict.UPDATE, Verdict.UNCHANGED, Verdict.MANIFEST_REPAIR}
)
"""The verdicts whose path the new manifest records at the **library's** digest.

A superset of `WRITTEN_VERDICTS` by two: after this run the target holds the library's bytes at an
`UNCHANGED` path because it already did, and at a `MANIFEST_REPAIR` path because it already did
and only the record was stale — which is exactly what the repair repairs.

Every other path the manifest ends up naming keeps the digest the *previous* manifest gave it.
That is not a fallback, it is the rule: the manifest says what this tool put there, and a path it
did not touch still holds whatever it last put there.
"""


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """What one apply did. The value a caller turns into an exit status.

    Attributes:
        manifest: the record now on disk. Written **before** the first file (R63), so this is a
            claim about the run's intent; the three path tuples below say what came of it.
        backup_id: the backup taken before anything was written, or `None` when the run had
            nothing to write or delete and so had nothing to protect.
        written: the target-relative paths written, in plan order.
        deleted: the target-relative paths removed, in plan order. Empty unless pruning was asked
            for — install never removes a path on its own initiative.
        left_alone: every entry apply refused to act on, with the `reason` that came with it. The
            user is being asked to decide something, and this is the list they decide about.
    """

    manifest: Manifest
    backup_id: str | None = None
    written: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    left_alone: tuple[PlanEntry, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Whether every entry was applied. `False` means exit `INCOMPLETE = 6` (R57).

        Derived rather than stored, for the reason `InstallPlan.is_complete` is: a stored flag
        that can disagree with the list beside it is the drift both contracts exist to prevent.
        **Not a failure** — everything safe was written and nothing was destroyed.
        """
        return not self.left_alone


def plan_install(
    library: ArtifactRepository,
    target: TargetRepository,
    *,
    manifest: Manifest | None,
    force: bool = False,
) -> InstallPlan:
    """The plan an apply would execute. Contract C-10, plus ruling R75's refusal.

    Args:
        library: contract C-4, the library being installed from.
        target: contract C-12, the directory being installed into. Only `scan()` is called;
            planning writes nothing.
        manifest: contract C-11, what was last installed into this target, or `None` when nothing
            was. **Required, with no default.** A caller that omitted it would judge every path
            `CREATE` and overwrite the whole target, which is the failure the manifest exists to
            prevent, and a default would let that be a typo rather than a decision.
        force: install an artifact that does not validate anyway. **Ruling R75**: by default an
            artifact carrying an ERROR finding comes back `SKIPPED`, with a reason naming the
            codes that fired, and is not written. A WARNING never refuses anything (R22) — charter
            §8 made V6 a warning precisely so that reporting an editor swap file cannot stop an
            install. This is the parameter behind `hl install --force`; the flag is T-22's.

    Returns:
        One `PlanEntry` per path the library, the manifest or the target holds, in path order.
        `InstallPlan.is_complete` is false when any of them awaits a human decision, and
        `counts` is dense over every verdict.

    Raises:
        ValueError: the manifest records an `artifact_id` that is not a `<type>/<name>` identity,
            so the files it names cannot be located inside the target. Since ruling R74 this can
            no longer come from a `Manifest` the store read — the entity rejects it first, and the
            store renders that as a located `ManifestError`.
    """
    plan = diff_against_target(library, target, manifest=manifest)
    if force:
        return plan
    return _refuse_artifacts_that_do_not_validate(plan, library.list_all())


def apply_install(
    plan: InstallPlan,
    library: ArtifactRepository,
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    lock: WriteLock,
    manifest: Manifest | None,
    target_path: str,
    installed_at: datetime,
    library_git_sha: str | None = None,
    prune: bool = False,
) -> ApplyResult:
    """Execute `plan`, under this target's write lock. **Back up, manifest, files** — R63, R50.

    The module docstring argues the order at length; the short form is that a manifest written
    first can only over-claim and an over-claim is self-correcting, while a manifest written last
    can lose a user's files to a power cut with no way back.

    Args:
        plan: what to do, decided already. Apply does **not** re-scan the target: a second
            snapshot disagreeing with the first is how a path gets written on the strength of a
            verdict decided about a different file.
        library: contract C-4, where the bytes come from.
        target: contract C-12, the directory being written. Only `write` and `delete` are called.
        backups: contract C-13. Every path this run will write or delete is copied first, and a
            backup that cannot be taken stops the run before anything is touched (F-9).
        manifests: where the new record goes. The seam that exists because `application/` may not
            import `infrastructure/` and R63 makes the manifest write a step of this function.
        lock: charter §12, ruling R50. Held around the whole run — the backup, the manifest and
            every file — and released however the run ends. **Required, with no default**, for
            the reason `manifest` is: a default would make an unlocked apply a typo rather than a
            decision, and this is the one operation in the project that destroys data.
        manifest: contract C-11, what was last installed here, or `None` for a first install.
            **Required, with no default** — the same rule `plan_install` keeps, and for a sharper
            reason: this is what every path apply does *not* write keeps its digest from, so a
            caller that omitted it would silently drop every conflicted artifact's record and
            orphan its files.
        target_path: the absolute directory being installed into, as text. Recorded in the
            manifest and used by the store to key it; a first install has no previous manifest to
            take it from.
        installed_at: when this run happened, timezone-aware. A parameter and not a clock call:
            the composition root owns the instant, and a use case that read the wall clock would
            make every assertion about the record it writes depend on when the suite ran.
        library_git_sha: the library's commit, or `None` when it is not a clean work tree.
        prune: remove the paths the manifest records and the library no longer holds. Off by
            default — install removing a file nobody asked it to remove is the behaviour this
            product exists to replace.

    Returns:
        `ApplyResult`, whose `is_complete` is what a caller exits `INCOMPLETE = 6` from.

    Raises:
        LockHeldError: another writer holds this target's lock. **Nothing was written and nothing
            was backed up** — the lock is taken before the first of the three steps.
        BackupFailedError: the backup could not be taken. **Nothing was written.**
        ManifestWriteError: the manifest could not be written. **Nothing was written** — under
            R63 this failure always precedes the first file.
        TargetUnwritableError: a path could not be written or removed. The manifest is already on
            disk and the files before this one are already written; see the module docstring.
        ArtifactFileNotFoundError: a file the plan names is no longer in the library — a torn read
            between the scan and the apply, which charter §7 states as a limitation of a
            single-user tool rather than one it locks against.
        ValueError: an entry to be written belongs to no artifact the library holds. Unreachable
            from a plan this library produced, and a bare `ValueError` for that reason: it means
            the plan and the library are from two different runs, which is a bug and not a user's
            mistake.
    """
    with lock.hold():
        return _apply(
            plan,
            library,
            target,
            backups,
            manifests,
            manifest=manifest,
            target_path=target_path,
            installed_at=installed_at,
            library_git_sha=library_git_sha,
            prune=prune,
        )


def _apply(
    plan: InstallPlan,
    library: ArtifactRepository,
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    manifest: Manifest | None,
    target_path: str,
    installed_at: datetime,
    library_git_sha: str | None,
    prune: bool,
) -> ApplyResult:
    """R63's five steps, with the lock already held. Split out so the lock wraps every one of them.

    A separate function rather than an indented block, because the boundary is what is being
    guaranteed: nothing this function does can be reached without going through `apply_install`'s
    `with`, and a step added here is inside the lock by construction rather than by remembering.
    """
    written_entries = tuple(entry for entry in plan.entries if entry.verdict in WRITTEN_VERDICTS)
    # `pruned_entries`, not a second comprehension: `hl prune` removes the same paths through
    # the same function, and two spellings of "what --prune removes" would agree until one of
    # them grew a narrowing the other did not (T-19).
    deleted_entries = pruned_entries(plan) if prune else ()
    left_alone = tuple(entry for entry in plan.entries if entry.verdict in BLOCKING_VERDICTS)
    sources = _library_sources(library.list_all())

    # 1. Back up every path this run will write or delete — including the ones the target does
    #    not hold yet, so that undoing a first install means removing what it created.
    backup_id = _take_backup(backups, written_entries + deleted_entries)

    # 2. Then the manifest, and only then a file. Ruling R63; see the module docstring.
    record = _manifest_after(
        plan,
        sources=sources,
        previous=manifest,
        removed=frozenset(entry.path for entry in deleted_entries),
        target_path=target_path,
        installed_at=installed_at,
        library_git_sha=library_git_sha,
        backup_id=backup_id,
    )
    _write_manifest(manifests, record)

    # 3. The files. A failure here leaves the manifest over-claiming, which is the accepted cost.
    for entry in written_entries:
        _write_file(target, library, sources, entry)
    for entry in deleted_entries:
        _delete_file(target, entry)

    return ApplyResult(
        manifest=record,
        backup_id=backup_id,
        written=tuple(entry.path for entry in written_entries),
        deleted=tuple(entry.path for entry in deleted_entries),
        left_alone=left_alone,
    )


# ------------------------------------------------------------------------------------------------
# Ruling R75 — an artifact that does not validate is not installed
# ------------------------------------------------------------------------------------------------


def _refuse_artifacts_that_do_not_validate(
    plan: InstallPlan, artifacts: Iterable[Artifact]
) -> InstallPlan:
    """Replace the verdict of every library-held path of an invalid artifact with `SKIPPED`.

    **Library-held only.** A `FOREIGN` path sitting under the same artifact root is not refused:
    install never writes or removes a foreign path anyway, and calling one `SKIPPED` would claim
    the user owes a decision about a file this tool has no opinion on. A `PRUNE` path cannot
    arise — an artifact the library no longer holds carries no findings to refuse it by.

    The original verdict is **replaced**, including a `CONFLICT`'s reason. That is deliberate: the
    refusal outranks the conflict, because an artifact that does not validate must not be
    installed by resolving it either, and nothing is lost — `force=True` skips this narrowing
    entirely and the plan comes back with every original verdict and reason intact.
    """
    refused = {
        artifact.id: _refusal_reason(artifact) for artifact in artifacts if not artifact.is_valid
    }
    if not refused:
        return plan
    return InstallPlan(entries=tuple(_refused_or(entry, refused) for entry in plan.entries))


def _refused_or(entry: PlanEntry, refused: Mapping[str, str]) -> PlanEntry:
    """`entry` as `SKIPPED`, or `entry` unchanged."""
    if entry.library_sha is None or entry.artifact_id is None:
        return entry
    reason = refused.get(entry.artifact_id)
    if reason is None:
        return entry
    return replace(entry, verdict=Verdict.SKIPPED, reason=reason)


def _refusal_reason(artifact: Artifact) -> str:
    """Why this artifact is refused, **naming the rules that fired**.

    The codes rather than the messages: charter §8's register is the contract, a consumer branches
    on a code, and a user who is told "V1" can look up the one rule they have to fix. Sorted and
    deduplicated so two runs over one library produce the same sentence.
    """
    codes = ", ".join(sorted({finding.code.value for finding in artifact.errors}))
    return (
        f"{artifact.id} does not validate: {codes}. Install refuses an artifact whose errors it "
        "cannot judge the consequences of; --force installs it anyway"
    )


# ------------------------------------------------------------------------------------------------
# The three writes, each with its own refusal
# ------------------------------------------------------------------------------------------------


def _take_backup(backups: BackupStore, entries: tuple[PlanEntry, ...]) -> str | None:
    """Copy every path this run will touch, before it touches one. `None` when it touches none.

    Deduplicated but not sorted: the plan is already in path order, and a backup listing that
    reordered its own paths would be harder to compare against the plan that produced it.

    Raises:
        BackupFailedError: the store could not take it. Nothing is written — a write with no way
            back is the failure mode this initiative exists to remove (F-9).
    """
    paths = tuple(dict.fromkeys(entry.path for entry in entries))
    if not paths:
        return None
    try:
        return backups.create(paths)
    except OSError as error:
        raise BackupFailedError(str(error)) from error


def _write_manifest(manifests: ManifestStore, manifest: Manifest) -> None:
    """Record the run, **before the first file**. Ruling R63.

    Raises:
        ManifestWriteError: it could not be written, so nothing was installed. That guarantee is
            what this line's position in `apply_install` buys, and moving it below the file loop
            would take it away without failing a type check.
    """
    try:
        manifests.write(manifest)
    except OSError as error:
        raise ManifestWriteError(str(error)) from error


def _write_file(
    target: TargetRepository,
    library: ArtifactRepository,
    sources: Mapping[str, _Source],
    entry: PlanEntry,
) -> None:
    """Put one library file at its target path.

    Raises:
        ValueError: nothing in the library lands at this path. See `apply_install`.
        TargetUnwritableError: the target refused the write.
    """
    source = sources.get(entry.path)
    if source is None:
        raise ValueError(
            f"the plan writes {entry.path!r}, which no artifact in this library produces. The "
            "plan and the library are from two different runs; nothing can be written for it"
        )
    data = read_file_bytes(library, source.artifact_id, source.file.path)
    try:
        target.write(entry.path, data)
    except OSError as error:
        raise TargetUnwritableError(entry.path, str(error)) from error


def _delete_file(target: TargetRepository, entry: PlanEntry) -> None:
    """Remove one pruned path.

    Raises:
        TargetUnwritableError: it could not be removed — including a path that is already gone,
            which is a target that changed under the plan and not something to pass over quietly.
    """
    try:
        target.delete(entry.path)
    except OSError as error:
        raise TargetUnwritableError(entry.path, str(error)) from error


# ------------------------------------------------------------------------------------------------
# The record this run leaves behind
# ------------------------------------------------------------------------------------------------


class _Source(NamedTuple):
    """One library file and the artifact it belongs to, keyed elsewhere by its target path."""

    artifact_id: str
    file: ArtifactFile


def _library_sources(artifacts: Iterable[Artifact]) -> dict[str, _Source]:
    """Every file the library would install, keyed by where it lands in the target.

    The **same forward join** the plan was built from, `registry.target_path_of`, and deliberately
    not an inverse of it: `PlanEntry.path` cannot be turned back into an artifact-root-relative
    path without knowing the artifact's kind, and a second implementation of the layout is exactly
    what ruling R73 put that function in the registry to prevent.

    First claim wins, as in `read/drift.py`: two artifacts cannot normally claim one target path,
    and a library that managed it is a library-level fault rather than a write to do twice.
    """
    found: dict[str, _Source] = {}
    for artifact in artifacts:
        for file in artifact.files:
            found.setdefault(
                target_path_of(artifact.type, artifact.name, file.path),
                _Source(artifact.id, file),
            )
    return found


def _manifest_after(
    plan: InstallPlan,
    *,
    sources: Mapping[str, _Source],
    previous: Manifest | None,
    removed: frozenset[str],
    target_path: str,
    installed_at: datetime,
    library_git_sha: str | None,
    backup_id: str | None,
) -> Manifest:
    """What the manifest says once this run has happened.

    Per path, one of three things:

    * apply put the library's bytes there, or they were already there — the library's digest;
    * apply left it alone — **whatever the previous manifest said**, unchanged, so a conflicted
      artifact keeps its record and its installed files stay prunable and uninstallable rather
      than becoming `FOREIGN`;
    * it was pruned, or it is foreign — recorded nowhere.

    A path the library holds that apply did not write **and** the previous manifest did not record
    is recorded nowhere either: nothing installed it, so there is nothing to remember about it.

    Composed rather than edited from the previous manifest, so that a record for an artifact whose
    every path has left is dropped instead of lingering as an empty entry.
    """
    kept = _previous_by_target_path(previous)
    recorded: dict[str, dict[str, ArtifactFile]] = {}

    for entry in plan.entries:
        if entry.path in removed:
            continue
        held = sources.get(entry.path)
        if held is not None and entry.verdict in RECORDED_VERDICTS:
            recorded.setdefault(held.artifact_id, {})[held.file.path] = held.file
            continue
        previously = kept.get(entry.path)
        if previously is not None:
            recorded.setdefault(previously.artifact_id, {})[previously.file.path] = previously.file

    return Manifest(
        target_path=target_path,
        installed_at=installed_at,
        library_git_sha=library_git_sha,
        backup_id=backup_id,
        artifacts=tuple(
            ManifestArtifact(
                artifact_id=artifact_id,
                content_hash=content_hash_of_files(files.values()),
                files=tuple(files.values()),
            )
            for artifact_id, files in recorded.items()
            if files
        ),
    )


def _previous_by_target_path(previous: Manifest | None) -> dict[str, _Source]:
    """The previous manifest's files, keyed by target path — the same key the plan uses.

    Through `target_path_of` again, because C-11 stores no target-relative path on purpose: one
    copy per file would repeat the prefix N times and one per artifact would be a second source of
    truth for a layout `TypeSpec` already owns.

    Every id here parses: ruling R74 put that guard on `ManifestArtifact` itself, so a manifest
    holding an unjoinable record cannot be constructed and cannot be read back off disk. The
    narrowing below is for the type, not for a state.
    """
    found: dict[str, _Source] = {}
    if previous is None:
        return found
    for record in previous.artifacts:
        identity = parse_artifact_id(record.artifact_id)
        if identity is None:  # pragma: no cover - R74 makes this unconstructible
            continue
        artifact_type, name = identity
        for file in record.files:
            found.setdefault(
                target_path_of(artifact_type, name, file.path),
                _Source(record.artifact_id, file),
            )
    return found


__all__ = ["ApplyResult", "apply_install", "plan_install"]
