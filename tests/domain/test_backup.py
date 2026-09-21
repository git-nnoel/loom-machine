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


# -- Ruling R92, amending C-13: the kept set ------------------------------------------------------
#
# Added, never altered: every test above keeps the field list and the invariants it already
# asserted, and `kept` defaults to `()` so a record built without it is still a record.


def test_a_record_says_which_of_its_paths_it_holds_bytes_for() -> None:
    """The amendment itself. Before it, "this path was absent when the backup was taken" was
    inferred from the `files/` tree, so a byte-file removed afterwards read as an absence and the
    restore **deleted** a live target path. Now the record says which is which."""
    record = a_record(
        paths=("skills/delivery-lead/SKILL.md", "skills/new/SKILL.md"),
        kept=("skills/delivery-lead/SKILL.md",),
    )

    assert record.kept == ("skills/delivery-lead/SKILL.md",)
    assert set(record.paths) - set(record.kept) == {"skills/new/SKILL.md"}


def test_a_record_keeping_bytes_for_nothing_it_describes_is_refused() -> None:
    """`kept` is a subset of `paths` and not a second list.

    `restore` walks `paths`, so bytes recorded outside it would be held forever and put back
    never — a backup silently smaller than it claims. The invariant runs one way only: a path in
    `paths` and not in `kept` is the ordinary case R79 exists for.
    """
    with pytest.raises(ValueError, match="does not describe"):
        a_record(paths=("skills/a/SKILL.md",), kept=("skills/b/SKILL.md",))


def test_a_record_keeping_nothing_is_a_value_and_not_an_error() -> None:
    """A first install into an empty target holds bytes for none of the paths it describes, and
    restoring it removes every one of them. That is the case R79 exists for, not a fault."""
    assert a_record(paths=("skills/new/SKILL.md",)).kept == ()


# ==============================================================================================
# C-13's second amendment — `links`, ruling R94
# ==============================================================================================
#
# Added, never altered: every test above keeps the fields and invariants it already asserted, and
# `links` defaults to empty so a record built without it is still a record.

LINK = "skills/delivery-lead/references/elsewhere.md"
DESTINATION = "../../../../outside/target-escape.md"


def test_a_record_says_where_each_of_its_symlinks_pointed() -> None:
    """The amendment itself. A link has no bytes to copy — R6 never reads through one — so
    before this field it was described like an absent path, and restoring the backup **removed**
    it and never put it back. A link's content is its destination, and this is where it lives."""
    record = a_record(paths=("skills/delivery-lead/SKILL.md", LINK), links={LINK: DESTINATION})

    assert record.links[LINK] == DESTINATION
    assert LINK not in record.kept


def test_a_record_recording_a_link_it_does_not_describe_is_refused() -> None:
    """`links` is keyed within `paths`, for the reason `kept` is a subset of it: `restore` walks
    `paths`, so a link recorded outside would be held forever and recreated never."""
    with pytest.raises(ValueError, match="does not describe"):
        a_record(paths=("skills/a/SKILL.md",), links={LINK: DESTINATION})


def test_a_path_cannot_be_both_bytes_and_a_link() -> None:
    """A path was one or the other when the backup was taken. A record holding both would make
    `restore` guess which the target really held — and guessing wrong means writing a regular
    file where the user had a link, or a link where they had a file."""
    with pytest.raises(ValueError, match="both bytes and a link"):
        a_record(paths=(LINK,), kept=(LINK,), links={LINK: DESTINATION})


def test_a_link_with_no_destination_is_refused() -> None:
    """The destination is the link's whole content. An empty one cannot be recreated, and a
    record carrying it would fail at restore time — over a target that has already changed."""
    with pytest.raises(ValueError, match="empty link destination"):
        a_record(paths=(LINK,), links={LINK: ""})


def test_a_record_with_no_links_is_a_value_and_not_an_error() -> None:
    """The positive control for the three refusals above: an ordinary backup of an ordinary
    target records no link at all, and that is the common case rather than a fault."""
    assert a_record().links == {}
