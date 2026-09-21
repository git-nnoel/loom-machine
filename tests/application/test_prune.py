"""`PruneTarget` — F-12's `--prune`. What leaves a target when the library drops it.

The assertion this module exists for is the **negative** one: a still-present artifact's installed
files are byte-identical afterwards. Everything else here is either that claim's positive control
— prune really does remove what it says it removes, so "nothing was touched" cannot mean "this
use case does nothing" — or the ordering that makes a failure recoverable.

Fakes only, zero disk (charter §10). What this layer cannot see: that a real `delete` unlinks a
symlink as itself, that a real emptied directory survives, or that a backup lands outside the
target. Those are proven against real files in `tests/infrastructure/` and `tests/test_clean.py`,
and the lock's half is proven in `tests/test_single_writer.py`.

**Every byte-identical assertion reads the target's content** through `FakeTargetRepository`,
never the delete recorder: a recorder can be empty because nothing was removed or because nothing
recorded it, and F-12 is about the file.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from harness_library.application.write import PruneResult, prune_target, pruned_entries
from harness_library.domain.errors import (
    BackupFailedError,
    ErrorCode,
    LockHeldError,
    RecordStaleError,
    TargetUnwritableError,
)
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.manifest import Manifest
from tests.application.fakes import (
    FakeBackupStore,
    FakeManifestStore,
    FakeTargetRepository,
    FakeWriteLock,
    make_file,
    manifest_artifact,
    manifest_of,
    target_holding,
)

DEPARTED_ID = "skill/retired-helper"
PRESENT_ID = "skill/delivery-lead"

ENTRY = "SKILL.md"
REFERENCE = "references/notes.md"

DEPARTED_ENTRY = "skills/retired-helper/SKILL.md"
DEPARTED_REFERENCE = "skills/retired-helper/references/notes.md"
PRESENT_ENTRY = "skills/delivery-lead/SKILL.md"
FOREIGN_BESIDE = "skills/retired-helper/NOTES.md"
"""A file **under the departed artifact's own root** that the manifest does not record.

Under the root rather than loose in the target, for the reason `test_uninstall.py`'s is: a loose
file survives even a `rm -rf skills/retired-helper`, so it would prove nothing about where the
removal list came from.
"""

DEPARTED_BYTES = b"# what the library used to hold\n"
DEPARTED_REFERENCE_BYTES = b"# and its reference\n"
PRESENT_BYTES = b"# what the library still holds\n"
FOREIGN_BYTES = b"# the user wrote this, in the same directory\n"

INSTALLED_AT = datetime(2026, 9, 21, 19, 5, tzinfo=UTC)
"""When every prune in this module ran. A parameter, never a clock."""


# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


def a_manifest() -> Manifest:
    """Two artifacts recorded: the one the library dropped, and one it still holds."""
    return manifest_of(
        manifest_artifact(
            DEPARTED_ID,
            (
                make_file(ENTRY, DEPARTED_BYTES),
                make_file(REFERENCE, DEPARTED_REFERENCE_BYTES),
            ),
        ),
        manifest_artifact(PRESENT_ID, (make_file(ENTRY, PRESENT_BYTES),)),
    )


def a_target() -> FakeTargetRepository:
    """What `a_manifest` describes, plus a file nobody recorded."""
    return target_holding(
        (DEPARTED_ENTRY, DEPARTED_BYTES),
        (DEPARTED_REFERENCE, DEPARTED_REFERENCE_BYTES),
        (PRESENT_ENTRY, PRESENT_BYTES),
        (FOREIGN_BESIDE, FOREIGN_BYTES),
    )


def entry(path: str, verdict: Verdict, *, artifact_id: str | None, content: bytes) -> PlanEntry:
    """One plan entry whose digests really describe `content` on the sides that hold it."""
    digest = hash_bytes(content)
    return PlanEntry(
        artifact_id=artifact_id,
        path=path,
        verdict=verdict,
        library_sha=None if verdict is Verdict.PRUNE else digest,
        manifest_sha=None if verdict is Verdict.FOREIGN else digest,
        target_sha=digest,
    )


def a_plan() -> InstallPlan:
    """The departed artifact's two files pruned, the present one unchanged, one foreign."""
    return InstallPlan(
        entries=(
            entry(DEPARTED_ENTRY, Verdict.PRUNE, artifact_id=DEPARTED_ID, content=DEPARTED_BYTES),
            entry(FOREIGN_BESIDE, Verdict.FOREIGN, artifact_id=DEPARTED_ID, content=FOREIGN_BYTES),
            entry(
                DEPARTED_REFERENCE,
                Verdict.PRUNE,
                artifact_id=DEPARTED_ID,
                content=DEPARTED_REFERENCE_BYTES,
            ),
            entry(PRESENT_ENTRY, Verdict.UNCHANGED, artifact_id=PRESENT_ID, content=PRESENT_BYTES),
        )
    )


def prune(
    target: FakeTargetRepository,
    *,
    plan: InstallPlan | None = None,
    manifest: Manifest | None = None,
    backups: FakeBackupStore | None = None,
    manifests: FakeManifestStore | None = None,
    lock: FakeWriteLock | None = None,
) -> PruneResult:
    """`prune_target` with this module's fixed instant.

    Plumbing only: it passes arguments and returns the result. It asserts nothing and decides
    nothing (L29). A fresh `FakeWriteLock` unless one is given, so **every prune here runs under
    a lock** (R82) rather than each test deciding whether this run is the locked kind.
    """
    return prune_target(
        plan if plan is not None else a_plan(),
        target,
        backups if backups is not None else FakeBackupStore(target),
        manifests if manifests is not None else FakeManifestStore(),
        lock=lock if lock is not None else FakeWriteLock(),
        manifest=manifest if manifest is not None else a_manifest(),
        installed_at=INSTALLED_AT,
    )


class _TargetRefusingOneDelete(FakeTargetRepository):
    """A target whose `delete` raises `OSError` on one named path, and works on every other.

    The real repository raises a builtin from `os.unlink`; a fake raising this project's own
    error would make the translation untestable by pre-supplying its result (ruling R24).
    """

    def __init__(self, inner: FakeTargetRepository, *, refusing: str) -> None:
        super().__init__(inner.scan(), contents=inner.snapshot())
        self._refusing = refusing

    def delete(self, path: str) -> None:
        if path == self._refusing:
            raise OSError(f"the injected failure refuses to remove {path!r}")
        super().delete(path)


# -------------------------------------------------------------------------------------------
# F-12's `--prune` — exactly what the library dropped, and nothing beside it
# -------------------------------------------------------------------------------------------


def test_prune_removes_the_files_of_an_artifact_that_left_the_library() -> None:
    """**The must-stay-green control of this task's mutation (b)** (prune every path the manifest
    records instead of only the pruned ones).

    Without it the mutation could pass by removing *nothing*: a use case that deleted no file at
    all would leave the still-present artifact byte-identical too. Asserted per path, on the
    target's content and not on the recorder.

    It asserts that the pruned files **went**, and deliberately not that *only* they went — that
    half is the must-fail's, next door. **L51:** a control which also pinned the exact removal
    list would redden under the very mutation it exists to survive, and the pair would stop
    telling "removes too much" from "removes nothing".
    """
    target = a_target()

    result = prune(target)

    held = target.snapshot()
    assert DEPARTED_ENTRY not in held
    assert DEPARTED_REFERENCE not in held
    assert set(result.removed) >= {DEPARTED_ENTRY, DEPARTED_REFERENCE}


def test_a_still_present_artifacts_files_survive_a_prune() -> None:
    """**The must-fail assertion of mutation (b).**

    `skills/delivery-lead/SKILL.md` is recorded by the manifest and still held by the library, so
    its verdict is `UNCHANGED` and prune must not touch it. Asserted on its **bytes**, because a
    report saying "I left it alone" is exactly what the wrong implementation also says.

    The exact removal tuple is asserted here rather than in the control above, which is where
    reddening is the point (L51).
    """
    target = a_target()

    result = prune(target)

    assert target.snapshot()[PRESENT_ENTRY] == PRESENT_BYTES
    assert result.removed == (DEPARTED_ENTRY, DEPARTED_REFERENCE)
    assert target.deletes == [DEPARTED_ENTRY, DEPARTED_REFERENCE]


def test_a_foreign_file_under_the_departed_artifacts_root_survives() -> None:
    """F-10 holds through a prune too. The file sits inside `skills/retired-helper/`, so removing
    "the artifact that left" as a directory would take it; its verdict is `FOREIGN`, so a
    verdict-driven prune cannot see it at all.

    Asserted on its bytes, with the removals in the same test as the positive control.
    """
    target = a_target()

    prune(target)

    assert target.snapshot()[FOREIGN_BESIDE] == FOREIGN_BYTES
    assert DEPARTED_ENTRY not in target.snapshot()


def test_prune_never_scans_the_target() -> None:
    """The plan is the input and a second snapshot is not taken.

    A scan here is how a path nobody judged reaches the removal list — the plan says which paths
    are `PRUNE` and a rescan would answer a different question about a directory that may have
    changed since. `exists` is called per candidate, which is a question about one named path and
    not a new list of paths.
    """
    target = a_target()

    prune(target)

    assert target.scan_calls == 0


def test_pruned_entries_is_what_apply_and_prune_both_select_on() -> None:
    """One spelling of "what `--prune` removes", asserted as a fact about the function.

    `apply_install` calls this and so does `prune_target`; a second comprehension in either would
    make `hl install --prune` and `hl prune` able to remove different files from one target while
    both reported success. Nothing else in the suite notices a duplicate.
    """
    selected = pruned_entries(a_plan())

    assert tuple(one.path for one in selected) == (DEPARTED_ENTRY, DEPARTED_REFERENCE)
    assert all(one.verdict is Verdict.PRUNE for one in selected)


def test_a_plan_with_nothing_pruned_removes_nothing_and_takes_no_backup() -> None:
    """The positive control's mirror: prune over a plan with no `PRUNE` entry is a no-op on the
    files, and the record it writes is the one it was given with a fresh instant.

    A backup of nothing is not taken — there is nothing to protect — which is the same rule
    uninstall keeps for an artifact recording no file.
    """
    target = a_target()
    backups = FakeBackupStore(target)
    plan = InstallPlan(
        entries=(
            entry(PRESENT_ENTRY, Verdict.UNCHANGED, artifact_id=PRESENT_ID, content=PRESENT_BYTES),
        )
    )

    result = prune(target, plan=plan, backups=backups)

    assert result.removed == ()
    assert result.backup_id is None
    assert backups.created == []
    assert target.snapshot()[DEPARTED_ENTRY] == DEPARTED_BYTES


# -------------------------------------------------------------------------------------------
# The record this run leaves behind
# -------------------------------------------------------------------------------------------


def test_the_manifest_drops_only_the_pruned_files() -> None:
    """**The must-stay-green control of mutation (c)** (record first instead of last).

    A successful run writes the same record under either ordering, which is exactly why this
    cannot be the must-fail — and exactly why it is the right control: the mutation must not be
    able to reach it.

    The departed artifact loses both its files and is dropped entirely rather than lingering as a
    record claiming nothing; the artifact the library still holds keeps its file, at the digest
    the previous record gave it, because this run did not touch it.
    """
    target = a_target()
    manifests = FakeManifestStore()

    result = prune(target, manifests=manifests)

    assert manifests.latest is result.manifest
    assert [one.artifact_id for one in result.manifest.artifacts] == [PRESENT_ID]
    assert result.manifest.artifacts[0].files[0].sha256 == hash_bytes(PRESENT_BYTES)


def test_the_manifest_is_written_only_after_the_pruned_files_are_gone() -> None:
    """**The must-fail assertion of mutation (c) — charter §13b, R86, and L52.**

    A failure is injected into the *second* delete. The first file is already gone and the
    manifest must **not** have been written: prune's record is the one in this initiative that
    actively *disowns* paths, so a record written first and then abandoned part-way leaves the
    remaining pruned files claimed by nobody — `FOREIGN`, which install will not touch, uninstall
    cannot remove, and only `clean --foreign` can reach.

    Move `manifests.write` above the delete loop and the second assertion fails. Nothing else in
    this module notices, because a run that does not fail cannot tell the two orders apart.
    """
    target = _TargetRefusingOneDelete(a_target(), refusing=DEPARTED_REFERENCE)
    manifests = FakeManifestStore()

    with pytest.raises(TargetUnwritableError) as raised:
        prune(target, manifests=manifests, backups=FakeBackupStore(target))

    assert DEPARTED_ENTRY not in target.snapshot()
    assert manifests.written == [], (
        "the manifest must not be written until the deletes have finished: prune's record drops "
        "the paths it removes, so a record written first and abandoned leaves the rest of them "
        "FOREIGN, and nothing in this initiative can touch a foreign path"
    )
    assert raised.value.code is ErrorCode.TARGET_UNWRITABLE
    assert raised.value.path == DEPARTED_REFERENCE


def test_a_record_that_cannot_be_written_after_the_deletes_is_record_stale() -> None:
    """**Ruling R90.** The files are gone and the record is behind, which is the opposite of what
    `MANIFEST_UNWRITABLE` promises — so it gets a code of its own and exit 13.

    Asserted on the code and on the target, together: a status claiming "nothing happened" over a
    target that has just lost two files is worse than no status at all, because a script that
    believed it would retry, report success, or do nothing.
    """
    target = a_target()

    with pytest.raises(RecordStaleError) as raised:
        prune(target, manifests=FakeManifestStore(fail=True))

    assert raised.value.code is ErrorCode.RECORD_STALE
    assert raised.value.operation == "prune"
    assert DEPARTED_ENTRY not in target.snapshot()


def test_a_recorded_path_the_target_no_longer_holds_is_reported_rather_than_raised() -> None:
    """A `PRUNE` verdict says the target held exactly what was installed, so a path missing here
    means the target changed between the plan and this run.

    Reported rather than folded into `removed`, because it is the visible sign of that drift —
    and not raised on, because refusing to finish over a file somebody already deleted would
    leave the rest of the departed artifact behind. It is dropped from the record either way: it
    is not on disk, so dropping it disowns nothing.
    """
    target = target_holding(
        (DEPARTED_ENTRY, DEPARTED_BYTES),
        (PRESENT_ENTRY, PRESENT_BYTES),
    )

    result = prune(target)

    assert result.removed == (DEPARTED_ENTRY,)
    assert result.absent == (DEPARTED_REFERENCE,)
    assert [one.artifact_id for one in result.manifest.artifacts] == [PRESENT_ID]


def test_the_record_keeps_the_library_sha_it_was_given() -> None:
    """Unlike a rollback's, which drops it. The artifacts still recorded here really did come from
    that library state and this run changed none of them — what moved on is the library, and this
    record does not claim to describe it."""
    previous = Manifest(
        target_path="/home/example/.claude",
        installed_at=INSTALLED_AT,
        library_git_sha="c0ffee",
        backup_id=None,
        artifacts=a_manifest().artifacts,
    )

    result = prune(a_target(), manifest=previous)

    assert result.manifest.library_git_sha == "c0ffee"
    assert result.manifest.installed_at == INSTALLED_AT


# -------------------------------------------------------------------------------------------
# F-9 / R88 — the backup, and the refusal without one
# -------------------------------------------------------------------------------------------


def test_a_backup_of_every_path_it_will_delete_is_taken_before_the_first_delete() -> None:
    """The prune is the one removal in this project no library can rebuild: the files it takes
    away are gone from the library too. The backup is the only way back.

    The paths the target no longer holds go into the backup as well, and that is not a copy of
    nothing: C-13 records a path it keeps no bytes for so that a restore **removes** it (R79,
    R92), which is what makes a rollback of this prune put the target back rather than part of it.
    """
    target = a_target()
    backups = FakeBackupStore(target)

    result = prune(target, backups=backups)

    assert backups.created == [(DEPARTED_ENTRY, DEPARTED_REFERENCE)]
    assert result.backup_id == backups.list()[0].backup_id
    assert backups.list()[0].kept == (DEPARTED_ENTRY, DEPARTED_REFERENCE)


def test_prune_refuses_when_the_backup_cannot_be_taken() -> None:
    """F-9 and R88: a delete with no way back is the failure mode this initiative exists to
    remove, and here there is no other way back at all.

    Asserted on the target's content, not on the report: every recorded file is still exactly
    where it was, and the manifest was never written.
    """
    target = a_target()
    manifests = FakeManifestStore()

    with pytest.raises(BackupFailedError) as raised:
        prune(target, backups=FakeBackupStore(target, fail=True), manifests=manifests)

    assert raised.value.code is ErrorCode.BACKUP_FAILED
    assert target.snapshot()[DEPARTED_ENTRY] == DEPARTED_BYTES
    assert target.deletes == []
    assert manifests.written == []


# -------------------------------------------------------------------------------------------
# C-16 / R82 — the lock, at this layer
# -------------------------------------------------------------------------------------------


def test_prune_requires_a_lock_and_gives_it_no_default() -> None:
    """The signature itself, because nothing else in the toolchain can see it.

    A write use case that simply does not take a lock keeps `ruff`, `mypy`, `lint-imports` and
    every test green while sitting outside charter §12. A lock with a *default* is worse: an
    unlocked run becomes a typo rather than a decision.
    """
    parameter = inspect.signature(prune_target).parameters["lock"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_prune_removes_nothing_when_the_lock_is_held() -> None:
    """The refusal, at this layer. What this fake **cannot** prove is that anything is really
    excluded — that is a sentinel file, and `tests/test_single_writer.py` proves it against a real
    one. What it can prove is that the lock wraps the whole run, backup included.
    """
    target = a_target()
    backups = FakeBackupStore(target)

    with pytest.raises(LockHeldError) as raised:
        prune(target, lock=FakeWriteLock(held_by_another=True), backups=backups)

    assert raised.value.code is ErrorCode.LOCK_HELD
    assert target.snapshot()[DEPARTED_ENTRY] == DEPARTED_BYTES
    assert backups.created == []


def test_the_lock_is_taken_before_the_backup_and_released_on_success() -> None:
    """The order, as one list. The lock is taken before the first thing this run does to a disk,
    and released however the run ends."""
    target = a_target()
    lock = FakeWriteLock()

    class _RecordingStore(FakeBackupStore):
        def create(self, paths: tuple[str, ...]) -> str:
            lock.events.append("backed up")
            return super().create(paths)

    prune(target, lock=lock, backups=_RecordingStore(target))

    assert lock.events == ["acquired", "backed up", "released"]
    assert lock.held is False


def test_the_lock_is_released_when_a_delete_fails_part_way_through() -> None:
    """A lock leaked on the error path is worse than no lock, because it only bites after
    something has already gone wrong."""
    lock = FakeWriteLock()
    target = _TargetRefusingOneDelete(a_target(), refusing=DEPARTED_REFERENCE)

    with pytest.raises(TargetUnwritableError):
        prune(target, lock=lock, backups=FakeBackupStore(target))

    assert lock.events == ["acquired", "released"]
    assert lock.held is False
