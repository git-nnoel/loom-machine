"""Ruling R50 on disk — the `O_EXCL` sentinel that keeps two applies out of one target.

```
<state_root>/manifests/<sha256 of the target path>.lock
```

**Beside the manifest, and keyed by the manifest's own key.** Not "in the same directory by
coincidence": the path is `manifest_store.manifest_path_for(...)` with its suffix changed, so the
lock and the record it guards can never be keyed two different ways. `canonical_target_path`
already collapses every spelling of one directory into one key (R43), and a second derivation of
that key is a second answer to "which target is this" — exactly the drift DEC-14 avoided by
hashing the path once.

Per target, therefore. Installing into `~/.claude` and into a staging directory at the same time
is two sentinels and no contention, which is the point of R43's keying.

**Why a sentinel and not `flock`.** An advisory `flock` is released when the process dies, which
sounds strictly better and is worse here: nothing is left behind for a human to see, so a lock
that *is* held and a lock that was never taken look identical from the outside, and a state root
on a filesystem that does not honour `flock` fails open silently. A file that names its holder can
be read with `cat`, and R50 fixes this mechanism rather than leaving it to a specialist.

## Staleness, and what the pid check can and cannot do

A sentinel whose process is gone must not wedge the tool forever — that is the failure mode that
makes people delete lock files by hand and lose the protection entirely. So the holder's pid is
written into the sentinel and checked with `os.kill(pid, 0)`:

* **alive** — refused, `LockHeldError`. Including when the pid is *this* process: the lock is per
  target, not per process, and two applies interleaving inside one process is the same corruption
  as two processes doing it.
* **gone** — the sentinel is removed and the create is retried once. If that retry also collides,
  another run won the same race and this one is refused.
* **unreadable, or naming no pid at all** — treated as gone. An empty sentinel is exactly what a
  crash between `O_EXCL` and the first `write` leaves behind, and a document that cannot name a
  holder cannot claim one is alive.

Two things the check does **not** do, both of which fail safe. A **reused pid** reads as alive, so
the lock is refused rather than broken — the remedy is the one `LOCK_HELD` already prints, wait
and run again. And a sentinel written on **another host**, if a state root is ever shared over a
network filesystem, has its pid compared against this machine's process table, which is
meaningless; `hostname` is recorded so a human can see that, and R50's decision is a pid check, so
the code does not act on it.

**The state root is a parameter, never the environment** — charter §13 and ruling R66, the same
rule `manifest_store` keeps. Nothing here reads `$XDG_STATE_HOME` or `Path.home()`.

## A state root that will not take the sentinel

Ruling **R111**, T-24. This module had no `except OSError` at all, which made it the one disk
step of a write run with no code: a read-only mount, a full disk, or a `~/.local/state` a `sudo`
run left owned by root gave `install`, `uninstall`, `rollback` and `clean --remove` a raw
traceback and exit 1 — outside contract C-14's table, so a script could not tell it from
anything else that goes wrong.

`_acquire` translates it to `StateUnwritableError` (`STATE_UNWRITABLE`, exit 15). Translated
**here** rather than in `application/`, against the direction ruling R24 sets for the backup
store and the target repository, because `hold()` wraps a whole use-case body: a `try` around it
in the use case would catch the backup's and the target's failures too, and answer a half-written
target with a code whose whole content is *nothing was written*. `LockHeldError` has been raised
from this class since T-17 for the same reason — a judgement only the lock can make.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loom.domain.errors import LockHeldError, StateUnwritableError
from loom.infrastructure.manifest_store import manifest_path_for

LOCK_SUFFIX = ".lock"
"""What the sentinel's name is, given the manifest's. See `lock_path_for`."""

SCHEMA_VERSION = 1
"""The version of the sentinel document.

The same reasoning as the manifest's and the backup record's, with the opposite consequence: a
sentinel this build cannot read is **breakable**, not a loud failure, because a lock is a
statement about a live process and an unreadable one cannot make it.
"""

SENTINEL_MODE = 0o644
"""The mode the sentinel is created with, set explicitly for the reason `target.FILE_MODE` is: a
strict umask would otherwise leave a lock another of the user's own sessions cannot read."""

_ENCODING = "utf-8"


def lock_path_for(target: Path, *, state_root: Path) -> Path:
    """This target's sentinel — the manifest's path with `.lock` in place of `.json`.

    Derived from `manifest_path_for` rather than re-hashed here, so "beside the manifest" (R50) is
    a fact about the code and not a comment, and so the lock and the manifest cannot end up keyed
    by two spellings of one directory.
    """
    return manifest_path_for(target, state_root=state_root).with_suffix(LOCK_SUFFIX)


class FilesystemWriteLock:
    """The single-writer advisory lock for one target. Implements `domain.lock.WriteLock`.

    The protocol stays in `domain/lock.py` and is satisfied structurally — this class does not
    inherit it — which is the shape ruling R14 settled for C-4 and C-12, C-13 and C-15 keep.

    Holds no state between calls but the path and the clock: everything that says whether the lock
    is held lives in the sentinel, because the next run is a different process and can only read
    the disk.
    """

    def __init__(
        self,
        target: Path,
        *,
        state_root: Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind the lock to one target under one state root.

        Args:
            target: the install target this lock is for. Any spelling of it; `lock_path_for`
                canonicalises through the manifest's key (R43).
            state_root: the directory the manifests live under.
                `manifest_store.default_state_root()` in production, `tmp_path` in every test —
                nothing here reads the environment (charter §13, R66).
            now: the clock the sentinel's `created_at` comes from. Defaults to the real one; a
                test passes a fixed instant, for the reason `FilesystemBackupStore` takes one.
        """
        self._path = lock_path_for(target, state_root=state_root)
        self._now = now if now is not None else (lambda: datetime.now(UTC))

    @property
    def path(self) -> Path:
        """Where the sentinel is. Read by a test and by a diagnosis; never by a decision."""
        return self._path

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Take the lock, run the block, and release the lock however the block ends.

        The release is in a `finally` and that is the whole of it: apply can abort at the backup,
        at the manifest or part-way through the files, and a lock leaked on one of those paths
        only bites after something has already gone wrong.

        Raises:
            LockHeldError: a live process holds this target's lock. Nothing has been written.
            StateUnwritableError: the state directory could not be created or the sentinel could
                not be written. **Ruling R111** — until T-24 this was left as a builtin, on the
                argument that it was an ordinary I/O fault with no code of its own, and T-23
                found what that costs: a read-only mount, a full disk or a `~/.local/state` one
                `sudo` run left owned by root gave a raw traceback and exit 1 on every write
                command. Nothing has been written either way; see `_acquire`.
        """
        token = self._acquire()
        try:
            yield
        finally:
            self._release(token)

    # -- Acquire ---------------------------------------------------------------------------------

    def _acquire(self) -> str:
        """`_take`, with every disk fault under it given contract C-14's code. Ruling R111.

        **One `except OSError` and not one per syscall.** `_take` reaches the disk four times —
        the `mkdir`, two `os.open`s and the `unlink` of a stale sentinel — and a translation
        repeated at each of them is a rule stated four times, which is a rule a mutation cannot
        break: three of the four would keep the code alive while the fourth returned a
        traceback. Stated once, it is one line to get wrong and one line to check.

        Nothing else can arrive here. `LockHeldError` is not an `OSError`, so the refusal passes
        through untouched, and `_holder` swallows its own read failures — every `OSError` out of
        `_take` is the state directory, and the guarantee `StateUnwritableError` carries (the
        lock precedes the backup, the record and the first file) holds for all four of them.

        Raises:
            LockHeldError: a live process holds this target's lock.
            StateUnwritableError: the state directory would not take the sentinel.
        """
        try:
            return self._take()
        except OSError as error:
            raise StateUnwritableError(str(self._path), str(error)) from error

    def _take(self) -> str:
        """Create the sentinel, breaking a stale one. Returns the token it wrote into it.

        The token, and not merely "it worked": `_release` reads it back before unlinking, so a
        run whose own sentinel was broken as stale cannot then delete the sentinel of the run
        that broke it and hand the target to a third.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        try:
            self._create(token)
        except FileExistsError:
            pass
        else:
            return token

        holder = self._holder()
        if holder is not None and _is_running(holder):
            raise LockHeldError(str(self._path), pid=holder)

        # Stale: the process that left this is gone, or the document cannot name one. Remove it
        # and try once more — a second collision means another run broke the same sentinel first,
        # and the honest answer to that is the same as to any other held lock.
        self._path.unlink(missing_ok=True)
        try:
            self._create(token)
        except FileExistsError as error:
            raise LockHeldError(str(self._path)) from error
        return token

    def _create(self, token: str) -> None:
        """`O_EXCL` — the exclusion itself. Raises `FileExistsError` when the lock is taken."""
        descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, SENTINEL_MODE)
        try:
            os.write(descriptor, self._document(token))
        finally:
            os.close(descriptor)

    def _document(self, token: str) -> bytes:
        """What is in the sentinel: who holds it, where, since when, and under which name.

        `token` is a name no other acquire has, and it is what makes "is this still *my*
        sentinel" answerable at release. **Not the inode**, which was the obvious answer and is
        the wrong one: a filesystem hands the just-freed inode straight back to the next file, so
        a sentinel unlinked and immediately replaced can carry the same one, and the check passes
        for the file it was written to refuse.

        `hostname` is recorded and is **not** part of the staleness decision; see the module
        docstring. `created_at` is for whoever is looking at a lock that has not moved in an hour.
        """
        document = {
            "schema_version": SCHEMA_VERSION,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": self._now().isoformat(),
            "token": token,
        }
        return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode(_ENCODING)

    def _holder(self) -> int | None:
        """The pid the sentinel names, or `None` when it names none that can be believed.

        Quiet on every failure, which is `_read_record`'s posture in `backup.py` and the opposite
        of `read_manifest`'s, for the same reason: a damaged manifest read as empty destroys a
        user's files, while a sentinel that cannot name a live holder is a sentinel with nothing
        to say. Refusing on it would wedge the target on exactly the crash the pid check exists
        to recover from.
        """
        try:
            document: Any = json.loads(self._path.read_text(encoding=_ENCODING))
        except (OSError, ValueError):
            return None
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            return None
        pid = document.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int):
            return None
        return pid

    # -- Release ---------------------------------------------------------------------------------

    def _release(self, token: str) -> None:
        """Remove the sentinel — but only the one this lock created.

        A sentinel carrying a different token is somebody else's: this run's was broken as stale
        while it was still working, which the pid check makes unlikely and does not make
        impossible. Removing it would take the lock away from whoever holds it now.

        One left behind because it could not be read back is left behind on purpose, and costs
        nothing: an unreadable sentinel is a stale sentinel to the next acquire, which breaks it.

        The read and the unlink are two syscalls and not one, so a successor arriving between
        them is removed anyway. That window is microseconds wide in a tool charter §12 describes
        as advisory and single-writer, and closing it would need a lock over the lock.
        """
        try:
            document: Any = json.loads(self._path.read_text(encoding=_ENCODING))
        except (OSError, ValueError):
            return
        if not isinstance(document, dict) or document.get("token") != token:
            return
        self._path.unlink(missing_ok=True)


def _is_running(pid: int) -> bool:
    """Whether a process with this pid exists. Signal 0 checks and delivers nothing.

    A pid of `0` or below is answered `False` without a syscall, and that guard is not decoration:
    `os.kill(0, 0)` addresses the whole process group and `os.kill(-1, 0)` every process this user
    owns, so a sentinel holding a nonsense pid must never reach the call.

    `PermissionError` means the process exists and belongs to another user — alive, and not ours
    to break.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


__all__ = ["LOCK_SUFFIX", "SCHEMA_VERSION", "SENTINEL_MODE", "FilesystemWriteLock", "lock_path_for"]
