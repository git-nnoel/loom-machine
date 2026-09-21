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

**The second apply is fired from inside the first apply's first write**, through a target
repository that calls back once. That is not a contrivance for its own sake: it is the only
moment at which the two runs really overlap, and a test that merely took the lock by hand and
then called apply would stay green even if apply released the lock before writing a byte — which
is exactly the mutation this module's first test exists to catch.

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

from harness_library.application.write import ApplyResult, apply_install
from harness_library.domain.errors import ErrorCode, LockHeldError
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
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


def a_library() -> FakeArtifactRepository:
    """Two single-file skills, both holding `LIBRARY_BYTES`."""
    artifacts = [
        make_artifact(name, files=(make_file(ENTRY, LIBRARY_BYTES),))
        for name in (SKILL_NAME, OTHER_NAME)
    ]
    return FakeArtifactRepository(
        artifacts, contents={(artifact.id, ENTRY): LIBRARY_BYTES for artifact in artifacts}
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
