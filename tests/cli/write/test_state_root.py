"""The state directory refusing the lock, through `loom`. Contract C-14, ruling R111. T-24.

**The one disk step of a write run that had no code.** Every other failure of the same kind is
typed and says what happened to the target — the backup gives `BACKUP_FAILED = 9`, the manifest
`MANIFEST_UNWRITABLE = 11`, the target `TARGET_UNWRITABLE = 7` — and
`FilesystemWriteLock._acquire` gave a forty-line traceback and exit 1, outside the table
entirely, on `install`, `uninstall`, `rollback` and `clean --remove` alike. A full disk, a
read-only mount and a `~/.local/state` one `sudo` run left owned by root all reach it.

**Both outcomes are asserted here, as a pair.** `STATE_UNWRITABLE = 15` and `LOCK_HELD = 10` are
the two ways the lock refuses a target; both mean nothing was written and they differ only in
what a user must do about it, so each is the other's control. A change that collapsed them —
translating the `OSError` into `LockHeldError`, or letting it out again — reddens one of the two
whichever direction it went.

Every claim about the target is its **hash set**, never the command's own report (R31): "nothing
was written" is a fact about the directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from loom.cli.exit_codes import LOCK_HELD, STATE_UNWRITABLE
from loom.infrastructure.lock import lock_path_for
from loom.infrastructure.manifest_store import MANIFESTS_DIRECTORY_NAME
from tests.cli.write.conftest import digests, library_with, run

ONLY = "skills/only/SKILL.md"

WRITE_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("install",),
    ("uninstall", "skill/only"),
    ("rollback",),
    ("clean", "--remove"),
)
"""The four commands that take the lock. **All four, because the fix is in the lock and not in
any of them** — a translation that reached only the one command a test happened to pick would
leave the other three answering with a traceback."""


@pytest.fixture
def installed(runner: CliRunner, tmp_path: Path, empty_target: Path) -> Path:
    """A target with one artifact installed, a manifest and a backup. What each command needs.

    The install runs *before* the state root is made read-only: every command below acts on a
    record, and this suite is about the second run rather than the first.
    """
    library = library_with(tmp_path, only="The one skill.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    (empty_target / "settings.json").write_text("{}\n", encoding="utf-8")
    return library


def read_only_manifests(state_root: Path) -> Path:
    """The directory the sentinel goes in, made unwritable. Returns it, so a test can undo it."""
    manifests = state_root / MANIFESTS_DIRECTORY_NAME
    manifests.chmod(0o500)
    return manifests


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a mode-500 directory regardless")
@pytest.mark.parametrize("command", WRITE_COMMANDS, ids=lambda one: one[0])
def test_a_state_root_that_will_not_take_the_lock_is_exit_15_and_writes_nothing(
    runner: CliRunner,
    installed: Path,
    empty_target: Path,
    state_root: Path,
    command: tuple[str, ...],
) -> None:
    """**Ruling R111**, on the integer, through Typer's own runner, for each of the four.

    `STATE_UNWRITABLE` and not `LOCK_HELD`, which would send a user to wait for a run that does
    not exist, and not `MANIFEST_UNWRITABLE`, which promises something specifically about the
    manifest under R63's ordering — the sentinel is not the manifest, and a script reading 11
    would believe a record had been attempted.
    """
    before = digests(empty_target)
    manifests = read_only_manifests(state_root)
    try:
        result = run(runner, installed, *command, "--target", str(empty_target))
    finally:
        manifests.chmod(0o700)

    assert result.exit_code == STATE_UNWRITABLE
    assert "STATE_UNWRITABLE" in result.stderr
    assert digests(empty_target) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a mode-500 directory regardless")
def test_the_diagnosis_says_nothing_was_written_and_names_the_sentinel(
    runner: CliRunner, installed: Path, empty_target: Path, state_root: Path
) -> None:
    """The message is the remedy. It names the path a user has to fix and says, in as many
    words, that the run wrote nothing — which the lock's position before the backup, the record
    and the first file is what makes true."""
    sentinel = lock_path_for(empty_target, state_root=state_root)
    manifests = read_only_manifests(state_root)
    try:
        result = run(runner, installed, "install", "--target", str(empty_target))
    finally:
        manifests.chmod(0o700)

    assert str(sentinel) in result.stderr
    assert "wrote nothing" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a mode-500 directory regardless")
def test_the_failure_is_json_on_stderr_like_every_other_one(
    runner: CliRunner, installed: Path, empty_target: Path, state_root: Path
) -> None:
    """Charter §11 and `_run`: a diagnosis goes to stderr in both modes and carries its code, so
    a wrapper parses one format rather than sniffing which stream to read."""
    manifests = read_only_manifests(state_root)
    try:
        result = run(runner, installed, "install", "--target", str(empty_target), "--json")
    finally:
        manifests.chmod(0o700)

    assert result.exit_code == STATE_UNWRITABLE
    assert json.loads(result.stderr)["error"]["code"] == "STATE_UNWRITABLE"
    assert result.stdout == ""


def test_a_held_lock_is_still_exit_10_and_writes_nothing(
    runner: CliRunner, installed: Path, empty_target: Path, state_root: Path
) -> None:
    """**The control, and the whole reason the new code is a new code.**

    A sentinel naming a live process — this one — is a lock another run holds, and it must keep
    answering `LOCK_HELD`: the remedy is to wait, and there is nothing wrong with the state
    directory. This test is what a translation that swallowed the refusal into
    `STATE_UNWRITABLE` would redden, and it is also what stays green when the `OSError`
    translation above is removed, so the pair separates the two failures rather than testing
    one of them twice.
    """
    sentinel = lock_path_for(empty_target, state_root=state_root)
    sentinel.write_text(
        json.dumps({"schema_version": 1, "pid": os.getpid(), "token": "held-by-hand"}),
        encoding="utf-8",
    )
    before = digests(empty_target)

    result = run(runner, installed, "install", "--target", str(empty_target))

    assert result.exit_code == LOCK_HELD
    assert "LOCK_HELD" in result.stderr
    assert digests(empty_target) == before
    assert sentinel.is_file(), "a refused run leaves the holder's sentinel alone"
