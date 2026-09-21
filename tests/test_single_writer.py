"""Charter §12, ruling R50 — the lock and the thing it protects, in one place.

**The only cross-layer module in this suite, and it has to be.** The exclusion is a sentinel file
in `infrastructure/` and the thing it guards is a use case in `application/`; neither layer alone
can witness "a second apply writes nothing", because at the application layer the lock is a fake
that cannot exclude anything and at the infrastructure layer there is no apply to exclude. Every
other guarantee in this initiative is visible from one side. This one is not.

So: a real `FilesystemWriteLock`, a real `FilesystemTargetRepository`, a real manifest store, a
real backup store, and a real `apply_install`. The library is the application fake, because the
library side is not what is being proven here and a real one would drag a fixture tree in with
no bearing on the lock.

**The second run is fired from inside the first run's first write**, through a wrapper that
calls back once. That is not a contrivance for its own sake: it is the only moment at which the
two runs really overlap, and a test that merely took the lock by hand and then called the use
case would stay green even if the use case released the lock before touching a byte — which is
exactly the mutation this module's first test exists to catch.

**T-18 adds rollback's and uninstall's witnesses here** rather than in a third cross-layer module,
because they are the same claim about the same sentinel over two more write use cases (C-16, R82).
Each keeps the shape above: uninstall's callback hangs off the first `delete`, and rollback's off
the entry to `restore` — the moment the run is between taking the lock and moving a byte, which is
the window an early release opens.

Nothing here writes outside `tmp_path`. Every state root and every target is a temporary
directory, and `default_state_root()` is not called.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness_library.application.write import (
    ApplyResult,
    RollbackResult,
    UninstallResult,
    apply_install,
    rollback_install,
    uninstall_artifact,
)
from harness_library.domain.backup import BackupRecord, BackupStore
from harness_library.domain.errors import ErrorCode, LockHeldError
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.manifest import Manifest
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.target import TargetFile, TargetRepository
from harness_library.infrastructure.backup import FilesystemBackupStore
from harness_library.infrastructure.lock import (
    SCHEMA_VERSION,
    FilesystemWriteLock,
    lock_path_for,
)
from harness_library.infrastructure.manifest_store import FilesystemManifestStore
from harness_library.infrastructure.target import FilesystemTargetRepository
from tests.application.fakes import FakeArtifactRepository, make_artifact, make_file

SKILL_NAME = "delivery-lead"
SKILL_ID = "skill/delivery-lead"
OTHER_NAME = "phase-reviewer"
OTHER_ID = "skill/phase-reviewer"
ENTRY = "SKILL.md"

INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"
INSTALLED_OTHER = "skills/phase-reviewer/SKILL.md"

FOREIGN = "settings.json"
FOREIGN_BYTES = b'{"theme": "dark"}\n'
LIBRARY_BYTES = b"# what the library holds\n"
LATER_BYTES = b"# what the library holds after it moved on\n"
"""A second version, so an apply over an installed target really changes a byte — which is what
lets a rollback of it be *seen*. T-18."""

INSTALLED_AT = datetime(2026, 9, 21, 16, 45, tzinfo=UTC)
"""When every apply in this module ran. A parameter, never a clock."""


# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


def a_target(root: Path, name: str = "target") -> Path:
    """A real install target holding one file this tool did not put there."""
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / FOREIGN).write_bytes(FOREIGN_BYTES)
    return target


def a_library(body: bytes = LIBRARY_BYTES) -> FakeArtifactRepository:
    """Two single-file skills, both holding `body`.

    The parameter is T-18's and defaults to what every existing caller passed implicitly, so a
    second version of the same library is one argument rather than a second helper.
    """
    artifacts = [
        make_artifact(name, files=(make_file(ENTRY, body),)) for name in (SKILL_NAME, OTHER_NAME)
    ]
    return FakeArtifactRepository(
        artifacts, contents={(artifact.id, ENTRY): body for artifact in artifacts}
    )


def a_plan() -> InstallPlan:
    """Install both skills into a target that holds neither."""
    return InstallPlan(
        entries=(
            PlanEntry(
                artifact_id=SKILL_ID,
                path=INSTALLED_ENTRY,
                verdict=Verdict.CREATE,
                library_sha=hash_bytes(LIBRARY_BYTES),
                manifest_sha=None,
                target_sha=None,
            ),
            PlanEntry(
                artifact_id=OTHER_ID,
                path=INSTALLED_OTHER,
                verdict=Verdict.CREATE,
                library_sha=hash_bytes(LIBRARY_BYTES),
                manifest_sha=None,
                target_sha=None,
            ),
        )
    )


def hash_set(root: Path) -> dict[str, str]:
    """Every file under `root` and its digest. Content, never mtime (L37).

    `domain.hashing.hash_bytes` and not a second `hashlib` call, for the reason charter §7 gives:
    two hashing routines over one rule agree until they do not.
    """
    return {
        str(path.relative_to(root)): hash_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def an_installed_target() -> dict[str, str]:
    """What `hash_set` returns for a target both skills have been installed into."""
    return {
        FOREIGN: hash_bytes(FOREIGN_BYTES),
        INSTALLED_ENTRY: hash_bytes(LIBRARY_BYTES),
        INSTALLED_OTHER: hash_bytes(LIBRARY_BYTES),
    }


def run_apply(
    *,
    library: ArtifactRepository,
    target_root: Path,
    state_root: Path,
    target: TargetRepository | None = None,
) -> ApplyResult:
    """One real apply into `target_root`, under a real lock over `state_root`."""
    return apply_install(
        a_plan(),
        library,
        target if target is not None else FilesystemTargetRepository(target_root),
        FilesystemBackupStore(state_root, target_root, now=lambda: INSTALLED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: INSTALLED_AT),
        manifest=None,
        target_path=str(target_root),
        installed_at=INSTALLED_AT,
    )


class TargetCallingBackOnItsFirstWrite:
    """Contract C-12 over a real target, with a hook on the first write.

    The hook is what makes two applies genuinely overlap: it runs after the first apply has taken
    the lock, taken its backup and written its manifest, and before the first byte reaches the
    target. Everything else is delegated, so what the first apply does to the disk is exactly
    what `FilesystemTargetRepository` would have done.
    """

    def __init__(self, inner: FilesystemTargetRepository, on_first_write: Callable[[], None]):
        self._inner = inner
        self._on_first_write = on_first_write
        self._fired = False

    def scan(self) -> tuple[TargetFile, ...]:
        return self._inner.scan()

    def read_bytes(self, path: str) -> bytes:
        return self._inner.read_bytes(path)

    def write(self, path: str, data: bytes) -> None:
        if not self._fired:
            self._fired = True
            self._on_first_write()
        self._inner.write(path, data)

    def delete(self, path: str) -> None:
        self._inner.delete(path)

    def exists(self, path: str) -> bool:
        return self._inner.exists(path)


@dataclass
class SecondRun:
    """What happened to an apply fired from inside another one. Evidence, not a verdict."""

    refused: LockHeldError | None = None
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)


def a_pid_that_is_gone() -> int:
    """The pid of a process that really has exited and been reaped.

    The same helper `tests/infrastructure/test_lock.py` keeps, and deliberately a second copy:
    that module proves the lock's own staleness rule and this one proves what an apply does about
    it, and a shared helper between two modules at two layers is a coupling neither needs.
    """
    with subprocess.Popen([sys.executable, "-c", ""]) as process:
        process.wait()
    try:
        os.kill(process.pid, 0)
    except ProcessLookupError:
        return process.pid
    pytest.fail(f"pid {process.pid} was reused, so this test cannot prove anything. Re-run.")


# -------------------------------------------------------------------------------------------
# F-14 — a second apply against a held lock
# -------------------------------------------------------------------------------------------


def test_a_second_apply_against_a_held_lock_writes_nothing(tmp_path: Path) -> None:
    """**F-14, and the must-fail assertion of T-17's mutation** (release the lock before the
    write instead of after).

    The second apply starts while the first is between its manifest and its first file — the
    exact window in which two runs can interleave and leave a target holding half of each plan
    with a manifest describing neither. It must be refused with `LOCK_HELD` and it must leave the
    target untouched, and **both** are asserted, because a refusal that still wrote is the
    failure and a silence that wrote nothing would not tell a script anything.

    Asserted on the target's **hash set**, never on either run's report: a report saying "I wrote
    nothing" is exactly what the wrong implementation also says.

    The positive control is the last assertion: the first apply really does change the target, so
    "unchanged" cannot mean "this harness never writes".
    """
    state_root = tmp_path / "state"
    target_root = a_target(tmp_path)
    library = a_library()
    second = SecondRun()

    def a_second_apply_while_the_first_is_writing() -> None:
        second.before = hash_set(target_root)
        try:
            run_apply(library=library, target_root=target_root, state_root=state_root)
        except LockHeldError as refused:
            second.refused = refused
        second.after = hash_set(target_root)

    run_apply(
        library=library,
        target_root=target_root,
        state_root=state_root,
        target=TargetCallingBackOnItsFirstWrite(
            FilesystemTargetRepository(target_root), a_second_apply_while_the_first_is_writing
        ),
    )

    assert isinstance(second.refused, LockHeldError), (
        "the second apply was not refused: while one apply holds this target's lock, another must "
        "exit LOCK_HELD rather than interleaving its writes with the first's (R50)"
    )
    assert second.refused.code is ErrorCode.LOCK_HELD
    assert second.after == second.before, (
        "the second apply changed the target although it was refused: LOCK_HELD means nothing "
        "was written, and the lock is taken before the backup so that it can"
    )
    assert hash_set(target_root) != second.before


def test_a_single_apply_writes_every_file_and_leaves_no_sentinel(tmp_path: Path) -> None:
    """**The must-stay-green control** of the mutation above.

    Without it, "the lock is never taken" and "the lock is released too early" are the same
    result: both leave a suite in which the only failing test is the second-apply one. This says
    the ordinary case still works — every file written, the foreign file untouched, and the
    sentinel gone afterwards, so a run that succeeded leaves nothing for the next one to break.
    """
    state_root = tmp_path / "state"
    target_root = a_target(tmp_path)

    result = run_apply(library=a_library(), target_root=target_root, state_root=state_root)

    assert hash_set(target_root) == an_installed_target()
    assert result.written == (INSTALLED_ENTRY, INSTALLED_OTHER)
    assert not lock_path_for(target_root, state_root=state_root).exists()


def test_a_stale_sentinel_whose_process_is_gone_is_broken_and_the_apply_proceeds(
    tmp_path: Path,
) -> None:
    """**F-14's second half, and the must-fail assertion of this task's own mutation** (never
    break a stale sentinel).

    A sentinel left by a process that is no longer running must not wedge the target forever.
    That is the failure mode that makes people delete lock files by hand — and a user who has
    learnt to do that has lost the protection entirely, on every run, not just this one.

    Asserted on the **installed file's bytes**: the apply has to actually happen, not merely
    decline to raise.
    """
    state_root = tmp_path / "state"
    target_root = a_target(tmp_path)
    sentinel = lock_path_for(target_root, state_root=state_root)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "pid": a_pid_that_is_gone(),
                "hostname": "a machine that went down",
                "created_at": INSTALLED_AT.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert sentinel.is_file()

    run_apply(library=a_library(), target_root=target_root, state_root=state_root)

    assert (target_root / INSTALLED_ENTRY).read_bytes() == LIBRARY_BYTES
    assert (target_root / INSTALLED_OTHER).read_bytes() == LIBRARY_BYTES
    assert not sentinel.exists()


def test_two_targets_are_installed_into_concurrently(tmp_path: Path) -> None:
    """**R43: the lock is per target, like the manifest.** Two installs into two directories are
    not two writers to one thing, and a lock that refused the second would make `--target` useless
    for the case it exists for.

    The second install runs from inside the first's write loop, so the two really are concurrent
    rather than merely consecutive — which is the same construction the refusal test uses, and
    the reason this is the honest control for it.
    """
    state_root = tmp_path / "state"
    one = a_target(tmp_path, "one")
    two = a_target(tmp_path, "two")
    library = a_library()
    results: list[ApplyResult] = []

    def install_into_the_other_target() -> None:
        results.append(run_apply(library=library, target_root=two, state_root=state_root))

    run_apply(
        library=library,
        target_root=one,
        state_root=state_root,
        target=TargetCallingBackOnItsFirstWrite(
            FilesystemTargetRepository(one), install_into_the_other_target
        ),
    )

    assert [result.written for result in results] == [(INSTALLED_ENTRY, INSTALLED_OTHER)]
    assert hash_set(one) == an_installed_target()
    assert hash_set(two) == an_installed_target()


# -------------------------------------------------------------------------------------------
# C-16 / R82 — the other two write use cases, under the same sentinel (T-18)
# -------------------------------------------------------------------------------------------


def run_uninstall(
    *,
    target_root: Path,
    state_root: Path,
    manifest: Manifest,
    target: TargetRepository | None = None,
) -> UninstallResult:
    """One real uninstall of `SKILL_ID` from `target_root`, under a real lock."""
    return uninstall_artifact(
        target if target is not None else FilesystemTargetRepository(target_root),
        FilesystemBackupStore(state_root, target_root, now=lambda: INSTALLED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: INSTALLED_AT),
        manifest=manifest,
        artifact_id=SKILL_ID,
        installed_at=INSTALLED_AT,
    )


def run_rollback(
    *,
    target_root: Path,
    state_root: Path,
    manifest: Manifest,
    backup_id: str,
    backups: BackupStore | None = None,
) -> RollbackResult:
    """One real rollback of `target_root`, under a real lock."""
    return rollback_install(
        FilesystemTargetRepository(target_root),
        backups
        if backups is not None
        else FilesystemBackupStore(state_root, target_root, now=lambda: INSTALLED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: INSTALLED_AT),
        manifest=manifest,
        backup_id=backup_id,
        installed_at=INSTALLED_AT,
    )


class TargetCallingBackOnItsFirstDelete:
    """Contract C-12 over a real target, with a hook on the first delete.

    Uninstall's equivalent of `TargetCallingBackOnItsFirstWrite`, and the same argument: the hook
    runs after the first uninstall has taken the lock and its backup, and before the first file
    leaves the target. Everything else is delegated, so what the first run does to the disk is
    exactly what `FilesystemTargetRepository` would have done.
    """

    def __init__(self, inner: FilesystemTargetRepository, on_first_delete: Callable[[], None]):
        self._inner = inner
        self._on_first_delete = on_first_delete
        self._fired = False

    def scan(self) -> tuple[TargetFile, ...]:
        return self._inner.scan()

    def read_bytes(self, path: str) -> bytes:
        return self._inner.read_bytes(path)

    def write(self, path: str, data: bytes) -> None:
        self._inner.write(path, data)

    def delete(self, path: str) -> None:
        if not self._fired:
            self._fired = True
            self._on_first_delete()
        self._inner.delete(path)

    def exists(self, path: str) -> bool:
        return self._inner.exists(path)


class BackupStoreCallingBackOnRestore:
    """Contract C-13 over a real store, with a hook fired as a restore begins.

    Rollback writes nothing through the target itself — the bytes are the store's, and
    `FilesystemBackupStore` reaches the target through a repository it builds for itself — so the
    hook goes here. It fires while the first rollback is **between taking the lock and moving a
    byte**, which is precisely the window a lock released before the work opens: under an early
    release the second run would take the lock, restore the whole backup, and the target would
    change under the first run's feet.
    """

    def __init__(self, inner: FilesystemBackupStore, on_restore: Callable[[], None]):
        self._inner = inner
        self._on_restore = on_restore
        self._fired = False

    def create(self, paths: tuple[str, ...]) -> str:
        return self._inner.create(paths)

    def restore(self, backup_id: str) -> None:
        if not self._fired:
            self._fired = True
            self._on_restore()
        self._inner.restore(backup_id)

    def list(self) -> tuple[BackupRecord, ...]:
        return self._inner.list()


def test_a_second_uninstall_against_a_held_lock_removes_nothing(tmp_path: Path) -> None:
    """**C-16 for uninstall, in the shape L50 requires.**

    The second uninstall starts while the first is between its backup and its first delete —
    the window in which two runs can interleave and leave one of them writing a record about
    files the other has already removed. It must be refused with `LOCK_HELD` and it must leave
    the target untouched, and both are asserted.

    Asserted on the target's **hash set** across the second run, never on either report: a
    report saying "I removed nothing" is exactly what the wrong implementation also says. The
    positive control is the last assertion — the first uninstall really does remove the file, so
    "unchanged" cannot mean "this use case never deletes".
    """
    state_root = tmp_path / "state"
    target_root = a_target(tmp_path)
    installed = run_apply(library=a_library(), target_root=target_root, state_root=state_root)
    second = SecondRun()

    def a_second_uninstall_while_the_first_is_deleting() -> None:
        second.before = hash_set(target_root)
        try:
            run_uninstall(
                target_root=target_root, state_root=state_root, manifest=installed.manifest
            )
        except LockHeldError as refused:
            second.refused = refused
        second.after = hash_set(target_root)

    run_uninstall(
        target_root=target_root,
        state_root=state_root,
        manifest=installed.manifest,
        target=TargetCallingBackOnItsFirstDelete(
            FilesystemTargetRepository(target_root), a_second_uninstall_while_the_first_is_deleting
        ),
    )

    assert isinstance(second.refused, LockHeldError), (
        "the second uninstall was not refused: while one writer holds this target's lock another "
        "must exit LOCK_HELD rather than interleaving its deletes with the first's (R50, R82)"
    )
    assert second.refused.code is ErrorCode.LOCK_HELD
    assert second.after == second.before, (
        "the second uninstall changed the target although it was refused: LOCK_HELD means "
        "nothing was removed, and the lock is taken before the backup so that it can"
    )
    assert INSTALLED_ENTRY not in hash_set(target_root)


def test_a_second_rollback_against_a_held_lock_restores_nothing(tmp_path: Path) -> None:
    """**C-16 for rollback, in the shape L50 requires.**

    The second rollback starts while the first holds the lock and has not yet moved a byte. Under
    a lock released too early it would restore the whole backup there and then, and the target
    would change inside the callback — which is what the hash set across the second run says.

    The positive control is the last assertion: the first rollback really does put the earlier
    bytes back, so "unchanged" cannot mean "this use case never restores".
    """
    state_root = tmp_path / "state"
    target_root = a_target(tmp_path)
    run_apply(library=a_library(), target_root=target_root, state_root=state_root)
    updated = run_apply(
        library=a_library(LATER_BYTES), target_root=target_root, state_root=state_root
    )
    assert updated.backup_id is not None
    assert hash_set(target_root)[INSTALLED_ENTRY] == hash_bytes(LATER_BYTES)
    second = SecondRun()

    def a_second_rollback_while_the_first_is_restoring() -> None:
        second.before = hash_set(target_root)
        try:
            run_rollback(
                target_root=target_root,
                state_root=state_root,
                manifest=updated.manifest,
                backup_id=str(updated.backup_id),
            )
        except LockHeldError as refused:
            second.refused = refused
        second.after = hash_set(target_root)

    run_rollback(
        target_root=target_root,
        state_root=state_root,
        manifest=updated.manifest,
        backup_id=updated.backup_id,
        backups=BackupStoreCallingBackOnRestore(
            FilesystemBackupStore(state_root, target_root, now=lambda: INSTALLED_AT),
            a_second_rollback_while_the_first_is_restoring,
        ),
    )

    assert isinstance(second.refused, LockHeldError), (
        "the second rollback was not refused: while one writer holds this target's lock another "
        "must exit LOCK_HELD rather than restoring over the top of it (R50, R82)"
    )
    assert second.refused.code is ErrorCode.LOCK_HELD
    assert second.after == second.before, (
        "the second rollback changed the target although it was refused: LOCK_HELD means nothing "
        "was restored"
    )
    assert hash_set(target_root)[INSTALLED_ENTRY] == hash_bytes(LIBRARY_BYTES)
