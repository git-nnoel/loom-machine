"""`list_backups` — which rollback points a target has. Ruling R113.

**The undo had no listing, so its argument was unreachable.** `loom rollback [BACKUP_ID]` takes an
id precisely so that a user can undo three installs instead of the last one (R54), and until this
use case there was no way to *discover* an id except by listing the state directory by hand:
`BackupStore.list()` has been on contract C-13 since T-16 and nothing reached it. A feature whose
argument cannot be spelled is a feature nobody has.

**Read, and therefore no lock** (R85, charter §12). Nothing here writes, so a listing taken while
an install is midway through describes a target that is being written — which is the same
statement `loom diff` already makes, and the same reason locking a read would serialise the one
operation that is always safe.

**Retention is not here.** Backups accumulate and each `clean --foreign --remove` of a real
harness costs 144 MB of state; deciding what to delete and when is a separate question with a
different risk, and this use case deliberately only says what is there.
"""

from __future__ import annotations

from loom.domain.backup import BackupRecord, BackupStore


def list_backups(backups: BackupStore, *, target_path: str) -> tuple[BackupRecord, ...]:
    """Every backup of one target, oldest first.

    **The filter is the point.** One state root holds the backups of every target a user has
    installed into (R43) and `BackupStore.list()` returns all of them, by design — a listing that
    hid the others would make "where did my backup go" unanswerable. A *caller* asking about one
    target must filter, and `BackupRecord.target_path` is the field that exists so that it can.
    Doing it here rather than in each adapter means "this target's backups" has one definition,
    reached by both the listing a user reads and the choice `loom rollback` makes without an id.

    Args:
        backups: contract C-13. Only `list()` is called; nothing is created and nothing restored.
        target_path: the canonical spelling of the target, as `Manifest.target_path` records it
            and as the store writes it into each record. Compared exactly — canonicalisation
            happens once, in the composition root (R43), and a second spelling of one directory
            here would answer about a different set of backups from the one a rollback uses.

    Returns:
        The records, oldest first, so `[-1]` is the most recent. Empty when this target has none:
        a target nothing was ever backed up from is a fact and not a failure, and the caller says
        what that means — for `loom rollback` it is R112's "there is nothing to put back".
    """
    return tuple(record for record in backups.list() if record.target_path == target_path)


__all__ = ["list_backups"]
