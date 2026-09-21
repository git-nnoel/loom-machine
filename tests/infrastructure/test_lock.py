"""The `O_EXCL` sentinel, against real files. Charter §12, ruling R50.

Real sentinels under `tmp_path`, never a fake filesystem (charter §10) — the whole mechanism *is*
a filesystem behaviour, and a fake that answered "already exists" would be asserting its own
`if`. Every state root here is `tmp_path`; `default_state_root()` is called by nothing but the
composition root, so no test creates a real `~/.local/state/harness-library`.

**What this module cannot see.** It cannot see that an apply takes the lock, that it releases it
when the apply fails, or that a second apply consequently writes nothing. Those are
`tests/application/test_install.py` (the control flow, against a fake lock) and
`tests/test_single_writer.py` (both halves at once, against a real one). What it *can* see is the
only thing this layer decides: where the sentinel goes, when it appears and disappears, who is
refused, and which sentinels are stale.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness_library.domain.errors import ErrorCode, LockHeldError, StateUnwritableError
from harness_library.domain.lock import WriteLock
from harness_library.infrastructure.lock import (
    LOCK_SUFFIX,
    SCHEMA_VERSION,
    FilesystemWriteLock,
    lock_path_for,
)
from harness_library.infrastructure.manifest_store import (
    MANIFESTS_DIRECTORY_NAME,
    manifest_path_for,
)

HELD_AT = datetime(2026, 9, 21, 16, 45, tzinfo=UTC)
"""When every sentinel in this module was taken. A parameter, never a clock."""


def a_lock(target: Path, *, state_root: Path) -> FilesystemWriteLock:
    """One lock over a target, with the instant held still."""
    return FilesystemWriteLock(target, state_root=state_root, now=lambda: HELD_AT)


def a_target(root: Path, name: str = "target") -> Path:
    """A directory to install into. It need not hold anything; the lock never looks inside it."""
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    return target


def a_pid_that_is_gone() -> int:
    """The pid of a process that really has exited and been reaped.

    A spawned-and-waited child rather than a large literal, so the pid check is exercised against
    the same `ProcessLookupError` a crashed `hl` would produce. The precondition is asserted
    rather than assumed: if this machine managed to reuse the pid in the microseconds since, the
    test says so instead of quietly proving nothing.
    """
    with subprocess.Popen([sys.executable, "-c", ""]) as process:
        process.wait()
    try:
        os.kill(process.pid, 0)
    except ProcessLookupError:
        return process.pid
    pytest.fail(
        f"pid {process.pid} was reused between exiting and this check, so this test cannot say "
        "anything about a stale sentinel. Re-run."
    )


def write_sentinel(path: Path, text: str) -> None:
    """Put a sentinel on disk by hand, to be found by the next acquire."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sentinel_naming(pid: int) -> str:
    """A well-formed sentinel document claiming `pid` holds the lock."""
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "pid": pid,
            "hostname": "elsewhere",
            "created_at": HELD_AT.isoformat(),
        }
    )


# -------------------------------------------------------------------------------------------
# Where the sentinel goes
# -------------------------------------------------------------------------------------------


def test_the_sentinel_sits_beside_the_manifest_and_shares_its_key(tmp_path: Path) -> None:
    """R50 says *beside the manifest*, and the key is the manifest's own (R43, DEC-14).

    Derived here rather than re-hashed, so the lock and the record it guards cannot be keyed by
    two spellings of one directory — which is the whole reason `canonical_target_path` exists.
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    manifest = manifest_path_for(target, state_root=state_root)

    sentinel = lock_path_for(target, state_root=state_root)

    assert sentinel.parent == manifest.parent
    assert sentinel.stem == manifest.stem
    assert sentinel.suffix == LOCK_SUFFIX


def test_two_spellings_of_one_target_reach_one_sentinel(tmp_path: Path) -> None:
    """One directory reached two ways is one target (R43), and must be one sentinel — otherwise
    two applies into the same files would each take a lock and neither would see the other.

    A symlink rather than a trailing slash, because `Path` collapses the easy spellings on its
    own and only `canonical_target_path`'s `resolve()` collapses this one.
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    link = tmp_path / "another-name-for-it"
    link.symlink_to(target)

    assert lock_path_for(target, state_root=state_root) == lock_path_for(
        link, state_root=state_root
    )


def test_two_different_targets_get_two_different_sentinels(tmp_path: Path) -> None:
    """The positive control for the pair above, and R43's point: the lock is per target, so
    installing into two directories at once is not contention."""
    state_root = tmp_path / "state"

    assert lock_path_for(a_target(tmp_path, "one"), state_root=state_root) != lock_path_for(
        a_target(tmp_path, "two"), state_root=state_root
    )


# -------------------------------------------------------------------------------------------
# Holding and releasing
# -------------------------------------------------------------------------------------------


def test_the_sentinel_exists_while_the_lock_is_held_and_not_after(tmp_path: Path) -> None:
    """The absence assertion and its positive control, in one test: the sentinel is gone
    afterwards **and** was really there during, so "gone" cannot mean "never created"."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)

    assert not sentinel.exists()
    with a_lock(target, state_root=state_root).hold():
        assert sentinel.is_file()

    assert not sentinel.exists()


def test_the_sentinel_names_the_process_holding_it(tmp_path: Path) -> None:
    """A lock nobody can read is a lock somebody deletes. The pid is what the next run's
    staleness check reads; the hostname and the instant are for whoever is looking at a lock that
    has not moved in an hour."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)

    with a_lock(target, state_root=state_root).hold():
        document = json.loads(sentinel.read_text(encoding="utf-8"))

    assert document["pid"] == os.getpid()
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["created_at"] == HELD_AT.isoformat()
    assert document["hostname"]
    assert document["token"]


def test_the_lock_is_released_when_the_block_raises(tmp_path: Path) -> None:
    """The guarantee every failure path in apply depends on. A lock leaked on the error path is
    worse than no lock: it only bites after something has already gone wrong."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)
    lock = a_lock(target, state_root=state_root)

    with pytest.raises(RuntimeError, match="the block failed"), lock.hold():
        raise RuntimeError("the block failed")

    assert not sentinel.exists()


def test_the_state_directory_is_created_when_it_is_not_there(tmp_path: Path) -> None:
    """A first install on a fresh machine has no state root at all, and must not be the run that
    discovers it. `default_state_root()` computes and creates nothing (R66), so this does."""
    state_root = tmp_path / "never-created"
    target = a_target(tmp_path)

    with a_lock(target, state_root=state_root).hold():
        assert lock_path_for(target, state_root=state_root).is_file()


def test_two_targets_can_be_held_at_the_same_time(tmp_path: Path) -> None:
    """R43: the lock is per target, like the manifest. Two installs into two directories are not
    two writers to one thing, and refusing the second would be wrong."""
    state_root = tmp_path / "state"
    one = a_target(tmp_path, "one")
    two = a_target(tmp_path, "two")

    with a_lock(one, state_root=state_root).hold(), a_lock(two, state_root=state_root).hold():
        assert lock_path_for(one, state_root=state_root).is_file()
        assert lock_path_for(two, state_root=state_root).is_file()


# -------------------------------------------------------------------------------------------
# Exclusion
# -------------------------------------------------------------------------------------------


def test_a_second_lock_on_a_held_target_is_refused(tmp_path: Path) -> None:
    """`LOCK_HELD = 10`, and the error names where to look and who to wait for."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)
    first = a_lock(target, state_root=state_root)
    second = a_lock(target, state_root=state_root)

    # Entering `second.hold()` **is** the call under test (L48), so `pytest.raises` covers that
    # and the already-held `first` is entered outside it.
    with first.hold(), pytest.raises(LockHeldError) as raised, second.hold():
        pass

    assert raised.value.code is ErrorCode.LOCK_HELD
    assert raised.value.path == str(sentinel)
    assert raised.value.pid == os.getpid()


def test_a_sentinel_naming_this_very_process_is_still_refused(tmp_path: Path) -> None:
    """The lock is per **target**, not per process. Two threads in one `hl` interleaving two
    applies is the same corruption as two processes doing it, so "the holder is me" is not a
    reason to proceed — and it is exactly what the test above relies on."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    write_sentinel(lock_path_for(target, state_root=state_root), sentinel_naming(os.getpid()))
    lock = a_lock(target, state_root=state_root)

    with pytest.raises(LockHeldError), lock.hold():
        pass


def test_a_refused_lock_leaves_the_sentinel_alone(tmp_path: Path) -> None:
    """The refusal must not disturb the holder's own sentinel — a release that removed one it did
    not create would hand the target to a third run."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)
    held = sentinel_naming(os.getpid())
    write_sentinel(sentinel, held)
    lock = a_lock(target, state_root=state_root)

    with pytest.raises(LockHeldError), lock.hold():
        pass

    assert sentinel.read_text(encoding="utf-8") == held


# -------------------------------------------------------------------------------------------
# Staleness — the half that keeps a crashed run from wedging the tool forever
# -------------------------------------------------------------------------------------------


def test_a_sentinel_whose_process_is_gone_is_broken(tmp_path: Path) -> None:
    """R50's pid check. A sentinel nobody is holding must not wedge the target: that is the
    failure mode that makes people delete lock files by hand and lose the protection entirely."""
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)
    write_sentinel(sentinel, sentinel_naming(a_pid_that_is_gone()))

    with a_lock(target, state_root=state_root).hold():
        document = json.loads(sentinel.read_text(encoding="utf-8"))

    assert document["pid"] == os.getpid()
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("", id="empty"),
        pytest.param("{", id="not-json"),
        pytest.param(
            json.dumps({"schema_version": SCHEMA_VERSION, "hostname": "elsewhere"}),
            id="no-pid",
        ),
        pytest.param(
            json.dumps({"schema_version": SCHEMA_VERSION, "pid": "me"}),
            id="a-pid-that-is-not-a-number",
        ),
        pytest.param(
            json.dumps({"schema_version": 99, "pid": 1}),
            id="a-schema-version-this-build-does-not-read",
        ),
    ],
)
def test_a_sentinel_that_cannot_name_a_holder_is_broken(tmp_path: Path, content: str) -> None:
    """**Empty is the important row.** A crash between `O_EXCL` and the first `write` leaves
    exactly that, which is the same crash the pid check exists to recover from; refusing on it
    would wedge the target on the one failure the mechanism is for.

    The others follow from the same rule: a document that cannot name a holder cannot claim one
    is alive. This is `backup.py`'s quiet posture, not `read_manifest`'s loud one, and the
    difference is what each failure costs — see `infrastructure/lock.py`.
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    write_sentinel(lock_path_for(target, state_root=state_root), content)

    with a_lock(target, state_root=state_root).hold():
        held = lock_path_for(target, state_root=state_root).read_text(encoding="utf-8")

    assert json.loads(held)["pid"] == os.getpid()


@pytest.mark.parametrize("pid", [0, -1])
def test_a_sentinel_holding_a_nonsense_pid_is_broken_and_never_signalled(
    tmp_path: Path, pid: int
) -> None:
    """`os.kill(0, 0)` addresses this whole process group and `os.kill(-1, 0)` every process this
    user owns. The guard that keeps those out of the liveness check is not decoration, and a
    sentinel holding one of them is broken like any other that names no believable holder.

    The assertion is that the lock is taken: signalling cannot be observed from here, and a
    delivered signal 0 changes nothing even when it arrives — which is precisely why the guard
    has to be a rule rather than something a test would notice the absence of.
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)
    write_sentinel(sentinel, sentinel_naming(pid))

    with a_lock(target, state_root=state_root).hold():
        assert json.loads(sentinel.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_a_release_does_not_remove_a_sentinel_it_did_not_create(tmp_path: Path) -> None:
    """The token written at acquire, earning its keep.

    A run whose own sentinel was broken as stale — unlikely under the pid check, not impossible —
    must not then delete the sentinel of the run that broke it and hand the target to a third.
    The replacement is written here by hand, which is what "somebody else now holds it" looks
    like from this process's side.

    **This test is why the identity is a token and not the inode.** The first implementation
    compared `st_ino` and this test failed: the filesystem handed the just-freed inode straight
    back to the replacement, so the sentinel written to be refused carried the number that says
    "mine". An identity a filesystem is free to reuse is not one.
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    sentinel = lock_path_for(target, state_root=state_root)
    successor = sentinel_naming(os.getpid())

    with a_lock(target, state_root=state_root).hold():
        sentinel.unlink()
        write_sentinel(sentinel, successor)

    assert sentinel.read_text(encoding="utf-8") == successor


# -------------------------------------------------------------------------------------------
# The seam
# -------------------------------------------------------------------------------------------


def test_the_filesystem_lock_is_the_write_lock_seam(tmp_path: Path) -> None:
    """Satisfied structurally, never inherited — the shape ruling R14 settled for C-4."""
    assert isinstance(a_lock(a_target(tmp_path), state_root=tmp_path / "state"), WriteLock)
    assert issubclass(FilesystemWriteLock, WriteLock)


# -- A state root that will not take the sentinel (ruling R111, T-24) ----------------------------
#
# This module had no `except OSError` at all until T-24, which made the acquire the one disk step
# of a write run with no code: a read-only mount, a full disk or a `~/.local/state` one `sudo`
# run left owned by root reached the user as a raw traceback and exit 1 on every write command.
#
# The pair below is the whole distinction. Both are the lock refusing to hand over a target and
# both guarantee that nothing was written; they differ in what a user must do, and the codes are
# what tell them apart. `LockHeldError` is not an `OSError`, so the refusal above passes through
# the new translation untouched — which is what makes that test this one's control.


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a mode-500 directory regardless")
def test_a_state_directory_that_will_not_take_the_sentinel_is_state_unwritable(
    tmp_path: Path,
) -> None:
    """**Ruling R111.** `STATE_UNWRITABLE`, and not a `PermissionError` out of `os.open`.

    Simulated with a read-only `manifests/` directory, which is where the sentinel goes — the
    same shape `tests/infrastructure/test_backup.py` uses for a state root that will not take a
    backup, and the shape T-23 found the traceback with.
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    manifests = state_root / MANIFESTS_DIRECTORY_NAME
    manifests.mkdir(parents=True)
    manifests.chmod(0o500)
    try:
        with (
            pytest.raises(StateUnwritableError) as raised,
            a_lock(target, state_root=state_root).hold(),
        ):
            pass  # pragma: no cover - the acquire raises before the block runs
    finally:
        manifests.chmod(0o700)

    assert raised.value.code is ErrorCode.STATE_UNWRITABLE
    assert raised.value.path == str(lock_path_for(target, state_root=state_root))


@pytest.mark.skipif(os.geteuid() == 0, reason="root creates a directory under a mode-500 parent")
def test_a_state_root_that_cannot_be_created_is_state_unwritable_too(tmp_path: Path) -> None:
    """The `mkdir` and the `os.open` are one condition and take one code.

    Both are "the state directory would not take the sentinel", both happen before the backup,
    the record and the first file, and a user fixes both the same way. Asserted because the
    translation is a single `except OSError` around the whole acquire rather than one per
    syscall: a rule stated at four call sites is a rule three of them can keep while the fourth
    returns a traceback.
    """
    parent = tmp_path / "read-only"
    parent.mkdir()
    parent.chmod(0o500)
    target = a_target(tmp_path)
    try:
        with (
            pytest.raises(StateUnwritableError),
            a_lock(target, state_root=parent / "state").hold(),
        ):
            pass  # pragma: no cover - the acquire raises before the block runs
    finally:
        parent.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a mode-500 directory regardless")
def test_an_unwritable_state_root_is_not_reported_as_a_held_lock(tmp_path: Path) -> None:
    """**The two refusals must not be one.** `LOCK_HELD` sends a user to wait for another run;
    there is no other run, and waiting for it will not make `~/.local/state` writable again.

    The positive control is `test_a_second_lock_on_a_held_target_is_refused` above, which still
    raises `LockHeldError` — so "not a held lock" cannot mean "nothing is ever a held lock".
    """
    state_root = tmp_path / "state"
    target = a_target(tmp_path)
    manifests = state_root / MANIFESTS_DIRECTORY_NAME
    manifests.mkdir(parents=True)
    manifests.chmod(0o500)
    try:
        with (
            pytest.raises(StateUnwritableError) as raised,
            a_lock(target, state_root=state_root).hold(),
        ):
            pass  # pragma: no cover - the acquire raises before the block runs
    finally:
        manifests.chmod(0o700)

    assert not isinstance(raised.value, LockHeldError)
    assert raised.value.code is not ErrorCode.LOCK_HELD
