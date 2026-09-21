"""`RollbackInstall` — F-11's control flow, and the record it leaves behind.

What belongs *here* is what the application layer decides: that the restore runs under the lock,
that the record is written **after** it and describes the restored disk, and that each of the
store's two failures reaches a caller as something it can branch on.

What does **not** belong here is F-11's criterion itself. "The target is back to its exact prior
hash set, per file" is a fact about a real directory, and the code that makes it true is split
between `infrastructure/backup.py` and this use case — `tests/test_rollback.py` is where the two
meet. `FakeBackupStore` keeps real bytes and mirrors C-13's rule (a path it holds no bytes for is
removed again), which is enough to drive this layer's decisions and is **not** evidence about the
real store: a fake that agrees with the contract proves only that the fake was written from it.

Fakes only, zero disk (charter §10).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from harness_library.application.write import RollbackResult, rollback_install
from harness_library.domain.errors import (
    BackupNotFoundError,
    ErrorCode,
    LockHeldError,
    RecordStaleError,
    RestoreFailedError,
)
from harness_library.domain.manifest import Manifest
from tests.application.fakes import (
    TARGET_PATH,
    FakeBackupStore,
    FakeManifestStore,
    FakeTargetRepository,
    FakeWriteLock,
    make_file,
    manifest_artifact,
    manifest_of,
    target_file,
    target_holding,
    target_symlink,
)

SKILL_ID = "skill/delivery-lead"
OTHER_ID = "skill/phase-reviewer"

ENTRY = "SKILL.md"
INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"
INSTALLED_OTHER = "skills/phase-reviewer/SKILL.md"
FOREIGN = "settings.json"

BEFORE_BYTES = b"# what the last install put there\n"
AFTER_BYTES = b"# what this install put there\n"
CREATED_BYTES = b"# a file this install created\n"
FOREIGN_BYTES = b'{"theme": "dark"}\n'

ROLLED_BACK_AT = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
"""When every rollback in this module ran. A parameter, never a clock."""


def rollback(
    target: FakeTargetRepository,
    backups: FakeBackupStore,
    *,
    manifest: Manifest,
    backup_id: str = "2026-09-21T14-29-00Z",
    manifests: FakeManifestStore | None = None,
    lock: FakeWriteLock | None = None,
) -> RollbackResult:
    """`rollback_install` with this module's fixed instant.

    Plumbing only: it passes arguments and returns the result. It asserts nothing and decides
    nothing (L29). A fresh `FakeWriteLock` unless one is given, so **every rollback here runs
    under a lock** (R82).
    """
    return rollback_install(
        target,
        backups,
        manifests if manifests is not None else FakeManifestStore(),
        lock=lock if lock is not None else FakeWriteLock(),
        manifest=manifest,
        backup_id=backup_id,
        installed_at=ROLLED_BACK_AT,
    )


_Applied = tuple[FakeTargetRepository, FakeBackupStore, Manifest]
"""What an apply left behind: the target, the backup it took, and the record it wrote."""


def an_apply_that_overwrote_and_created() -> _Applied:
    """The target, the backup and the manifest an apply would have left behind.

    Built by really running the steps in order — back up, then write — rather than by declaring
    the end state, so the backup holds what the target actually held and the two literals cannot
    drift apart. Ruling R79 is in the order: `INSTALLED_OTHER` is backed up *before* it exists,
    which is what makes its creation undoable.
    """
    target = target_holding(
        (INSTALLED_ENTRY, BEFORE_BYTES),
        (FOREIGN, FOREIGN_BYTES),
    )
    backups = FakeBackupStore(target)
    backups.create((INSTALLED_ENTRY, INSTALLED_OTHER))

    target.write(INSTALLED_ENTRY, AFTER_BYTES)
    target.write(INSTALLED_OTHER, CREATED_BYTES)

    manifest = manifest_of(
        manifest_artifact(SKILL_ID, (make_file(ENTRY, AFTER_BYTES),)),
        manifest_artifact(OTHER_ID, (make_file(ENTRY, CREATED_BYTES),)),
    )
    return target, backups, manifest


# -------------------------------------------------------------------------------------------
# What the record says afterwards
# -------------------------------------------------------------------------------------------


def test_the_new_record_carries_the_digest_the_restored_file_now_holds() -> None:
    """**The manifest describes the restored state, not the state that was rolled back.**

    The record apply left behind claimed the library's digest for this path. After the rollback
    the path holds what the *previous* install put there, and the record has to say so — a
    manifest still claiming the newer digest would report the restored file as a `LOCAL_EDIT` on
    the next `hl diff` and ask the user to decide about a file this tool put back itself.

    The digest is read off the restored disk because there is nowhere else to read it from:
    `ManifestStore` has one member (C-15) and apply overwrote the record that described this
    state.
    """
    target, backups, manifest = an_apply_that_overwrote_and_created()

    result = rollback(target, backups, manifest=manifest)

    restored = next(
        record for record in result.manifest.artifacts if record.artifact_id == SKILL_ID
    )
    assert restored.files[0].sha256 == make_file(ENTRY, BEFORE_BYTES).sha256
    assert restored.files[0].size == len(BEFORE_BYTES)
    assert target.snapshot()[INSTALLED_ENTRY] == BEFORE_BYTES


def test_an_artifact_whose_only_file_was_removed_is_dropped_from_the_record() -> None:
    """**Ruling R79's half, at the record.** The backup described `INSTALLED_OTHER` and held no
    bytes for it, so the restore removed it; the manifest must stop claiming it.

    Left claimed, it would come back `CREATE` on the next diff — recoverable, but a lie about
    what is installed — and an artifact with no file left would linger as an empty record.
    """
    target, backups, manifest = an_apply_that_overwrote_and_created()

    result = rollback(target, backups, manifest=manifest)

    assert INSTALLED_OTHER not in target.snapshot()
    assert [record.artifact_id for record in result.manifest.artifacts] == [SKILL_ID]


def test_the_record_keeps_the_is_text_the_previous_one_carried() -> None:
    """C-12 gives a target no `is_text` and charter §7 wants one implementation of that decision,
    so the flag is carried over from the record rather than decided a second time here.

    A binary file restored by a rollback stays binary in the manifest, which is what keeps it out
    of `hl search` afterwards.
    """
    binary = b"\x89PNG\r\n\x1a\n\x00rolled back\n"
    target = target_holding((INSTALLED_ENTRY, binary))
    backups = FakeBackupStore(target)
    backups.create((INSTALLED_ENTRY,))
    target.write(INSTALLED_ENTRY, b"\x89PNG\r\n\x1a\n\x00and then replaced\n")
    manifest = manifest_of(
        manifest_artifact(
            SKILL_ID,
            (make_file(ENTRY, b"\x89PNG\r\n\x1a\n\x00and then replaced\n", is_text=False),),
        )
    )

    result = rollback(target, backups, manifest=manifest)

    assert result.manifest.artifacts[0].files[0].is_text is False
    assert result.manifest.artifacts[0].files[0].sha256 == make_file(ENTRY, binary).sha256


def test_a_symlink_now_sitting_at_a_recorded_path_is_not_recorded() -> None:
    """A link carries no content digest (R6, R68) and `<unhashed>` is a plan-time sentinel, not a
    digest: putting either into `ArtifactFile.sha256` would make the manifest claim a value
    nothing has, and the next diff would compare the library against it and always disagree.

    The link is left exactly where it is — rollback restores a backup and touches nothing the
    backup does not describe — and simply goes unclaimed, which is the honest answer to "did this
    tool install that".
    """
    target = FakeTargetRepository(
        (target_symlink(INSTALLED_ENTRY), target_file(INSTALLED_OTHER, AFTER_BYTES)),
        contents={INSTALLED_OTHER: AFTER_BYTES},
    )
    backups = FakeBackupStore(target)
    backups.create((INSTALLED_OTHER,))
    manifest = manifest_of(
        manifest_artifact(SKILL_ID, (make_file(ENTRY, AFTER_BYTES),)),
        manifest_artifact(OTHER_ID, (make_file(ENTRY, AFTER_BYTES),)),
    )

    result = rollback(target, backups, manifest=manifest)

    assert [record.artifact_id for record in result.manifest.artifacts] == [OTHER_ID]
    assert any(file.is_symlink for file in target.scan())


def test_the_new_record_names_no_library_version_and_no_backup() -> None:
    """Two honest `None`s.

    `library_git_sha` — the restored bytes came from a library state this run cannot name, and
    carrying the apply's sha over would name the version that was just undone. C-11 makes `None`
    an honest answer rather than a missing one.

    `backup_id` — rollback takes no backup of its own. The field means "the state before this
    run", and recording the backup this run *consumed* would name the state it came from.
    """
    target, backups, manifest = an_apply_that_overwrote_and_created()

    result = rollback(target, backups, manifest=manifest)

    assert result.manifest.library_git_sha is None
    assert result.manifest.backup_id is None
    assert result.manifest.target_path == TARGET_PATH
    assert result.manifest.installed_at == ROLLED_BACK_AT


def test_the_result_names_what_came_back_and_what_went_away() -> None:
    """What a caller prints. `restored` is every path whose bytes changed or appeared, `removed`
    every path the restore took away — and the foreign file is in neither, because a backup
    describes only the paths the run it protected would have touched."""
    target, backups, manifest = an_apply_that_overwrote_and_created()

    result = rollback(target, backups, manifest=manifest)

    assert result.restored == (INSTALLED_ENTRY,)
    assert result.removed == (INSTALLED_OTHER,)
    assert result.backup_id == "2026-09-21T14-29-00Z"
    assert target.snapshot()[FOREIGN] == FOREIGN_BYTES


# -------------------------------------------------------------------------------------------
# The order — restore, then record
# -------------------------------------------------------------------------------------------


class _BackupStoreMarking(FakeBackupStore):
    """A `FakeBackupStore` that leaves a mark in a shared list when it restores."""

    def __init__(self, target: FakeTargetRepository, events: list[str]) -> None:
        super().__init__(target)
        self._events = events

    def restore(self, backup_id: str) -> None:
        self._events.append("restored")
        super().restore(backup_id)


class _ManifestStoreMarking(FakeManifestStore):
    """A `FakeManifestStore` that leaves a mark in the same list when it writes."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    def write(self, manifest: Manifest) -> None:
        self._events.append("recorded")
        super().write(manifest)


def test_the_record_is_written_after_the_restore_and_not_before() -> None:
    """**Ruling R63's rule, pointing the other way.**

    Apply records first because it makes files appear; rollback records last because it makes
    them disappear. The rule underneath is the same one — *the manifest must never disown a file
    that is still on disk* — and here the other order is not merely unsafe, it is impossible: the
    restored disk is the only source for the digests the new record names.

    One ordered list, because two separate assertions could each pass while the pair was wrong.
    """
    events: list[str] = []
    target = target_holding((INSTALLED_ENTRY, BEFORE_BYTES))
    backups = _BackupStoreMarking(target, events)
    backups.create((INSTALLED_ENTRY,))
    target.write(INSTALLED_ENTRY, AFTER_BYTES)
    manifest = manifest_of(manifest_artifact(SKILL_ID, (make_file(ENTRY, AFTER_BYTES),)))

    rollback(target, backups, manifest=manifest, manifests=_ManifestStoreMarking(events))

    assert events == ["restored", "recorded"]


# -------------------------------------------------------------------------------------------
# The two ways a restore fails
# -------------------------------------------------------------------------------------------


def test_a_backup_id_that_names_nothing_is_refused_and_nothing_is_recorded() -> None:
    """A directory with no readable record is not a backup and is never offered (C-13), so a
    caller reaching one arrives here. `BACKUP_FAILED` is the status whose remedy is already "go
    and look at where backups live"; nothing on disk moved and the record is untouched."""
    target, backups, manifest = an_apply_that_overwrote_and_created()
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(BackupNotFoundError) as raised:
        rollback(target, backups, manifest=manifest, backup_id="nonsense", manifests=manifests)

    assert raised.value.code is ErrorCode.BACKUP_FAILED
    assert raised.value.backup_id == "nonsense"
    assert target.snapshot() == before
    assert manifests.written == []


def test_a_restore_that_fails_part_way_leaves_the_record_alone() -> None:
    """**The answer to "one file restorable, another not".**

    Rollback does not pre-flight the backup and does not undo what it managed — C-13 restores as
    a unit and offers no transaction — so the target is left part-way back. What it does *not*
    do is write the record: the manifest still claims every path, so nothing on disk is disowned
    and every path that did move comes back `LOCAL_EDIT`, `CONFLICT` or `CREATE` rather than
    `FOREIGN`.

    The remedy is that restoring one backup twice produces the same target, so the run is
    finished by running it again — the property apply does not have, and the reason apply needed
    a rollback while a rollback needs nothing beyond itself.
    """
    target = target_holding((INSTALLED_ENTRY, BEFORE_BYTES), (INSTALLED_OTHER, BEFORE_BYTES))
    backups = FakeBackupStore(target, fail_restore=True)
    backups.create((INSTALLED_ENTRY, INSTALLED_OTHER))
    target.write(INSTALLED_ENTRY, AFTER_BYTES)
    target.write(INSTALLED_OTHER, AFTER_BYTES)
    manifest = manifest_of(
        manifest_artifact(SKILL_ID, (make_file(ENTRY, AFTER_BYTES),)),
        manifest_artifact(OTHER_ID, (make_file(ENTRY, AFTER_BYTES),)),
    )
    manifests = FakeManifestStore()

    with pytest.raises(RestoreFailedError) as raised:
        rollback(target, backups, manifest=manifest, manifests=manifests)

    assert raised.value.code is ErrorCode.TARGET_UNWRITABLE
    assert raised.value.backup_id == "2026-09-21T14-29-00Z"
    assert manifests.written == [], (
        "a part-way restore must leave the record claiming everything it claimed before: a "
        "manifest that dropped a path whose file is still on disk makes that file FOREIGN, and "
        "nothing in this initiative can touch a foreign path"
    )
    assert target.snapshot()[INSTALLED_ENTRY] == BEFORE_BYTES
    assert target.snapshot()[INSTALLED_OTHER] == AFTER_BYTES


# -------------------------------------------------------------------------------------------
# Ruling R50 / C-16 — rollback's half of the single-writer lock
# -------------------------------------------------------------------------------------------


def test_rollback_requires_a_lock_and_gives_it_no_default() -> None:
    """C-16 and ruling R82. A write path that simply does not take a lock keeps every gate green
    while sitting outside charter §12, and rollback is a write path however much it is spelled
    as an undo."""
    parameter = inspect.signature(rollback_install).parameters["lock"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_rollback_restores_nothing_when_the_lock_is_held() -> None:
    """A run that cannot take the lock does not restore and does not record.

    The positive control is in the same test: the identical run under a free lock does both, so
    the empty lists cannot be empty because the backup was.
    """
    target, backups, manifest = an_apply_that_overwrote_and_created()
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(LockHeldError) as raised:
        rollback(
            target,
            backups,
            manifest=manifest,
            manifests=manifests,
            lock=FakeWriteLock(held_by_another=True),
        )

    assert raised.value.code is ErrorCode.LOCK_HELD
    assert backups.restored == []
    assert manifests.written == []
    assert target.snapshot() == before

    rollback(target, backups, manifest=manifest, manifests=manifests)

    assert backups.restored != []
    assert manifests.written != []
    assert target.snapshot() != before


def test_the_lock_is_released_when_the_restore_fails() -> None:
    """The failure path that matters most: this is the run that leaves the target part-way back,
    so it is the run whose user most needs to be able to try again without deleting a lock file
    by hand."""
    target = target_holding((INSTALLED_ENTRY, BEFORE_BYTES), (INSTALLED_OTHER, BEFORE_BYTES))
    backups = FakeBackupStore(target, fail_restore=True)
    backups.create((INSTALLED_ENTRY, INSTALLED_OTHER))
    manifest = manifest_of(manifest_artifact(SKILL_ID, (make_file(ENTRY, BEFORE_BYTES),)))
    lock = FakeWriteLock()

    with pytest.raises(RestoreFailedError):
        rollback(target, backups, manifest=manifest, lock=lock)

    assert lock.events == ["acquired", "released"]
    assert lock.held is False


def test_the_lock_is_released_on_a_rollback_that_succeeds() -> None:
    """The control for the pair above: a lock leaked on the happy path would wedge the target
    after the one run that went right."""
    target, backups, manifest = an_apply_that_overwrote_and_created()
    lock = FakeWriteLock()

    rollback(target, backups, manifest=manifest, lock=lock)

    assert lock.events == ["acquired", "released"]
    assert lock.held is False


# -- Ruling R90: a record that could not keep up (T-19) ------------------------------------------


def test_a_record_that_cannot_be_written_after_the_restore_is_record_stale() -> None:
    """**R90**, which is the C-6 amendment `rollback_install` used to say it was waiting for.

    This module used to let a bare `OSError` out here, on the argument that `MANIFEST_UNWRITABLE`
    promises *nothing happened* and that promise is exactly false after a restore. R90 gives the
    condition a code of its own — exit 13 — so a caller can tell "the target is as it was" from
    "the target moved and the record did not".

    Asserted on the code and on the target together: the restore really did happen, so the error
    cannot be read as a refusal.
    """
    target, backups, manifest = an_apply_that_overwrote_and_created()

    with pytest.raises(RecordStaleError) as raised:
        rollback(target, backups, manifest=manifest, manifests=FakeManifestStore(fail=True))

    assert raised.value.code is ErrorCode.RECORD_STALE
    assert raised.value.operation == "rollback"
    assert target.snapshot()[INSTALLED_ENTRY] == BEFORE_BYTES
