"""`--resolve` — the other half of every refusal this initiative can produce. Ruling **R54**.

Apply leaves a `LOCAL_EDIT` or a `CONFLICT` untouched and exits `INCOMPLETE = 6` (R48, R57). That
posture is right and it is only half a tool: **a refusal with no resolution path is a dead end**,
and until this module landed that is what `loom install` shipped. R48 chose "refuse and say why"
over prompting and over overwriting on the argument that the user should decide; a user who cannot
then act on the decision has been handed a worse tool, not a safer one.

## Two use cases, because they are two shapes

`resolve_conflict` chooses a side and ends in a record. `compare_versions` opens both versions in
`$EDITOR` and ends in nothing changing. A single function would have to return *"I wrote a file and
a record"* or *"I showed you two blobs"*, and this package already splits far smaller differences
than that — prune, clean and uninstall are three modules because they record at different ends of
a run.

`Resolution` has **two** members and not three. It names a *side*, and the only two sides that
exist are the library's version and the target's. `$EDITOR` is not a third: it decides nothing, and
the decision the user reaches is spelled as one of the two. T-22 owns the flag with three
spellings; this layer owns the two operations behind it.

**No merge, and nothing is read back from the editor.** Spec §8.5 and the plan's Deferred section
say never. Writing back whatever a user left in the buffer would put a third version — one neither
side holds — into the target and into the record, as if this tool had installed it. That is a
larger claim than `resolve target`'s and nobody asked for it.

## Per artifact, never per run

The entries acted on are exactly those whose `artifact_id` is the one named. Resolving one of two
conflicts leaves the other refused, its file byte-identical and its record untouched, and the run
is still incomplete until none remain. That is what makes `--resolve` a decision about a thing the
user looked at rather than a switch that turns the whole refusal posture off.

## What each side means, per conflict shape

`RESOLVABLE_VERDICTS` is `{LOCAL_EDIT, CONFLICT}` — `BLOCKING_VERDICTS` without `SKIPPED`, which is
**ruling R99**: a symlinked artifact root was never scanned, so the library holds no bytes for it
and there are no two versions to choose between. `--resolve` does not lift V11 any more than
`--force` does. A `SKIPPED` entry comes back in `left_alone` carrying its own V11 reason, which is
the same answer apply gives and is the actionable one.

| Which sides hold the path | `library` | `target` |
|---|---|---|
| all three, or a `LOCAL_EDIT` | written; library's digest | nothing written; target's digest |
| the manifest never recorded it | written; library's digest | target's digest, library's path |
| the target lost it | written; library's digest | **dropped** — what is on disk is nothing |
| the library dropped it | **refused** | target's digest; the path becomes `PRUNE` |
| `UNHASHED_TARGET_SHA` (R72) | **refused** | **refused** |

**Why taking the library's side is refused where the library holds nothing.** It could only mean
*deleting a file the user has edited*, which would make this one function both create and destroy
files — and a function that does both has to hold two record orderings and choose between them at
runtime (charter §13b), which is the one thing R63's position in `apply_install` exists to make
impossible. It is not a dead end: `resolve target` resolves that shape, the path then reads `PRUNE`,
and `--prune` removes it under its own record-last ordering. The reason on the refused entry says
so.

**Why an unreadable target path is refused by both sides (R72).** `UNHASHED_TARGET_SHA` means a
symlink sits there: the target holds the path and its content was never read. Taking the library's
side would write *through* the link — C-12 refuses that outright and R6 is why. Taking the target's
side would mean recording a digest of content nobody read, and `<unhashed>` is a plan-time sentinel
rather than a digest; putting it into `ArtifactFile.sha256` would make the manifest claim a digest
nothing has, which is the rule `rollback` already keeps. `compare_versions` **does** show such a
path — the library's version, with the target side named unreadable rather than absent, because
those are two different facts and `UNHASHED_TARGET_SHA` exists to carry the difference.

## What `resolve target` records, and why it is the sharp one

**The target's current bytes.** The path is read through C-12 at resolve time and both `sha256` and
`size` come from that read, so the record describes what is actually there rather than a digest
from a snapshot taken earlier. `is_text` is **carried** — from the previous record if there is one
and from the library's `ArtifactFile` otherwise — because charter §7 keeps one implementation of
that decision, it is `infrastructure.scanner.is_text`, and `application/` may not import
`infrastructure/`.

This is the one operation in the initiative that makes the tool **claim a file it did not put
there**. That is correct: the user is saying *this is now the installed version*. It is also why it
must do exactly that and nothing more — one artifact, its refused paths, no file touched.

## Ruling R86 — the record ordering, for each of the two

**`resolve library` makes files appear, so the record goes first**, which is apply's ordering and
apply's argument. A crash between them can only leave the record over-claiming, and an over-claim
returns as `LOCAL_EDIT` on the next diff — a decision the user is asked about. The other order
would leave a written file claimed by nobody: `FOREIGN`, which install will not touch and uninstall
cannot remove. So `MANIFEST_UNWRITABLE = 11` keeps its promise here too — **nothing happened** — and
there is no `RecordStaleError` anywhere in this module, because nothing here records after a file
has moved.

**`resolve target` moves no file at all, and that is the answer to the ordering question rather
than an evasion of it.** Charter §13b constrains the *interval* between the record and the file
movement: the manifest must never disown a file that is still on disk. With no file movement there
is no interval and no end of the run to put the record at — the record is the whole run. A crash
before it leaves the path refused exactly as it was; a crash after it is the completed operation.
The one thing it does that resembles disowning — dropping a path the target no longer holds —
disowns nothing, because there is nothing on disk to disown.

## Ruling R88 — the backup

`resolve library` takes one, of exactly the paths it will write, and refuses to run without it.
Against: the user named this artifact and this side, so the overwrite is deliberate and a copy of
what they asked to discard is ceremony. For: this is the **only** operation in the project that
destroys an edit of the user's — apply refuses precisely these paths for that reason — and `loom
uninstall` is every bit as deliberate and takes one anyway. F-9's sentence applies here without
modification, so it takes one.

`resolve target` takes **none**. It writes no file, so there is no target path whose bytes could be
copied; the only thing that changes is a record, and no backup in this project describes one.

## Ruling R82 — both take the lock

Required, keyword-only, no default, for the reason `apply_install`'s is. `compare_versions`
mutates nothing and takes one anyway, which is not ceremony: while the user is looking at two
versions of a path, no apply may move it underneath them. The cost is that the lock is held for as
long as the editor runs, so a concurrent `loom install` exits `LOCK_HELD = 10` — the right answer,
and the reason the sentinel is stale-broken by a pid check.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import NamedTuple

from loom.application.read._access import read_file_bytes
from loom.application.read.drift import UNHASHED_TARGET_SHA
from loom.domain.artifact import ArtifactFile
from loom.domain.backup import BackupStore
from loom.domain.errors import (
    BackupFailedError,
    ManifestWriteError,
    NothingToResolveError,
    TargetUnreadableError,
    TargetUnwritableError,
)
from loom.domain.hashing import content_hash_of_files, hash_bytes
from loom.domain.identity import ArtifactType, parse_artifact_id
from loom.domain.install_plan import (
    RESOLVABLE_VERDICTS,
    InstallPlan,
    PlanEntry,
    Verdict,
)
from loom.domain.lock import WriteLock
from loom.domain.manifest import Manifest, ManifestArtifact, ManifestStore
from loom.domain.registry import target_path_of
from loom.domain.repository import ArtifactRepository
from loom.domain.resolution import ConflictEditor, ConflictVersions, Resolution
from loom.domain.target import TargetRepository


@dataclass(frozen=True, slots=True)
class ResolveResult:
    """What one resolution did. The value a caller turns into an exit status and a report.

    Attributes:
        artifact_id: the artifact whose refused paths this run decided.
        resolution: which side was taken.
        manifest: the record now on disk, or `None` when the run resolved nothing and therefore
            wrote none. `CleanResult.manifest`'s rule, for `CleanResult`'s reason: a run that
            changed nothing must leave no trace of having run, and a target that had no manifest
            must not acquire one from a resolution that resolved nothing.
        backup_id: the backup taken before the first write, or `None`. Always `None` for a
            `TARGET` resolution, which writes no file and so has nothing to protect (R88).
        written: the target paths written, in plan order. Empty for a `TARGET` resolution.
        repaired: the target paths whose record now carries the **target's** digest, in plan
            order. Empty for a `LIBRARY` resolution — there the record carries the library's, and
            those paths are in `written`.
        dropped: the target paths dropped from the record because the target no longer holds
            them. Only a `TARGET` resolution produces one: keeping what is on disk, where what is
            on disk is nothing, is a record that stops naming the path.
        left_alone: every refused entry this run would not act on, with the reason. A `SKIPPED`
            artifact keeps its own V11 reason (R99); the other two refusals carry one written
            here, naming the side that *can* resolve them.
    """

    artifact_id: str
    resolution: Resolution
    manifest: Manifest | None = None
    backup_id: str | None = None
    written: tuple[str, ...] = ()
    repaired: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    left_alone: tuple[PlanEntry, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Whether every refused path of this artifact was decided.

        Derived rather than stored, for the reason `ApplyResult.is_complete` is. `False` means the
        caller still exits `INCOMPLETE = 6`: a V11 skip or a shape this side cannot take is still
        a decision the user owes.
        """
        return not self.left_alone


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """What one `$EDITOR` comparison showed. Nothing was written and nothing was recorded.

    Attributes:
        artifact_id: the artifact whose refused paths were shown.
        compared: the target paths handed to the editor, in plan order. A path whose target side
            is unreadable (R72) **is** here: the library's version is still worth seeing, and the
            missing side is named rather than silently blank.
        left_alone: the refused entries that could not be shown at all — a `SKIPPED` artifact,
            whose root was never scanned, so neither side has bytes (R99).
    """

    artifact_id: str
    compared: tuple[str, ...] = ()
    left_alone: tuple[PlanEntry, ...] = ()


def resolve_conflict(
    plan: InstallPlan,
    library: ArtifactRepository,
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    lock: WriteLock,
    manifest: Manifest | None,
    artifact_id: str,
    resolution: Resolution,
    target_path: str,
    installed_at: datetime,
    library_git_sha: str | None = None,
) -> ResolveResult:
    """Decide one artifact's refused paths, one way. Feature F-15, ruling R54.

    Args:
        plan: what the library, the manifest and the target say, decided already. Only this
            artifact's `LOCAL_EDIT`, `CONFLICT` and `SKIPPED` entries are read. Resolve does
            **not** re-scan: a second snapshot disagreeing with the first is how a path gets
            overwritten on the strength of a verdict decided about a different file.
        library: contract C-4. Where the bytes come from under `LIBRARY`, and where the
            artifact-root-relative path and `is_text` come from under either.
        target: contract C-12. `write` under `LIBRARY`; `read_bytes` under `TARGET`, which is how
            the record learns what is actually on disk.
        backups: contract C-13. Every path a `LIBRARY` resolution will write is copied first, and
            a backup that cannot be taken stops the run before anything is touched (F-9, R88). A
            `TARGET` resolution never reaches it.
        manifests: contract C-15, where the new record goes.
        lock: charter §12, C-16, ruling R82. Held around the backup, the record and every write.
            **Required, with no default**, for the reason `apply_install`'s is.
        manifest: contract C-11, what is recorded for this target, or `None` when nothing was
            installed here yet. **Required, and `None` is a real value**: the commonest first-run
            conflict is a target that already holds a hand-copied file no manifest records, and a
            resolution is exactly how a user settles it.
        artifact_id: the `<type>/<name>` to decide. **Exactly one artifact** — resolution is per
            artifact and never per run (R54), so another artifact's conflict is left refused.
        resolution: which side to take. See the module docstring's table.
        target_path: the absolute directory being resolved in, as text. Recorded in the manifest
            and used by the store to key it; a target with no previous manifest has none to take
            it from.
        installed_at: when this run happened, timezone-aware. A parameter and never a clock
            (R66), like every other write use case's.
        library_git_sha: the library's commit, or `None`. Recorded under `LIBRARY`, which really
            does install from that library state. **Not applicable under `TARGET`**, which
            installs nothing: that record keeps whatever the previous manifest said, because this
            run did not move any artifact's provenance.

    Returns:
        `ResolveResult`, whose `is_complete` is what a caller exits `INCOMPLETE = 6` from.

    Raises:
        LockHeldError: another writer holds this target's lock. **Nothing was written.**
        NothingToResolveError: this plan refuses nothing about this artifact. Loud rather than a
            quiet no-op (charter §13): the user has just been told a run was incomplete, so
            "there was nothing to decide" is news.
        BackupFailedError: the backup could not be taken, so **nothing was written**.
        ManifestWriteError: the record could not be written. **Nothing was written** — under this
            module's ordering that guarantee holds for both resolutions.
        TargetUnreadableError: a path a `TARGET` resolution had to read could not be read. Nothing
            was written and no record was made; this is ruling R81's code finally reaching an
            emitter.
        TargetUnwritableError: a path could not be written. The record is already on disk and the
            files before this one are already written — R63's accepted over-claim.
        ArtifactFileNotFoundError: a file the plan names is no longer in the library — a torn read
            between the scan and this run (charter §7).
    """
    with lock.hold():
        return _resolve(
            plan,
            library,
            target,
            backups,
            manifests,
            manifest=manifest,
            artifact_id=artifact_id,
            resolution=resolution,
            target_path=target_path,
            installed_at=installed_at,
            library_git_sha=library_git_sha,
        )


def compare_versions(
    plan: InstallPlan,
    library: ArtifactRepository,
    target: TargetRepository,
    editor: ConflictEditor,
    *,
    lock: WriteLock,
    artifact_id: str,
) -> ComparisonResult:
    """Show both versions of every refused path of one artifact, and change nothing. R54.

    The third way `--resolve` is spelled, and the one that decides nothing. Both versions go to
    the editor together, because an artifact's refused paths are one decision and answering it one
    `$EDITOR` invocation at a time would be answering a question this tool never asked. **Nothing
    is read back** — see the module docstring.

    Args:
        plan: as `resolve_conflict`'s. Only this artifact's refused entries are read.
        library: contract C-4, where the library's side comes from.
        target: contract C-12, where the target's side comes from. `read_bytes` only; this use
            case writes nothing, and the write recorder in the suite proves it.
        editor: the `ConflictEditor` seam. A protocol and not `subprocess`, because a test that
            launched `$EDITOR` would hang CI on a buffer nobody closes.
        lock: charter §12, C-16, ruling R82. **Required, with no default.** This use case mutates
            nothing and holds the lock anyway: while the user is looking at two versions of a
            path, no apply may move it underneath them. See the module docstring for the cost.
        artifact_id: the `<type>/<name>` to show. Per artifact, like the resolution it informs.

    Returns:
        `ComparisonResult`, naming what was shown and what could not be.

    Raises:
        LockHeldError: another writer holds this target's lock.
        NothingToResolveError: this plan refuses nothing about this artifact.
        TargetUnreadableError: a path the target holds could not be read.
        ArtifactFileNotFoundError: a file the plan names is no longer in the library.
        OSError: the editor could not materialise the versions or could not be run. **Deliberately
            a builtin.** C-6 has no code for "the editor would not start", charter §9 forbids
            inventing one at a raise site, and C-6 is frozen for this task — so it propagates and
            the composition root reports it. Flagged: it wants a ruling.
    """
    with lock.hold():
        entries = _refused_entries(plan, artifact_id)
        held = _library_files_of(library, artifact_id)

        versions: list[ConflictVersions] = []
        left_alone: list[PlanEntry] = []
        for entry in entries:
            if entry.verdict is Verdict.SKIPPED:
                left_alone.append(entry)
                continue
            versions.append(_versions_of(entry, library, target, held=held))

        editor.compare(tuple(versions))

        return ComparisonResult(
            artifact_id=artifact_id,
            compared=tuple(version.path for version in versions),
            left_alone=tuple(left_alone),
        )


# ------------------------------------------------------------------------------------------------
# Choosing a side
# ------------------------------------------------------------------------------------------------


class _Decided(NamedTuple):
    """One refused path this run will act on, and the record it produces.

    `file` is `None` for a path dropped from the record — a `TARGET` resolution of a path the
    target no longer holds, where *what is on disk* is nothing.

    **`artifact_id` is the entry's own and not the run's**, although under this module they are
    always the same value. That is deliberate: `_refused_entries` is the single place the
    per-artifact rule lives (R54), and every step after it reads the owner off the entry. Nothing
    downstream re-states the scoping, so nothing downstream can disagree with it — and the one
    line that enforces it is the one line a mutation has to change.
    """

    entry: PlanEntry
    artifact_id: str
    file_path: str
    file: ArtifactFile | None


def _resolve(
    plan: InstallPlan,
    library: ArtifactRepository,
    target: TargetRepository,
    backups: BackupStore,
    manifests: ManifestStore,
    *,
    manifest: Manifest | None,
    artifact_id: str,
    resolution: Resolution,
    target_path: str,
    installed_at: datetime,
    library_git_sha: str | None,
) -> ResolveResult:
    """The whole run, with the lock already held.

    A separate function rather than an indented block, for the reason `install._apply` is one:
    the boundary is what is being guaranteed, and a step added here is inside the lock by
    construction rather than by remembering.
    """
    entries = _refused_entries(plan, artifact_id)

    decided: list[_Decided] = []
    left_alone: list[PlanEntry] = []
    for entry in entries:
        refusal = _refusal_of(entry, resolution)
        if refusal is not None:
            left_alone.append(refusal)
            continue
        decided.append(_decide(entry, library, target, manifest, resolution=resolution))

    if not decided:
        # Nothing was resolved, so nothing is recorded — a run that changed nothing must leave no
        # trace, and a target with no manifest must not acquire one from a resolution that
        # resolved nothing. `CleanResult.manifest`'s rule.
        return ResolveResult(
            artifact_id=artifact_id,
            resolution=resolution,
            left_alone=tuple(left_alone),
        )

    written = tuple(one.entry.path for one in decided) if resolution is Resolution.LIBRARY else ()

    # 1. Back up every path this run will write, before it writes one. R88; a `TARGET` resolution
    #    writes none and so has nothing to protect.
    backup_id = _take_backup(backups, written)

    # 2. Then the record, and only then a file — ruling R63's ordering, for R63's reason. Under a
    #    `TARGET` resolution nothing follows it, which is the whole run.
    record = _manifest_after_resolve(
        manifest,
        decided=tuple(decided),
        target_path=target_path,
        installed_at=installed_at,
        library_git_sha=(
            library_git_sha
            if resolution is Resolution.LIBRARY
            else (manifest.library_git_sha if manifest is not None else None)
        ),
        backup_id=backup_id,
    )
    _write_record(manifests, record)

    # 3. The files, under `LIBRARY` only. A failure here leaves the record over-claiming, which is
    #    the accepted cost of the ordering above.
    if resolution is Resolution.LIBRARY:
        for one in decided:
            _write_file(target, library, one)

    return ResolveResult(
        artifact_id=artifact_id,
        resolution=resolution,
        manifest=record,
        backup_id=backup_id,
        written=written,
        repaired=(
            ()
            if resolution is Resolution.LIBRARY
            else tuple(one.entry.path for one in decided if one.file is not None)
        ),
        dropped=tuple(one.entry.path for one in decided if one.file is None),
        left_alone=tuple(left_alone),
    )


def _refused_entries(plan: InstallPlan, artifact_id: str) -> tuple[PlanEntry, ...]:
    """Every entry this plan refuses **about this artifact**, in plan order.

    The `artifact_id` clause is the whole of "resolution is per artifact" (R54). Without it one
    `--resolve` would decide every conflict in the run, which is the opposite of what a user who
    looked at one artifact asked for — and it would do it silently, because the report of a run
    that resolved four conflicts looks exactly like the report of one that resolved the right one.

    Raises:
        NothingToResolveError: this plan refuses nothing about this artifact. Both shapes of
            "nothing" reach it — an id the plan does not mention at all, and an id it mentions
            only at paths it is content with — because a user acts the same way on both: go and
            look at what is actually refused.
    """
    refused = tuple(
        entry
        for entry in plan.entries
        if entry.artifact_id == artifact_id
        and (entry.verdict in RESOLVABLE_VERDICTS or entry.verdict is Verdict.SKIPPED)
    )
    if not refused:
        mentioned = any(entry.artifact_id == artifact_id for entry in plan.entries)
        raise NothingToResolveError(
            artifact_id,
            "this plan judges none of its paths local_edit, conflict or skipped"
            if mentioned
            else "this plan says nothing about it at all",
        )
    return refused


def _refusal_of(entry: PlanEntry, resolution: Resolution) -> PlanEntry | None:
    """The entry re-stated as refused, or `None` when this side can take it.

    Three refusals, and each one is a fact about what does not exist rather than a policy:

    * a `SKIPPED` artifact was never scanned, so neither side has bytes (**R99**). Its **own**
      reason is kept — the V11 sentence names the link and the rule, and that is what the user
      has to act on;
    * a path the target holds and whose content was never read (**R72**, `UNHASHED_TARGET_SHA`):
      a symlink. Writing would go through it and recording would invent a digest;
    * a path the library no longer holds, asked to take the library's side: there is no version
      to take. The reason names the side that can.
    """
    if entry.verdict is Verdict.SKIPPED:
        return entry
    if entry.target_sha == UNHASHED_TARGET_SHA:
        return replace(
            entry,
            reason=(
                f"{entry.path} was not resolved: the target holds a symlink there, which ruling "
                "R6 never follows, so there is no content to write over and none to record. "
                "Remove or replace the link by hand and run the plan again"
            ),
        )
    if resolution is Resolution.LIBRARY and entry.library_sha is None:
        return replace(
            entry,
            reason=(
                f"{entry.path} was not resolved to the library's version: the library no longer "
                "holds this path, so taking its side could only mean deleting your copy. "
                "--resolve target keeps what is on disk and repairs the record, after which the "
                "path reads prune and --prune removes it"
            ),
        )
    return None


def _decide(
    entry: PlanEntry,
    library: ArtifactRepository,
    target: TargetRepository,
    manifest: Manifest | None,
    *,
    resolution: Resolution,
) -> _Decided:
    """What this path's record becomes under this side.

    `LIBRARY` records the library's own `ArtifactFile` — its digest, its size, its `is_text` —
    because after this run the target holds exactly the library's bytes, which is what the
    manifest is for.

    `TARGET` records **the target's current bytes**: the path is read here and both the digest and
    the size come from that read, so the record describes what is actually on disk rather than a
    digest from the snapshot the plan was decided on. A path the target does not hold records
    nothing — *what is on disk* is nothing, and the record stops naming it.

    The two lookups are done **per entry, from the entry's own owner**, rather than once from the
    run's `artifact_id`. They would give the same answer here, and scoping them to the run would
    quietly make this function depend on `_refused_entries` having filtered — a second statement
    of the per-artifact rule, in a place no reader of R54 would think to check.
    """
    owner = _owner_of(entry)
    held = _library_files_of(library, owner)
    recorded = _recorded_files_of(manifest, owner)
    reference = _reference_file(entry, held=held, recorded=recorded)

    if resolution is Resolution.LIBRARY:
        library_file = held.get(entry.path)
        if library_file is None:  # pragma: no cover - `_refusal_of` refuses this first
            raise ValueError(
                f"{entry.path!r} was resolved to the library's version and the library holds no "
                "file there; the plan and the library are from two different runs"
            )
        return _Decided(
            entry=entry, artifact_id=owner, file_path=library_file.path, file=library_file
        )
    if entry.target_sha is None:
        return _Decided(entry=entry, artifact_id=owner, file_path=reference.path, file=None)

    data = _read_target(target, entry.path)
    return _Decided(
        entry=entry,
        artifact_id=owner,
        file_path=reference.path,
        file=ArtifactFile(
            path=reference.path,
            sha256=hash_bytes(data),
            size=len(data),
            # Carried, never re-derived. Charter §7 keeps one implementation of the text
            # decision, it is `infrastructure.scanner.is_text`, and this layer may not import it.
            is_text=reference.is_text,
        ),
    )


def _owner_of(entry: PlanEntry) -> str:
    """Which artifact a refused path belongs to.

    Raises:
        ValueError: the entry belongs to no artifact. Unreachable from a refused entry — R60
            gives `None` only to a `FOREIGN` path under no artifact root, and `FOREIGN` is not
            resolvable — and a bare `ValueError` for that reason: it is a bug, not a user's
            mistake.
    """
    if entry.artifact_id is None:
        raise ValueError(
            f"{entry.path!r} is refused and belongs to no artifact, so there is nothing to "
            "resolve it against. R60 gives an entry no artifact only when it is foreign"
        )
    return entry.artifact_id


def _reference_file(
    entry: PlanEntry,
    *,
    held: Mapping[str, ArtifactFile],
    recorded: Mapping[str, ArtifactFile],
) -> ArtifactFile:
    """The file whose **artifact-root-relative path** and `is_text` this path inherits.

    The previous record first and the library second. Both spell the path identically — they reach
    the same target path through the same forward join (R73) — so the order only settles `is_text`,
    and the manifest is a record of what was *installed*, so the record's own answer is the one
    every other consumer of it already joins on.

    Raises:
        ValueError: neither side holds the path. Unreachable from a refused entry — a `LOCAL_EDIT`
            or a `CONFLICT` requires the library or the manifest to hold it — and a bare
            `ValueError` for that reason: it means the plan and the manifest are from two
            different runs, which is a bug and not a user's mistake.
    """
    previously = recorded.get(entry.path)
    if previously is not None:
        return previously
    library_file = held.get(entry.path)
    if library_file is None:
        raise ValueError(
            f"{entry.path!r} is refused and neither the library nor the manifest holds it, so "
            "there is no artifact-root-relative path to record it under"
        )
    return library_file


def _versions_of(
    entry: PlanEntry,
    library: ArtifactRepository,
    target: TargetRepository,
    *,
    held: Mapping[str, ArtifactFile],
) -> ConflictVersions:
    """Both versions of one refused path, as far as either can be fetched. **Ruling R72.**

    Three target states and not two: a digest, an absence, and `UNHASHED_TARGET_SHA` — the target
    holds the path and its content was never read, which today means a symlink. The last one is
    shown with the reason rather than as an empty pane, because "there is nothing here" and "there
    is something here that R6 will not read through" are different things to tell a user who is
    deciding what to do about the path.
    """
    library_file = held.get(entry.path)
    library_bytes = (
        None
        if library_file is None or entry.artifact_id is None
        else read_file_bytes(library, entry.artifact_id, library_file.path)
    )
    if entry.target_sha == UNHASHED_TARGET_SHA:
        return ConflictVersions(
            path=entry.path,
            library=library_bytes,
            unreadable=(
                "the target holds a symlink here, and ruling R6 never follows one, so its "
                "content cannot be shown"
            ),
        )
    return ConflictVersions(
        path=entry.path,
        library=library_bytes,
        target=None if entry.target_sha is None else _read_target(target, entry.path),
    )


# ------------------------------------------------------------------------------------------------
# The three things this module does to a disk
# ------------------------------------------------------------------------------------------------


def _take_backup(backups: BackupStore, paths: tuple[str, ...]) -> str | None:
    """Copy every path this run will write, before it writes one. `None` when it writes none.

    Deduplicated but not sorted, as apply's is: the plan is already in path order, and a backup
    listing that reordered its own paths would be harder to compare against the plan that produced
    it.

    Raises:
        BackupFailedError: the store could not take it, so **nothing is written**. R88 and F-9:
            this is the one operation in the project that deliberately destroys an edit of the
            user's, so a copy of what it is about to discard is the point rather than a formality.
    """
    unique = tuple(dict.fromkeys(paths))
    if not unique:
        return None
    try:
        return backups.create(unique)
    except OSError as error:
        raise BackupFailedError(str(error)) from error


def _write_record(manifests: ManifestStore, record: Manifest) -> None:
    """Record the decision, **before the first file**. Ruling R63, charter §13b.

    Raises:
        ManifestWriteError: it could not be written, so nothing was resolved. The code promises
            *nothing happened*, and under this module's ordering that is true of both
            resolutions — a `LIBRARY` run has not reached its first write and a `TARGET` run moves
            no file at all.
    """
    try:
        manifests.write(record)
    except OSError as error:
        raise ManifestWriteError(str(error)) from error


def _write_file(
    target: TargetRepository,
    library: ArtifactRepository,
    decided: _Decided,
) -> None:
    """Put the library's version of one path into the target.

    The bytes come from the **entry's own** artifact, not from the run's: see `_Decided`.

    Raises:
        TargetUnwritableError: the target refused the write.
        ArtifactFileNotFoundError: the library no longer holds the file — a torn read.
    """
    data = read_file_bytes(library, decided.artifact_id, decided.file_path)
    try:
        target.write(decided.entry.path, data)
    except OSError as error:
        raise TargetUnwritableError(decided.entry.path, str(error)) from error


def _read_target(target: TargetRepository, path: str) -> bytes:
    """The target's current bytes at one path.

    Raises:
        TargetUnreadableError: it could not be read — including a path the target no longer
            holds, which is a target that changed under the plan rather than something to pass
            over quietly. **Ruling R81's code, reaching its first emitter**: nothing has been
            written when this fires, because both callers read before they record.
    """
    try:
        return target.read_bytes(path)
    except OSError as error:
        raise TargetUnreadableError(path, str(error)) from error


# ------------------------------------------------------------------------------------------------
# The record this run leaves behind
# ------------------------------------------------------------------------------------------------


def _library_files_of(library: ArtifactRepository, artifact_id: str) -> dict[str, ArtifactFile]:
    """This artifact's files, keyed by where they land in the target.

    One artifact and not the whole library, because that is this run's whole scope — and through
    `registry.target_path_of`, the **same forward join** the plan was built from (R73). Never an
    inverse of it: `PlanEntry.path` cannot be turned back into an artifact-root-relative path
    without knowing the artifact's kind, and a second implementation of the layout is exactly what
    that ruling exists to prevent.

    Empty when the library no longer holds the artifact, which is a real state — the conflict
    shape in which the library dropped a file the target still has.
    """
    artifact = library.get(artifact_id)
    if artifact is None:
        return {}
    return {
        target_path_of(artifact.type, artifact.name, file.path): file for file in artifact.files
    }


def _recorded_files_of(manifest: Manifest | None, artifact_id: str) -> dict[str, ArtifactFile]:
    """What the manifest records for this artifact, keyed by where it was written.

    The same forward join again, for the reason `_library_files_of` uses it: C-11 records no
    target-relative path on purpose, so the manifest and the plan meet on a key neither stores.
    """
    if manifest is None:
        return {}
    for record in manifest.artifacts:
        if record.artifact_id != artifact_id:
            continue
        artifact_type, name = _identity_of(record.artifact_id)
        return {target_path_of(artifact_type, name, file.path): file for file in record.files}
    return {}


def _manifest_after_resolve(
    previous: Manifest | None,
    *,
    decided: tuple[_Decided, ...],
    target_path: str,
    installed_at: datetime,
    library_git_sha: str | None,
    backup_id: str | None,
) -> Manifest:
    """What the manifest says once the refused paths have been decided.

    **Only the records of the artifacts the run decided about change.** In practice that is one,
    because `_refused_entries` selects one artifact's entries and nothing after it widens the
    set — but this function reads each decided path's **own** owner rather than being told the
    run's, for the reason `_Decided` gives: the per-artifact rule is stated once, at the line
    that enforces it, and nowhere else.

    Every untouched record is carried over verbatim, digests included: this run moved none of
    their files, and re-deriving a digest from anywhere would be a claim about bytes nothing here
    read.

    One rule per decided path: **record the file the side chose, or drop the path when the side
    chose nothing.** Every other file of the same artifact keeps the digest the previous record
    gave it — the manifest says what this tool put there, and a path this run did not touch still
    holds whatever it last put there.

    An artifact left with no file is dropped rather than left as a record claiming nothing, which
    is the decision `install._manifest_after`, `prune` and `rollback` all make. `content_hash` is
    recomputed over the files that remain, because it describes the record beside it and a record
    that has gained or lost a file has changed.
    """
    changed: dict[str, dict[str, ArtifactFile]] = {}
    for one in decided:
        files = changed.setdefault(one.artifact_id, _files_by_path(previous, one.artifact_id))
        if one.file is None:
            files.pop(one.file_path, None)
        else:
            files[one.file_path] = one.file

    artifacts: list[ManifestArtifact] = []
    for record in previous.artifacts if previous is not None else ():
        if record.artifact_id not in changed:
            artifacts.append(record)
            continue
        files = changed.pop(record.artifact_id)
        if files:
            artifacts.append(_record_of(record.artifact_id, files))
    # Whatever is left had no previous record: a conflict at a path no manifest ever recorded,
    # which is the commonest first-run shape and the one `manifest=None` exists for.
    for artifact_id, files in changed.items():
        if files:
            artifacts.append(_record_of(artifact_id, files))

    return Manifest(
        target_path=previous.target_path if previous is not None else target_path,
        installed_at=installed_at,
        library_git_sha=library_git_sha,
        backup_id=backup_id,
        artifacts=tuple(artifacts),
    )


def _files_by_path(manifest: Manifest | None, artifact_id: str) -> dict[str, ArtifactFile]:
    """This artifact's recorded files, keyed by their artifact-root-relative path.

    The manifest's own key, not the target's: this is what the new record is rebuilt from, and
    joining it out to the target and back would be the inverse R73 forbids.
    """
    if manifest is None:
        return {}
    for record in manifest.artifacts:
        if record.artifact_id == artifact_id:
            return {file.path: file for file in record.files}
    return {}


def _record_of(artifact_id: str, files: Mapping[str, ArtifactFile]) -> ManifestArtifact:
    """One artifact's record, with a content hash that really describes the files beside it."""
    kept = tuple(files.values())
    return ManifestArtifact(
        artifact_id=artifact_id,
        content_hash=content_hash_of_files(kept),
        files=kept,
    )


def _identity_of(artifact_id: str) -> tuple[ArtifactType, str]:
    """`<type>/<name>` split. Every id in a constructed `Manifest` parses — ruling R74 guards
    `ManifestArtifact` itself, so the narrowing below is for the type and not for a state."""
    identity = parse_artifact_id(artifact_id)
    if identity is None:  # pragma: no cover - R74 makes this unconstructible
        raise ValueError(f"the manifest records {artifact_id!r}, which is not a <type>/<name>")
    return identity


__all__ = [
    "ComparisonResult",
    "ResolveResult",
    "compare_versions",
    "resolve_conflict",
]
