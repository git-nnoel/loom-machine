"""`WriteLock` — the seam charter §12 and ruling R50 put between two writers.

Nothing here can prove that anything is actually excluded: a protocol is a shape, and the
exclusion is a sentinel file. What this module proves is the shape the rest of the project relies
on — that an implementation satisfies it without inheriting it, and that the check can fail.

Where the lock really keeps two applies apart is `tests/test_single_writer.py`, against a real
sentinel and a real apply, which is the only place both halves are visible at once.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from loom.domain.lock import WriteLock


def test_the_lock_protocol_is_satisfied_structurally() -> None:
    """`WriteLock` is implemented, never inherited — the shape ruling R14 settled for C-4."""

    class Lock:
        @contextmanager
        def hold(self) -> Iterator[None]:
            yield

    assert isinstance(Lock(), WriteLock)


def test_an_object_that_cannot_be_held_is_not_a_write_lock() -> None:
    """The positive control for the check above."""

    class NotALock:
        def acquire(self) -> None:
            return None

    assert not isinstance(NotALock(), WriteLock)
