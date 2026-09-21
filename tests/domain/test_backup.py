"""Contract C-13's entity and protocol. T-16.

Pure domain, zero I/O. What this module cannot see is whether a backup lands outside the target,
survives a `git clean`, or puts real bytes back; that is proven against real files in
`tests/infrastructure/test_backup.py`. What it *can* see is the shape C-13 froze and the invariants
that keep a listing usable — an id that restores nothing, an instant that cannot be ordered, and a
target nobody can name.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from harness_library.domain.backup import BackupRecord, BackupStore

CREATED_AT = datetime(2026, 9, 21, 14, 29, tzinfo=UTC)
TARGET = "/home/example/.claude"


def a_record(**overrides: object) -> BackupRecord:
    """A valid record, with one field replaced."""
    fields: dict[str, object] = {
        "backup_id": "2026-09-21T14-29-00Z",
        "created_at": CREATED_AT,
        "target_path": TARGET,
        "paths": ("skills/delivery-lead/SKILL.md",),
    }
    fields.update(overrides)
    return BackupRecord(**fields)  # type: ignore[arg-type]


def test_a_record_carries_the_four_fields_c13_froze() -> None:
    record = a_record()

    assert record.backup_id == "2026-09-21T14-29-00Z"
    assert record.created_at == CREATED_AT
    assert record.target_path == TARGET
    assert record.paths == ("skills/delivery-lead/SKILL.md",)


def test_an_empty_backup_id_is_refused() -> None:
    """The id is what `restore` is given. One that is empty names no backup and restores none."""
    with pytest.raises(ValueError, match="backup_id"):
        a_record(backup_id="")


def test_a_naive_created_at_is_refused() -> None:
    """The same rule `Manifest.installed_at` keeps: this value is written to disk, read back on
    another day, and **sorted** — a listing is ordered by it. A naive instant compared with an
    aware one raises far from whichever of the two was wrong."""
    with pytest.raises(ValueError, match="timezone-aware"):
        a_record(created_at=datetime(2026, 9, 21, 14, 29))


def test_an_empty_target_path_is_refused() -> None:
    """One state root holds the backups of every target a user has (R43). A record that cannot
    say which target it came from would be offered for restore over the wrong one."""
    with pytest.raises(ValueError, match="target_path"):
        a_record(target_path="")


def test_a_backup_describing_no_paths_is_a_value_and_not_an_error() -> None:
    """Not every run has something to protect. The caller's answer to that is `backup_id=None`
    rather than an empty backup, but the record itself must not forbid one — the store is free to
    write a record for a run that turned out to touch nothing."""
    assert a_record(paths=()).paths == ()


def test_the_protocol_is_satisfied_structurally() -> None:
    """C-13 is implemented, never inherited (ruling R14's shape). The check is the one apply
    relies on: an object with the three members *is* a `BackupStore`."""

    class Store:
        def create(self, paths: tuple[str, ...]) -> str:
            return "id"

        def restore(self, backup_id: str) -> None:
            return None

        def list(self) -> tuple[BackupRecord, ...]:
            return ()

    assert isinstance(Store(), BackupStore)


def test_an_object_missing_a_member_is_not_a_backup_store() -> None:
    """The positive control for the check above: without it, `isinstance` passing proves nothing
    about which members the protocol actually names."""

    class NotAStore:
        def create(self, paths: tuple[str, ...]) -> str:
            return "id"

    assert not isinstance(NotAStore(), BackupStore)
