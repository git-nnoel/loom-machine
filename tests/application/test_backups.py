"""`list_backups` — which rollback points a target has. Ruling R113, T-24.

**What this layer decides, and it is one thing: which of a state root's backups are this
target's.** `BackupStore.list()` returns every target's (R43), by design — a listing that hid the
others would make "where did my backup go" unanswerable — so a caller asking about one target
has to filter, and doing it in each adapter is how two spellings of "this target's backups" come
to exist. `loom rollback` without an id and `loom backups` are those two callers, and they now reach
one definition.

**What this layer is blind to.** It cannot see that a backup is complete, that an older schema is
passed over, or that a directory with no record is not a backup — the store decides all three and
`tests/infrastructure/test_backup.py` proves them against real files. A fake that answered those
questions would be asserting its own `if`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from loom.application.read import list_backups
from loom.domain.backup import BackupRecord

TARGET = "/home/example/.claude"
OTHER = "/home/example/staging"

EARLIER = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 21, 15, 0, tzinfo=UTC)


class StoreHolding:
    """Contract C-13's `list()` over a fixed set of records. The other two members are unused.

    A class rather than `tests.application.fakes.FakeBackupStore` because the subject is the
    filter and nothing else: this use case never creates and never restores, and a fake that
    could would let a test assert something no caller of `list_backups` can reach.
    """

    def __init__(self, *records: BackupRecord) -> None:
        self._records = records

    def create(self, paths: tuple[str, ...]) -> str:  # pragma: no cover - never called
        raise AssertionError("list_backups creates nothing")

    def restore(self, backup_id: str) -> None:  # pragma: no cover - never called
        raise AssertionError("list_backups restores nothing")

    def list(self) -> tuple[BackupRecord, ...]:
        return self._records


def a_record(
    backup_id: str, *, target_path: str = TARGET, created_at: datetime = EARLIER
) -> BackupRecord:
    return BackupRecord(backup_id=backup_id, created_at=created_at, target_path=target_path)


def test_a_targets_own_backups_come_back_oldest_first() -> None:
    """The order is the store's and is preserved, so `[-1]` is the most recent — which is what
    a bare `loom rollback` puts back and what the listing's closing line names."""
    store = StoreHolding(
        a_record("first", created_at=EARLIER),
        a_record("second", created_at=LATER),
    )

    found = list_backups(store, target_path=TARGET)

    assert [record.backup_id for record in found] == ["first", "second"]


def test_another_targets_backups_are_not_this_targets() -> None:
    """**Ruling R43.** A user who installs into two directories must not be offered an id that
    would put one back over the other — and `loom rollback` without an id must not choose one."""
    store = StoreHolding(a_record("mine"), a_record("theirs", target_path=OTHER))

    assert [record.backup_id for record in list_backups(store, target_path=TARGET)] == ["mine"]
    assert [record.backup_id for record in list_backups(store, target_path=OTHER)] == ["theirs"]


def test_a_target_with_no_backups_is_an_empty_tuple_and_not_a_failure() -> None:
    """A run that wrote nothing took no backup, which is R112's whole subject. The *caller*
    decides what that means: for `loom rollback` it is "there is nothing to put back" and exit 0,
    and for `loom backups` it is an empty listing. Neither is this use case's to raise."""
    assert (
        list_backups(StoreHolding(a_record("theirs", target_path=OTHER)), target_path=TARGET) == ()
    )
    assert list_backups(StoreHolding(), target_path=TARGET) == ()


def test_the_comparison_is_exact_and_never_a_prefix() -> None:
    """The positive control for the filter, and the trap it avoids.

    `/home/example/.claude` and `/home/example/.claude-staging` are two targets, and a filter
    written as "starts with" would offer one's backups for the other. Canonicalisation happens
    once, in the composition root (R43), so what arrives here is a spelling to compare and never
    a path to normalise a second time.
    """
    store = StoreHolding(a_record("mine"), a_record("neighbour", target_path=f"{TARGET}-staging"))

    assert [record.backup_id for record in list_backups(store, target_path=TARGET)] == ["mine"]
