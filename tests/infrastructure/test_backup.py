"""The filesystem backup store — contract C-13 against real files. T-16.

Charter §10: this layer is tested against **real files under `tmp_path`**, never a fake
filesystem, and that matters here more than anywhere except the target repository itself. Every
test builds its own target and its own state root under `tmp_path`; **nothing reaches
`~/.claude/`** and nothing reaches a developer's `~/.local/state/`.

What this layer is blind to is stated once: it cannot see which paths an install *ought* to back
up. That is `application/write/install.py`'s, and a store test could not observe it because no
plan is ever built here.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness_library.domain.backup import BackupStore
from harness_library.infrastructure.backup import (
    BACKUPS_DIRECTORY_NAME,
    FILES_DIRECTORY_NAME,
    RECORD_FILENAME,
    FilesystemBackupStore,
    default_backups_root,
)
from harness_library.infrastructure.manifest_store import MANIFESTS_DIRECTORY_NAME

CREATED_AT = datetime(2026, 9, 21, 14, 29, tzinfo=UTC)
LATER = datetime(2026, 9, 21, 15, 45, tzinfo=UTC)

ENTRY = "skills/delivery-lead/SKILL.md"
REFERENCE = "skills/delivery-lead/references/notes.md"
FOREIGN = "settings.json"

INSTALLED = b"# what this tool installed\n"
FOREIGN_BYTES = b'{"theme": "dark"}\n'


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Where backups live for the duration of one test. Never the real state directory."""
    return tmp_path / "state"


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """A real install target holding two of this tool's files and one that is not ours."""
    root = tmp_path / "target"
    for path, content in ((ENTRY, INSTALLED), (REFERENCE, b"notes\n"), (FOREIGN, FOREIGN_BYTES)):
        located = root / path
        located.parent.mkdir(parents=True, exist_ok=True)
        located.write_bytes(content)
    return root


def a_store(state_root: Path, target: Path, *, now: datetime = CREATED_AT) -> FilesystemBackupStore:
    """A store whose clock is held still, so a listing's order is the test's to decide."""
    return FilesystemBackupStore(state_root, target, now=lambda: now)


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under `root` and its bytes. The evidence a byte-identical claim needs."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_store_satisfies_contract_c13() -> None:
    """Implemented structurally, never inherited — the shape ruling R14 settled for C-4."""
    assert issubclass(FilesystemBackupStore, BackupStore)


def test_a_backup_lands_under_the_state_root_and_never_inside_the_target(
    state_root: Path, target: Path
) -> None:
    """**The placement is the point.** Inside the target, a backup is destroyed by the wipe it
    exists to recover from; inside the library it is committed and a `git clean` takes it.

    Asserted on the target's own content as well as on the backup's location: the store must not
    have left so much as a marker file behind in the directory it copied from.
    """
    before = snapshot(target)

    backup_id = a_store(state_root, target).create((ENTRY,))

    assert (default_backups_root(state_root) / backup_id / RECORD_FILENAME).is_file()
    assert default_backups_root(state_root) == state_root / BACKUPS_DIRECTORY_NAME
    assert snapshot(target) == before


def test_backups_sit_beside_the_manifests_and_not_inside_them(state_root: Path) -> None:
    """Two directories under one state root, so `hl` owns one place on the machine and a user
    clearing it clears both. DEC-14 put the manifest there; C-13 puts these beside it."""
    assert default_backups_root(state_root).parent == state_root
    assert BACKUPS_DIRECTORY_NAME != MANIFESTS_DIRECTORY_NAME


def test_a_saved_path_comes_back_byte_identical(state_root: Path, target: Path) -> None:
    """The whole purpose, asserted on bytes. The file is destroyed between the two, so this
    cannot pass by never having changed."""
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY,))
    (target / ENTRY).write_bytes(b"# destroyed\n")

    store.restore(backup_id)

    assert (target / ENTRY).read_bytes() == INSTALLED


def test_restoring_removes_a_path_the_target_did_not_hold(state_root: Path, target: Path) -> None:
    """**What makes a first install undoable.** A `CREATE` path is absent when the backup is
    taken, so putting the target back means taking it away again. The store infers that from
    there being no bytes under `files/` — not from a second list in the record."""
    created = "skills/new-skill/SKILL.md"
    store = a_store(state_root, target)
    backup_id = store.create((created,))
    (target / created).parent.mkdir(parents=True)
    (target / created).write_bytes(b"# installed just now\n")

    store.restore(backup_id)

    assert not (target / created).exists()


def test_restoring_touches_nothing_the_backup_does_not_describe(
    state_root: Path, target: Path
) -> None:
    """A backup is not a snapshot of the whole target. The foreign file beside the backed-up one
    must survive a restore untouched, and so must a file created after the backup was taken."""
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY,))
    (target / "afterwards.md").write_bytes(b"written later\n")

    store.restore(backup_id)

    assert (target / FOREIGN).read_bytes() == FOREIGN_BYTES
    assert (target / "afterwards.md").read_bytes() == b"written later\n"


def test_the_record_names_the_target_the_instant_and_every_path(
    state_root: Path, target: Path
) -> None:
    """One state root holds every target's backups (R43), so a listing that could not say which
    target a backup came from would offer to restore one over another."""
    store = a_store(state_root, target)
    store.create((ENTRY, REFERENCE))

    record = store.list()[0]

    assert record.created_at == CREATED_AT
    assert record.target_path == str(target.resolve())
    assert record.paths == (ENTRY, REFERENCE)


def test_a_listing_is_oldest_first_and_covers_every_complete_backup(
    state_root: Path, target: Path
) -> None:
    """Ordered rather than arbitrary: the question a caller asks is "what is the most recent
    one", and directory order answers it differently on two machines."""
    a_store(state_root, target, now=LATER).create((REFERENCE,))
    a_store(state_root, target, now=CREATED_AT).create((ENTRY,))

    records = a_store(state_root, target).list()

    assert [record.created_at for record in records] == [CREATED_AT, LATER]


def test_two_backups_in_one_second_do_not_overwrite_each_other(
    state_root: Path, target: Path
) -> None:
    """The id is a timestamp, and a second backup silently reusing the first's directory would
    destroy the copy the first one was protecting."""
    store = a_store(state_root, target)

    first = store.create((ENTRY,))
    second = store.create((REFERENCE,))

    assert first != second
    assert len(store.list()) == 2


def test_a_backup_with_no_record_is_not_offered_and_cannot_be_restored(
    state_root: Path, target: Path
) -> None:
    """`backup.json` is written **last**, so a directory without one is what a crashed `create`
    leaves. Restoring half a target is worse than not offering it.

    The positive control is in the same test: with the record in place the same directory is
    listed and restorable, so this is not passing by listing nothing.
    """
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY,))
    record = default_backups_root(state_root) / backup_id / RECORD_FILENAME
    kept = record.read_text(encoding="utf-8")
    assert store.list() != ()

    record.unlink()

    assert store.list() == ()
    with pytest.raises(KeyError, match=backup_id):
        store.restore(backup_id)

    record.write_text(kept, encoding="utf-8")
    assert [found.backup_id for found in store.list()] == [backup_id]


def test_a_record_this_build_does_not_read_is_passed_over(state_root: Path, target: Path) -> None:
    """A schema version from a later `hl`, so the same quiet path covers "written by something
    else" as covers "half written". A backup is regenerated by the next install."""
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY,))
    record = default_backups_root(state_root) / backup_id / RECORD_FILENAME
    document = json.loads(record.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    record.write_text(json.dumps(document), encoding="utf-8")

    assert store.list() == ()


def test_a_state_root_with_no_backups_lists_nothing_rather_than_failing(
    state_root: Path, target: Path
) -> None:
    """A first run has taken none, and that is a value and not a fault — the same distinction
    `read_manifest` draws between absent and damaged."""
    assert a_store(state_root, target).list() == ()


def test_the_bytes_are_kept_outside_the_record_and_mirror_the_targets_layout(
    state_root: Path, target: Path
) -> None:
    """The layout is asserted because `restore` reads it: the presence of `files/<path>` is what
    distinguishes "saved" from "was absent", and nothing else records that fact."""
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY, "skills/absent/SKILL.md"))
    saved = default_backups_root(state_root) / backup_id / FILES_DIRECTORY_NAME

    assert (saved / ENTRY).read_bytes() == INSTALLED
    assert not (saved / "skills/absent/SKILL.md").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a mode-500 directory regardless")
def test_an_unwritable_state_root_makes_create_raise_oserror(target: Path, tmp_path: Path) -> None:
    """**What apply turns into `BACKUP_FAILED`.** A builtin and not the project's own error:
    ruling R24 keeps the translation in `application/`, and a store that raised the code itself
    would make that translation untestable by pre-supplying its result.

    Simulated by a read-only state root, which is F-9's own wording.
    """
    state_root = tmp_path / "read-only-state"
    state_root.mkdir()
    state_root.chmod(0o500)
    try:
        with pytest.raises(OSError):
            a_store(state_root, target).create((ENTRY,))
    finally:
        state_root.chmod(0o700)


def test_restoring_an_unknown_id_raises_key_error(state_root: Path, target: Path) -> None:
    with pytest.raises(KeyError, match="nonsense"):
        a_store(state_root, target).restore("nonsense")


def test_a_target_that_is_not_a_directory_is_refused(state_root: Path, tmp_path: Path) -> None:
    """Ruling R71: a missing target is not created here. That decision belongs to the
    composition root, which is where a user can be told about it."""
    with pytest.raises(FileNotFoundError):
        FilesystemBackupStore(state_root, tmp_path / "nowhere")
