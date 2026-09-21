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


# -- Ruling R92, amending C-13: the kept set, against a real tree --------------------------------
#
# Added, never altered. The three tests above that read the `files/` layout keep exactly what they
# assert; what changes is that the record now *says* which paths those bytes belong to, and that
# `restore` checks the two against each other before it moves anything.


def test_the_record_names_the_paths_it_kept_bytes_for(state_root: Path, target: Path) -> None:
    """Both halves in one record: the path the target held is in `kept`, the one it did not is
    described and not kept. That second path is what makes a first install undoable (R79)."""
    store = a_store(state_root, target)
    absent = "skills/absent/SKILL.md"

    backup_id = store.create((ENTRY, absent))

    record = next(one for one in store.list() if one.backup_id == backup_id)
    assert record.paths == (ENTRY, absent)
    assert record.kept == (ENTRY,)


def test_a_backup_whose_kept_bytes_were_deleted_is_refused_and_the_target_is_untouched(
    state_root: Path, target: Path
) -> None:
    """**The failure ruling R92 exists to close, and it used to be silent.**

    The backup kept bytes for `ENTRY`; something removed `files/<ENTRY>` afterwards — a stray
    `rm`, a half-cleaned state directory, a filesystem repair. Before the amendment the store
    inferred "absent when the backup was taken" from that missing file and **deleted the path
    from the target**: no error, no report, no code, and the user's file gone.

    Asserted on the target's **bytes**, because a refusal that still deleted is the failure. The
    refusal comes *before* the first path moves, so the rest of the target is untouched too — the
    positive control is the `FOREIGN` file, which a partial restore would also have rewritten.
    """
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY, FOREIGN))
    (default_backups_root(state_root) / backup_id / FILES_DIRECTORY_NAME / ENTRY).unlink()
    (target / FOREIGN).write_bytes(b"edited since\n")

    with pytest.raises(KeyError, match="not complete"):
        store.restore(backup_id)

    assert (target / ENTRY).read_bytes() == INSTALLED
    assert (target / FOREIGN).read_bytes() == b"edited since\n"


def test_a_path_that_was_absent_when_the_backup_was_taken_is_still_removed(
    state_root: Path, target: Path
) -> None:
    """**The positive control of the refusal above**, and R79 unchanged.

    Without it, "refuses a damaged backup" and "never removes anything any more" produce the same
    green run. This path is outside `kept`, so no bytes are missing and nothing is refused — the
    restore removes it, which is what makes a first install undoable.

    `tests/infrastructure/test_backup.py::test_restoring_removes_a_path_the_target_did_not_hold`
    says the same thing one test up; this one says it while a *different* path in the same backup
    does have bytes, which is the arrangement the refusal has to be able to tell apart.
    """
    store = a_store(state_root, target)
    created = "skills/created/SKILL.md"
    backup_id = store.create((ENTRY, created))
    (target / created).parent.mkdir(parents=True, exist_ok=True)
    (target / created).write_bytes(b"installed after the backup\n")

    store.restore(backup_id)

    assert not (target / created).exists()
    assert (target / ENTRY).read_bytes() == INSTALLED


def test_a_backup_written_before_the_kept_set_existed_is_not_offered(
    state_root: Path, target: Path
) -> None:
    """**What reading a pre-amendment backup does**: nothing reads it.

    A schema-1 record has no `kept`, so nothing distinguishes a path whose bytes were lost from
    one that was never there — the exact indistinguishability R92 closes. Inferring `kept` from
    the tree would carry the defect forward on the one class of backup that cannot prove itself,
    so the version check that already exists does the work: `list()` omits it and `restore`
    refuses it. A backup is regenerated by the next install.
    """
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY,))
    record = default_backups_root(state_root) / backup_id / RECORD_FILENAME
    document = json.loads(record.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    del document["kept"]
    record.write_text(json.dumps(document), encoding="utf-8")

    assert store.list() == ()
    with pytest.raises(KeyError, match=backup_id):
        store.restore(backup_id)
    assert (target / ENTRY).read_bytes() == INSTALLED


# ==================================================================================================
# Ruling R94 — a symlink is recorded as its destination and restored as a link
# ==================================================================================================

LINK = "skills/delivery-lead/references/elsewhere.md"
LINK_DESTINATION = "../../../../outside/target-escape.md"


@pytest.fixture
def target_with_a_link(target: Path) -> Path:
    """The same target, plus a symlink resolving **outside** it, pointing at a real file.

    Real because `ruff` exits 2 on a broken symlink anywhere in the tree (L21) — and because a
    dangling link would prove the easy case: the interesting claim is that the destination's
    *content* never enters the backup and never comes back as a regular file.
    """
    outside = target.parent / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "target-escape.md").write_bytes(b"# a file outside the target entirely\n")
    located = target / LINK
    located.parent.mkdir(parents=True, exist_ok=True)
    located.symlink_to(LINK_DESTINATION)
    assert located.is_symlink()
    return target


def test_a_symlink_is_recorded_as_its_destination_and_not_as_bytes(
    state_root: Path, target_with_a_link: Path
) -> None:
    """R6 forbids reading through a link, so nothing lands under `files/` for one. The record
    says where it pointed instead, which is the whole of what a link is.

    The `kept` assertion is the control for the `links` one: the ordinary file in the same
    backup *is* held as bytes, so "the link is not in `kept`" is a statement about the link and
    not about a store that keeps nothing.
    """
    store = a_store(state_root, target_with_a_link)

    backup_id = store.create((ENTRY, LINK))

    (record,) = store.list()
    assert record.links == {LINK: LINK_DESTINATION}
    assert record.kept == (ENTRY,)
    assert not (default_backups_root(state_root) / backup_id / FILES_DIRECTORY_NAME / LINK).exists()


def test_the_destination_of_a_linked_path_never_enters_the_backup(
    state_root: Path, target_with_a_link: Path
) -> None:
    """**The escape R6 exists to prevent, reached through the undo mechanism.** Following the
    link would copy a file from outside the target into a backup *of* the target, and a restore
    would then materialise it as a regular file — a different target from the one backed up.

    Asserted on the bytes, across the whole backup directory, so a copy under any name fails it.
    """
    destination = target_with_a_link.parent / "outside" / "target-escape.md"
    outside_bytes = destination.read_bytes()

    backup_id = a_store(state_root, target_with_a_link).create((ENTRY, LINK))

    directory = default_backups_root(state_root) / backup_id
    assert outside_bytes not in snapshot(directory).values()
    assert destination.read_bytes() == outside_bytes


def test_a_restored_symlink_is_a_symlink_naming_what_it_named_before(
    state_root: Path, target_with_a_link: Path
) -> None:
    """**The criterion of ruling R94, asserted on `is_symlink` and on the destination.**

    A regular file holding a copy of what the link pointed at would satisfy "the path is back"
    and would silently replace the user's development link with a snapshot of somebody else's
    directory. The link is destroyed between the two calls, so this cannot pass by never having
    changed.
    """
    store = a_store(state_root, target_with_a_link)
    backup_id = store.create((ENTRY, LINK))
    (target_with_a_link / LINK).unlink()
    assert not (target_with_a_link / LINK).exists()

    store.restore(backup_id)

    assert (target_with_a_link / LINK).is_symlink()
    assert (target_with_a_link / LINK).readlink() == Path(LINK_DESTINATION)
    assert (target_with_a_link / LINK).read_bytes() == b"# a file outside the target entirely\n"


def test_a_restored_symlink_replaces_whatever_took_its_place(
    state_root: Path, target_with_a_link: Path
) -> None:
    """A restore puts the target back, whatever is there now. Between the backup and the restore
    a clean-and-reinstall can leave an ordinary file at the path, and the link still has to
    come back as a link."""
    store = a_store(state_root, target_with_a_link)
    backup_id = store.create((LINK,))
    (target_with_a_link / LINK).unlink()
    (target_with_a_link / LINK).write_bytes(b"a regular file now\n")

    store.restore(backup_id)

    assert (target_with_a_link / LINK).is_symlink()
    assert (target_with_a_link / LINK).readlink() == Path(LINK_DESTINATION)


def test_a_dangling_symlink_is_recorded_and_restored_like_any_other(
    state_root: Path, target: Path
) -> None:
    """`readlink`, never `resolve` (R6). A link whose destination is gone is still a link, and a
    backup that refused one would refuse exactly the kind of path a user most needs putting
    back — the one that already looks broken."""
    (target / LINK).parent.mkdir(parents=True, exist_ok=True)
    (target / LINK).symlink_to("nowhere-at-all.md")
    store = a_store(state_root, target)
    backup_id = store.create((LINK,))
    (target / LINK).unlink()

    store.restore(backup_id)

    assert (target / LINK).is_symlink()
    assert (target / LINK).readlink() == Path("nowhere-at-all.md")
    assert not (target / LINK).exists()


def test_a_backup_written_before_the_link_set_existed_is_not_offered(
    state_root: Path, target: Path
) -> None:
    """**What reading a version-2 backup does**: nothing reads it, as with version 1.

    This reader has one version. A version-2 record could be read with no links, which is a true
    statement about it, but it would be a second code path through the one document whose job is
    to be trustworthy — in exchange for a rollback point on a tool that has not shipped.
    """
    store = a_store(state_root, target)
    backup_id = store.create((ENTRY,))
    record = default_backups_root(state_root) / backup_id / RECORD_FILENAME
    document = json.loads(record.read_text(encoding="utf-8"))
    document["schema_version"] = 2
    del document["links"]
    record.write_text(json.dumps(document), encoding="utf-8")

    assert store.list() == ()
    with pytest.raises(KeyError, match=backup_id):
        store.restore(backup_id)
    assert (target / ENTRY).read_bytes() == INSTALLED
