"""F-11 end to end — apply, then put it back, against real files.

**The second cross-layer module in this suite, and it has to be**, for the shape of reason
`tests/test_single_writer.py` gives about the lock. What F-11 claims is a fact about a real
directory — *the target is back to its exact prior hash set, per file* — and the code that makes
it true is split in two: `infrastructure/backup.py` holds the bytes and decides that a path it
kept none for is **removed** again (ruling R79), and `application/write/rollback.py` decides to
run that and writes the record afterwards. Neither layer alone can witness the claim. At the
application layer the store is a fake that was written from the contract, and a fake agreeing
with the contract proves only that somebody read it; at the infrastructure layer there is no
manifest and no use case to leave one behind.

So: a real `FilesystemBackupStore`, a real `FilesystemTargetRepository`, a real manifest store, a
real `FilesystemWriteLock`, a real `apply_install` and a real `rollback_install`. The library is
the application fake, because the library side is not what is being proven here and a real one
would drag a fixture tree in with no bearing on the restore.

Nothing here writes outside `tmp_path`. Every state root and every target is a temporary
directory, and `default_state_root()` is not called.
"""

from __future__ import annotations

import shutil
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness_library.application.write import (
    ApplyResult,
    RollbackResult,
    apply_install,
    plan_install,
    rollback_install,
)
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.manifest import Manifest
from harness_library.infrastructure.backup import FilesystemBackupStore
from harness_library.infrastructure.lock import FilesystemWriteLock
from harness_library.infrastructure.manifest_store import (
    FilesystemManifestStore,
    read_manifest,
)
from harness_library.infrastructure.target import (
    DIRECTORY_MODE,
    FILE_MODE,
    FilesystemTargetRepository,
)
from tests.application.fakes import FakeArtifactRepository, make_artifact, make_file

SKILL_NAME = "delivery-lead"
SKILL_ID = "skill/delivery-lead"
OTHER_NAME = "phase-reviewer"
ENTRY = "SKILL.md"

INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"
INSTALLED_OTHER = "skills/phase-reviewer/SKILL.md"
ARTIFACT_ROOT = "skills/delivery-lead"

FOREIGN = "settings.json"
FOREIGN_BYTES = b'{"theme": "dark"}\n'

FIRST_BYTES = b"# the first version this tool installed\n"
SECOND_BYTES = b"# and the version that replaced it\n"

APPLIED_AT = datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
"""When every run in this module happened. A parameter, never a clock."""


# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


def a_library(*names: str, body: bytes = FIRST_BYTES) -> FakeArtifactRepository:
    """One single-file skill per name, all holding `body`."""
    artifacts = [make_artifact(name, files=(make_file(ENTRY, body),)) for name in names]
    return FakeArtifactRepository(
        artifacts, contents={(artifact.id, ENTRY): body for artifact in artifacts}
    )


def hash_set(root: Path) -> dict[str, str]:
    """Every file under `root` and its digest. Content, never mtime (L37).

    `domain.hashing.hash_bytes` and not a second `hashlib` call, for the reason charter §7 gives:
    two hashing routines over one rule agree until they do not.
    """
    return {
        str(path.relative_to(root)): hash_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def install(
    library: FakeArtifactRepository,
    target_root: Path,
    state_root: Path,
    *,
    manifest: Manifest | None,
) -> ApplyResult:
    """One real apply into `target_root`, planned from the target as it is now."""
    target = FilesystemTargetRepository(target_root)
    return apply_install(
        plan_install(library, target, manifest=manifest),
        library,
        target,
        FilesystemBackupStore(state_root, target_root, now=lambda: APPLIED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: APPLIED_AT),
        manifest=manifest,
        target_path=str(target_root),
        installed_at=APPLIED_AT,
    )


def roll_back(
    target_root: Path,
    state_root: Path,
    *,
    manifest: Manifest,
    backup_id: str,
) -> RollbackResult:
    """One real rollback of `target_root`, from a backup this state root holds."""
    return rollback_install(
        FilesystemTargetRepository(target_root),
        FilesystemBackupStore(state_root, target_root, now=lambda: APPLIED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: APPLIED_AT),
        manifest=manifest,
        backup_id=backup_id,
        installed_at=APPLIED_AT,
    )


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Where the manifests, the backups and the sentinel go. Never `default_state_root()`."""
    return tmp_path / "state"


@pytest.fixture
def target_root(tmp_path: Path) -> Iterator[Path]:
    """An install target that exists and holds nothing. A first install's starting point."""
    root = tmp_path / "target"
    root.mkdir()
    yield root


# -------------------------------------------------------------------------------------------
# F-11 — the exact prior hash set, per file
# -------------------------------------------------------------------------------------------


def test_rolling_back_a_first_install_empties_the_target_again(
    target_root: Path, state_root: Path
) -> None:
    """**F-11's hardest case, and the must-fail assertion of this task's mutation (a)** (restore
    only the paths the target currently holds, skipping the ones the backup kept no bytes for).

    The target held nothing, so the backup holds nothing — it *describes* both paths and keeps no
    bytes for either, which is ruling R79 and is exactly what makes a first install undoable. A
    rollback that only overwrote would leave both created files behind and report the target
    restored.

    Asserted **per path** and then on the whole hash set, so "every file went" and "the right
    files went" are two claims rather than one. The positive control is the middle assertion: the
    install really did put both files there, so an empty target afterwards cannot mean this
    harness never writes.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)

    applied = install(library, target_root, state_root, manifest=None)

    assert applied.backup_id is not None
    assert hash_set(target_root) == {
        INSTALLED_ENTRY: hash_bytes(FIRST_BYTES),
        INSTALLED_OTHER: hash_bytes(FIRST_BYTES),
    }

    roll_back(
        target_root,
        state_root,
        manifest=applied.manifest,
        backup_id=applied.backup_id,
    )

    assert not (target_root / INSTALLED_ENTRY).exists(), (
        f"{INSTALLED_ENTRY} was created by the install this rollback undid, so putting the "
        "target back means taking it away again (R79): a backup describes a path it kept no "
        "bytes for precisely so that restoring it removes the path"
    )
    assert not (target_root / INSTALLED_OTHER).exists(), (
        f"{INSTALLED_OTHER} was created by the install this rollback undid and is still there"
    )
    assert hash_set(target_root) == {}


def test_rolling_back_an_overwrite_restores_the_previous_bytes(
    target_root: Path, state_root: Path
) -> None:
    """**The must-stay-green control of mutation (a).**

    Every path this backup describes is one the target already held, so the store kept bytes for
    all of them and the branch the mutation removes is never reached. Without this pair, "restore
    puts nothing back" and "restore puts back only what it overwrote" produce the same single
    failure and are indistinguishable.

    Asserted per file, on the bytes: the first version comes back, and the manifest that
    described the second one is gone from the target entirely.
    """
    first = a_library(SKILL_NAME)
    install(first, target_root, state_root, manifest=None)
    installed = read_manifest(target_root, state_root=state_root)
    assert installed is not None

    second = a_library(SKILL_NAME, body=SECOND_BYTES)
    applied = install(second, target_root, state_root, manifest=installed)

    assert applied.backup_id is not None
    assert (target_root / INSTALLED_ENTRY).read_bytes() == SECOND_BYTES

    roll_back(
        target_root,
        state_root,
        manifest=applied.manifest,
        backup_id=applied.backup_id,
    )

    assert (target_root / INSTALLED_ENTRY).read_bytes() == FIRST_BYTES
    assert hash_set(target_root) == {INSTALLED_ENTRY: hash_bytes(FIRST_BYTES)}


def test_a_foreign_file_is_byte_identical_after_a_rollback(
    target_root: Path, state_root: Path
) -> None:
    """F-10's promise survives the undo. A backup describes only the paths the run it protected
    would have written or deleted, so a file nobody recorded is outside it in both directions —
    it is not copied and it is not put back, which is how it stays exactly as it was.

    Asserted on the file's bytes and not on the report, and with the installed file's removal in
    the same test as the control: the rollback did do something.
    """
    (target_root / FOREIGN).write_bytes(FOREIGN_BYTES)
    library = a_library(SKILL_NAME)

    applied = install(library, target_root, state_root, manifest=None)
    assert applied.backup_id is not None

    roll_back(target_root, state_root, manifest=applied.manifest, backup_id=applied.backup_id)

    assert (target_root / FOREIGN).read_bytes() == FOREIGN_BYTES
    assert not (target_root / INSTALLED_ENTRY).exists()


# -------------------------------------------------------------------------------------------
# The record the rollback leaves on disk
# -------------------------------------------------------------------------------------------


def test_the_manifest_on_disk_describes_the_restored_state(
    target_root: Path, state_root: Path
) -> None:
    """**The record must describe what is there now, not what was rolled back**, and this is the
    assertion made against a manifest really read back off a real state directory.

    The digest is the *first* install's, which is what the restored file holds. Left claiming the
    second install's digest, the next `hl diff` would call the restored file a `LOCAL_EDIT` and
    ask the user to decide about a file this tool put back itself.
    """
    first = a_library(SKILL_NAME)
    install(first, target_root, state_root, manifest=None)
    installed = read_manifest(target_root, state_root=state_root)
    assert installed is not None

    second = a_library(SKILL_NAME, body=SECOND_BYTES)
    applied = install(second, target_root, state_root, manifest=installed)
    assert applied.backup_id is not None
    assert applied.manifest.artifacts[0].files[0].sha256 == hash_bytes(SECOND_BYTES)

    roll_back(target_root, state_root, manifest=applied.manifest, backup_id=applied.backup_id)

    recorded = read_manifest(target_root, state_root=state_root)
    assert recorded is not None
    assert recorded.artifacts[0].artifact_id == SKILL_ID
    assert recorded.artifacts[0].files[0].sha256 == hash_bytes(FIRST_BYTES)
    assert recorded.backup_id is None
    assert recorded.library_git_sha is None


def test_the_manifest_records_nothing_after_a_first_install_is_rolled_back(
    target_root: Path, state_root: Path
) -> None:
    """**Absent is not empty** (`infrastructure/manifest_store.py`), and this is the case that
    makes the distinction earn its keep: the target was installed into and then put back, which
    is not the same fact as never having been touched.

    A record still naming the removed files would report each of them `CREATE` — harmless — but
    an artifact whose every file has gone must not linger as a record claiming nothing.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    applied = install(library, target_root, state_root, manifest=None)
    assert applied.backup_id is not None

    roll_back(target_root, state_root, manifest=applied.manifest, backup_id=applied.backup_id)

    recorded = read_manifest(target_root, state_root=state_root)
    assert recorded is not None
    assert recorded.artifacts == ()


# -------------------------------------------------------------------------------------------
# Ruling R56 — what a restored file and a recreated directory are chmodded to
# -------------------------------------------------------------------------------------------


def test_a_restored_file_and_the_directory_it_needs_carry_the_installed_modes(
    target_root: Path, state_root: Path
) -> None:
    """R56, on the undo path. A restore writes through `FilesystemTargetRepository`, which is the
    single place that decides a mode — so a file put back by a rollback is `0644` and a directory
    recreated for it is `0755`, exactly as an install's are, and a strict umask cannot ship the
    user a harness their own editor cannot read.

    The artifact's whole directory is removed between the apply and the rollback, which is a real
    thing a user does and is what makes the restore recreate the parent rather than write into an
    existing one. The control is `stat.S_IMODE`, never the raw mode word.
    """
    first = a_library(SKILL_NAME)
    install(first, target_root, state_root, manifest=None)
    installed = read_manifest(target_root, state_root=state_root)
    assert installed is not None

    second = a_library(SKILL_NAME, body=SECOND_BYTES)
    applied = install(second, target_root, state_root, manifest=installed)
    assert applied.backup_id is not None

    shutil.rmtree(target_root / ARTIFACT_ROOT)
    assert not (target_root / ARTIFACT_ROOT).exists()

    roll_back(target_root, state_root, manifest=applied.manifest, backup_id=applied.backup_id)

    assert (target_root / INSTALLED_ENTRY).read_bytes() == FIRST_BYTES
    assert stat.S_IMODE((target_root / INSTALLED_ENTRY).stat().st_mode) == FILE_MODE
    assert stat.S_IMODE((target_root / ARTIFACT_ROOT).stat().st_mode) == DIRECTORY_MODE
