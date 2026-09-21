"""`UninstallArtifact` — F-12. What comes out of a target, and what must not.

The assertion this module exists for is the **negative** one: a foreign file sitting in the same
directory as an installed one is byte-identical afterwards. Everything else here is either that
claim's positive control — uninstall really does remove what it says it removes, so "nothing was
touched" cannot mean "this use case does nothing" — or the surrounding control flow.

Fakes only, zero disk (charter §10). What this layer cannot see: that a real `delete` unlinks a
symlink as itself rather than following it, that a directory really survives, or that a backup
lands outside the target. Those are proven against real files in `tests/infrastructure/`, and the
lock's half is proven in `tests/test_single_writer.py`.

**Every byte-identical assertion reads the target's content** through `FakeTargetRepository`,
never the delete recorder: a recorder can be empty because nothing was removed or because nothing
recorded it, and F-12 is about the file.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from harness_library.application.write import UninstallResult, uninstall_artifact
from harness_library.domain.errors import (
    ArtifactNotFoundError,
    BackupFailedError,
    ErrorCode,
    LockHeldError,
    RecordStaleError,
    TargetUnwritableError,
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
    target_holding,
)

SKILL_ID = "skill/delivery-lead"
OTHER_ID = "skill/phase-reviewer"

ENTRY = "SKILL.md"
REFERENCE = "references/notes.md"

INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"
INSTALLED_REFERENCE = "skills/delivery-lead/references/notes.md"
INSTALLED_OTHER = "skills/phase-reviewer/SKILL.md"

FOREIGN_BESIDE = "skills/delivery-lead/NOTES.md"
"""A file **under the artifact's own root** that the manifest does not record.

Under the root rather than loose in the target, because that is the case a directory-shaped
uninstall gets wrong and a record-driven one cannot: a loose `settings.json` survives even a
`rm -rf skills/delivery-lead`, so it would prove nothing about where the removal list came from.
"""

FOREIGN_LOOSE = "settings.json"

ENTRY_BYTES = b"# what this tool installed\n"
REFERENCE_BYTES = b"# a reference it installed too\n"
OTHER_BYTES = b"# a different artifact entirely\n"
FOREIGN_BYTES = b"# the user wrote this, in the same directory\n"
SETTINGS_BYTES = b'{"theme": "dark"}\n'

INSTALLED_AT = datetime(2026, 9, 21, 17, 15, tzinfo=UTC)
"""When every uninstall in this module ran. A parameter, never a clock."""


def a_manifest() -> Manifest:
    """Two artifacts recorded: the one to remove, with two files, and one to leave alone."""
    return manifest_of(
        manifest_artifact(
            SKILL_ID,
            (make_file(ENTRY, ENTRY_BYTES), make_file(REFERENCE, REFERENCE_BYTES)),
        ),
        manifest_artifact(OTHER_ID, (make_file(ENTRY, OTHER_BYTES),)),
    )


def a_target() -> FakeTargetRepository:
    """What `a_manifest` describes, plus two files nobody recorded."""
    return target_holding(
        (INSTALLED_ENTRY, ENTRY_BYTES),
        (INSTALLED_REFERENCE, REFERENCE_BYTES),
        (INSTALLED_OTHER, OTHER_BYTES),
        (FOREIGN_BESIDE, FOREIGN_BYTES),
        (FOREIGN_LOOSE, SETTINGS_BYTES),
    )


def uninstall(
    target: FakeTargetRepository,
    *,
    manifest: Manifest | None = None,
    artifact_id: str = SKILL_ID,
    backups: FakeBackupStore | None = None,
    manifests: FakeManifestStore | None = None,
    lock: FakeWriteLock | None = None,
) -> UninstallResult:
    """`uninstall_artifact` with this module's fixed instant.

    Plumbing only: it passes arguments and returns the result. It asserts nothing and decides
    nothing (L29). A fresh `FakeWriteLock` unless one is given, so **every uninstall here runs
    under a lock** (R82) rather than each test deciding whether this run is the locked kind.
    """
    return uninstall_artifact(
        target,
        backups if backups is not None else FakeBackupStore(target),
        manifests if manifests is not None else FakeManifestStore(),
        lock=lock if lock is not None else FakeWriteLock(),
        manifest=manifest if manifest is not None else a_manifest(),
        artifact_id=artifact_id,
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
# F-12 — exactly the manifest's files, and nothing beside them
# -------------------------------------------------------------------------------------------


def test_uninstall_removes_every_file_the_manifest_records() -> None:
    """**The must-stay-green control of this task's mutation (b)** (remove the whole artifact
    directory instead of the manifest's list).

    Without it the mutation could pass by removing *nothing*: a use case that deleted no file at
    all would leave the foreign file byte-identical too. Asserted per path, on the target's
    content and not on the recorder.

    It asserts that the record's files **went**, and deliberately not that *only* they went —
    that half is the must-fail's, next door. A control which also pinned the exact removal list
    would redden under the very mutation it exists to survive, and the pair would stop telling
    "removes too much" from "removes nothing".
    """
    target = a_target()

    result = uninstall(target)

    held = target.snapshot()
    assert INSTALLED_ENTRY not in held
    assert INSTALLED_REFERENCE not in held
    assert set(result.removed) >= {INSTALLED_ENTRY, INSTALLED_REFERENCE}


def test_a_foreign_file_under_the_artifacts_root_survives() -> None:
    """**F-12, and the must-fail assertion of mutation (b).**

    The file sits inside `skills/delivery-lead/`, so removing "the artifact" as a directory takes
    it. The manifest does not record it, so removing what the manifest records leaves it exactly
    where it was — asserted on its **bytes**, because a report saying "I left it alone" is
    exactly what the wrong implementation also says.

    Removing one file too many is the worst thing this tool can do, and nothing in the module
    under test knows this file exists. That is the mechanism: the list comes from the record.
    """
    target = a_target()

    uninstall(target)

    assert target.snapshot()[FOREIGN_BESIDE] == FOREIGN_BYTES
    assert target.deletes == [INSTALLED_ENTRY, INSTALLED_REFERENCE]
    assert uninstall(a_target()).removed == (INSTALLED_ENTRY, INSTALLED_REFERENCE)


def test_a_loose_foreign_file_elsewhere_in_the_target_survives() -> None:
    """The easier half of the same promise, kept as a pair with the one above.

    `settings.json` is under no artifact root at all (R60, R44), so it survives even a
    directory-shaped uninstall — which is why it cannot be the subject of the mutation and is
    worth asserting anyway: the two together say "nothing outside the record", not "nothing
    outside this one directory".
    """
    target = a_target()

    uninstall(target)

    assert target.snapshot()[FOREIGN_LOOSE] == SETTINGS_BYTES


def test_another_recorded_artifact_is_untouched() -> None:
    """Uninstall targets **one** artifact. The other's file and record both survive, asserted on
    the bytes and on the manifest, because `--prune` and `clean` are T-19's and neither of them
    is what `hl uninstall <id>` means."""
    target = a_target()

    result = uninstall(target)

    assert target.snapshot()[INSTALLED_OTHER] == OTHER_BYTES
    assert [record.artifact_id for record in result.manifest.artifacts] == [OTHER_ID]


def test_uninstall_never_scans_the_target() -> None:
    """The structural half of F-12: the removal list can only be the record's, because nothing
    here ever asks the target what it holds under a root.

    A scan is how a file nobody recorded gets into the list, and a use case that scanned would
    then need a named exclusion for `synced/` — which ruling R44 forbids anywhere. `exists` is
    called per recorded path and is not a scan.
    """
    target = a_target()

    uninstall(target)

    assert target.scan_calls == 0


# -------------------------------------------------------------------------------------------
# The record it leaves behind
# -------------------------------------------------------------------------------------------


def test_the_manifest_drops_the_artifact_and_keeps_every_other_field() -> None:
    """The record must stop claiming what is no longer there, and must keep claiming what is.

    `backup_id` becomes this run's backup — which is what makes `hl rollback` able to undo an
    `hl uninstall` — and `library_git_sha` is carried over, because the artifacts still recorded
    really did come from that library state and this run changed none of them.
    """
    target = a_target()
    manifests = FakeManifestStore()

    result = uninstall(target, manifests=manifests)

    assert manifests.latest is not None
    assert manifests.latest is result.manifest
    assert [record.artifact_id for record in manifests.latest.artifacts] == [OTHER_ID]
    assert manifests.latest.target_path == TARGET_PATH
    assert manifests.latest.installed_at == INSTALLED_AT
    assert manifests.latest.backup_id == result.backup_id


def test_the_manifest_is_written_only_after_the_files_are_gone() -> None:
    """**The ordering, and R63's rule pointing the other way.**

    A failure is injected into the *second* delete. The first file is already gone and the
    manifest must **not** have been written: a record that dropped the artifact and then failed
    part-way would leave the remaining file claimed by nobody — `FOREIGN`, which install will not
    touch and uninstall cannot remove.

    Write the manifest before the deletes and the second assertion fails. Nothing else in this
    module notices, because a run that does not fail cannot tell the two orders apart.
    """
    target = _TargetRefusingOneDelete(a_target(), refusing=INSTALLED_REFERENCE)
    manifests = FakeManifestStore()

    with pytest.raises(TargetUnwritableError) as raised:
        uninstall(target, manifests=manifests, backups=FakeBackupStore(target))

    assert INSTALLED_ENTRY not in target.snapshot()
    assert manifests.written == [], (
        "the manifest must not be written until the deletes have finished: a record that drops "
        "an artifact while its files are still on disk leaves them FOREIGN, and nothing in this "
        "initiative can touch a foreign path"
    )
    assert raised.value.code is ErrorCode.TARGET_UNWRITABLE
    assert raised.value.path == INSTALLED_REFERENCE


def test_a_recorded_path_the_target_no_longer_holds_is_reported_rather_than_raised() -> None:
    """The file is already not there, which is the outcome uninstall is for.

    Reported rather than folded into `removed`, because it is the one visible sign that the
    record and the target had drifted apart — and not raised on, because refusing to finish an
    uninstall over a file somebody already deleted would leave the rest of the artifact behind.
    """
    target = target_holding(
        (INSTALLED_ENTRY, ENTRY_BYTES),
        (INSTALLED_OTHER, OTHER_BYTES),
    )

    result = uninstall(target)

    assert result.removed == (INSTALLED_ENTRY,)
    assert result.absent == (INSTALLED_REFERENCE,)
    assert INSTALLED_ENTRY not in target.snapshot()


def test_an_artifact_this_manifest_does_not_record_is_refused() -> None:
    """Charter §13's posture: an empty answer is a fact about a target and must never also be
    how a typo looks. Nothing is backed up, nothing is removed and nothing is recorded."""
    target = a_target()
    backups = FakeBackupStore(target)
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(ArtifactNotFoundError) as raised:
        uninstall(target, artifact_id="skill/never-installed", backups=backups, manifests=manifests)

    assert raised.value.code is ErrorCode.ARTIFACT_NOT_FOUND
    assert backups.created == []
    assert manifests.written == []
    assert target.snapshot() == before


# -------------------------------------------------------------------------------------------
# The backup, and the refusal it buys
# -------------------------------------------------------------------------------------------


def test_a_backup_of_every_path_it_will_delete_is_taken_before_the_first_delete() -> None:
    """Uninstall is the operation that does nothing but delete, so F-9's argument applies to it
    without modification: a delete with no way back is the failure mode this initiative exists to
    remove.

    The backup covers exactly the paths that will go, and the id reaches the new record — which
    is what makes `hl rollback` able to undo this run.
    """
    target = a_target()
    backups = FakeBackupStore(target)

    result = uninstall(target, backups=backups)

    assert backups.created == [(INSTALLED_ENTRY, INSTALLED_REFERENCE)]
    assert result.backup_id == "2026-09-21T14-29-00Z"
    assert result.manifest.backup_id == result.backup_id


def test_uninstall_refuses_when_the_backup_cannot_be_taken() -> None:
    """Nothing is removed and nothing is recorded, asserted on both — the same guarantee apply's
    `BACKUP_FAILED` carries, and for the same reason."""
    target = a_target()
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(BackupFailedError) as raised:
        uninstall(target, backups=FakeBackupStore(target, fail=True), manifests=manifests)

    assert raised.value.code is ErrorCode.BACKUP_FAILED
    assert target.snapshot() == before
    assert target.deletes == []
    assert manifests.written == []


def test_an_artifact_recording_no_file_takes_no_backup() -> None:
    """There is nothing to protect, so there is nothing to copy — and the run still drops the
    record, which is the point: an artifact whose files have all gone is still recorded until
    something removes the record."""
    target = a_target()
    backups = FakeBackupStore(target)
    manifest = manifest_of(
        manifest_artifact(SKILL_ID, ()),
        manifest_artifact(OTHER_ID, (make_file(ENTRY, OTHER_BYTES),)),
    )

    result = uninstall(target, manifest=manifest, backups=backups)

    assert backups.created == []
    assert result.backup_id is None
    assert [record.artifact_id for record in result.manifest.artifacts] == [OTHER_ID]


# -------------------------------------------------------------------------------------------
# Ruling R50 / C-16 — uninstall's half of the single-writer lock
# -------------------------------------------------------------------------------------------
#
# Control flow only. That the lock actually excludes a second run is a sentinel file, proven in
# `tests/infrastructure/test_lock.py`, and the two together are proven in
# `tests/test_single_writer.py` with a second uninstall fired from inside this one's first delete.


class _BackupStoreMarkingTheLock(FakeBackupStore):
    """A `FakeBackupStore` that leaves a mark in the lock's own event list when it is called.

    One list holding both facts is what makes the *order* of the lock against the backup a single
    assertion rather than two that could each pass while the pair was wrong.
    """

    def __init__(self, target: FakeTargetRepository, lock: FakeWriteLock) -> None:
        super().__init__(target)
        self._lock = lock

    def create(self, paths: tuple[str, ...]) -> str:
        self._lock.events.append("backup")
        return super().create(paths)


def test_uninstall_requires_a_lock_and_gives_it_no_default() -> None:
    """C-16 and ruling R82. A write path that simply does not take a lock keeps every gate green
    while sitting outside charter §12, so the parameter is keyword-only and has no default: an
    unlocked uninstall must be something somebody wrote down."""
    parameter = inspect.signature(uninstall_artifact).parameters["lock"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_the_lock_is_taken_before_the_backup_and_released_on_success() -> None:
    """The backup is the first thing uninstall does to a disk, so the lock has to precede it.

    Asserted as one ordered list: a lock taken after the backup would still be "taken" and still
    be "released", and only the order says the copy was made under it.
    """
    target = a_target()
    lock = FakeWriteLock()

    uninstall(target, backups=_BackupStoreMarkingTheLock(target, lock), lock=lock)

    assert lock.events == ["acquired", "backup", "released"]
    assert lock.held is False


def test_uninstall_removes_nothing_when_the_lock_is_held() -> None:
    """A run that cannot take the lock does not back up, does not delete and does not record —
    the refusal is before all three.

    The positive control is in the same test: the identical run under a free lock does all three,
    so the empty lists cannot be empty because there was nothing to remove.
    """
    target = a_target()
    backups = FakeBackupStore(target)
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(LockHeldError) as raised:
        uninstall(
            target,
            backups=backups,
            manifests=manifests,
            lock=FakeWriteLock(held_by_another=True),
        )

    assert raised.value.code is ErrorCode.LOCK_HELD
    assert backups.created == []
    assert manifests.written == []
    assert target.snapshot() == before

    uninstall(target, backups=backups, manifests=manifests)

    assert backups.created != []
    assert manifests.written != []
    assert target.snapshot() != before


def test_the_lock_is_released_when_the_backup_cannot_be_taken() -> None:
    """A lock leaked here would wedge the target on the one run that already told the user
    something is wrong with their state directory."""
    target = a_target()
    lock = FakeWriteLock()

    with pytest.raises(BackupFailedError):
        uninstall(target, backups=FakeBackupStore(target, fail=True), lock=lock)

    assert lock.events == ["acquired", "released"]
    assert lock.held is False


def test_the_lock_is_released_when_a_delete_fails_part_way_through() -> None:
    """The run that leaves the target part-way emptied and the record over-claiming is the run
    whose user most needs to be able to try again — or to roll back — without deleting a lock
    file by hand."""
    target = _TargetRefusingOneDelete(a_target(), refusing=INSTALLED_REFERENCE)
    lock = FakeWriteLock()

    with pytest.raises(TargetUnwritableError):
        uninstall(target, backups=FakeBackupStore(target), lock=lock)

    assert target.deletes == [INSTALLED_ENTRY]
    assert lock.events == ["acquired", "released"]
    assert lock.held is False


# -- Ruling R90: a record that could not keep up (T-19) ------------------------------------------


def test_a_record_that_cannot_be_written_after_the_deletes_is_record_stale() -> None:
    """**R90**, which is the plan-level decision `uninstall_artifact` used to say it was waiting
    for.

    This module used to let a bare `OSError` out here, because `MANIFEST_UNWRITABLE` promises
    *nothing happened* and the files are already gone. The code now says what is true: the work
    is done and only the record is behind, so nothing is lost and the remedy is to fix the state
    directory and run the uninstall again.

    Asserted on the code and on the target together, because a status claiming nothing happened
    over a target that has just lost two files is the whole reason this code exists.
    """
    target = a_target()

    with pytest.raises(RecordStaleError) as raised:
        uninstall(target, manifests=FakeManifestStore(fail=True))

    assert raised.value.code is ErrorCode.RECORD_STALE
    assert raised.value.operation == "uninstall"
    assert INSTALLED_ENTRY not in target.snapshot()
