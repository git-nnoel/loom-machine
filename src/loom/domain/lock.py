"""Charter §12, ruling R50 — the seam that keeps two writers out of one target.

**Reads take no lock and writes take exactly one.** Several `loom mcp` processes reading a library
are safe: each holds its own snapshot and none of them changes anything. An apply is the one
operation in this project that destroys data, and two applies interleaving against one target can
write half of each plan's files and leave a manifest describing neither — a state no verdict in
C-9 can express and no command in this initiative can repair. The realistic case is not exotic:
`loom install` in two terminals, or a shell loop that fires twice.

**It is advisory, per target, and non-blocking.** Advisory because nothing stops a user's editor
or a `cp -a` from writing into the same directory — this keeps *this tool* out of its own way, and
charter §7's torn-read limitation still stands. Per target, like the manifest (R43), so installing
into two directories at once is fine and is asserted. Non-blocking because C-14 fixes the answer
to a held lock as an exit status, `LOCK_HELD = 10`, and not as a queue: a CLI that silently waited
for a lock a crashed process left behind is the behaviour that makes people delete lock files by
hand and lose the protection entirely.

**A context manager, not `acquire` and `release`.** The release has to happen on *every* exit —
apply can abort at the backup, at the manifest or part-way through the files, and a lock leaked on
the error path is worse than no lock at all, because it only bites after something has already
gone wrong. A pair of methods is a pair a caller can half-use; one `with` is not.

**The protocol says nothing about how exclusion is achieved.** `infrastructure/lock.py` does it
with an `O_EXCL` sentinel beside the manifest, stale-broken by a pid check, because that is what
R50 fixes; this layer performs no I/O and `tests/domain/test_purity.py` bars `os` from it.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class WriteLock(Protocol):
    """Exclusive permission to write to one target, for as long as the block runs.

    One member, and no second: this is a seam a fake replaces so apply is testable without a
    disk, and every member a fake implements is a member two tasks can get wrong in two places.
    The lock knows which target it is for; `hold` is given nothing.

    Satisfied **structurally** — an implementation does not inherit it — which is the shape ruling
    R14 settled for C-4 and C-12, C-13 and C-15 keep.
    """

    def hold(self) -> AbstractContextManager[None]:
        """Take the lock for the duration of the block, and release it however the block ends.

        Returns:
            A context manager. Entering it takes the lock; leaving it releases the lock, whether
            the block returned or raised. Nothing is yielded — a caller that holds the lock needs
            no handle to it, and a handle is something a caller could pass on past the release.

        Raises:
            LockHeldError: another writer holds this target's lock. **Nothing has been written**,
                and the remedy is the one no other error code shares: wait and run again.

                Deliberately one of this project's own errors rather than a builtin, which is the
                opposite of the posture `ManifestStore.write` and `BackupStore.create` keep. Those
                two let an `OSError` out because the *application* is what interprets a failed
                syscall (ruling R24). A held lock is not a failed syscall: telling "held by a live
                process" from "stale, break it" from "the state directory is unwritable" needs the
                sentinel's content and the holder's liveness, which only the implementation can
                see. There is no translation here for a fake to pre-supply — this is
                `read_manifest`'s posture, a judgement about content, and it is raised where the
                judgement is made.
        """
        ...


__all__ = ["WriteLock"]
