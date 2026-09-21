"""`hl uninstall` and `hl rollback` — the two commands that undo. Features F-11, F-12.

One module rather than two, because the pair is only coherent together: uninstall takes a backup
precisely so that rollback can undo it, and the criterion that matters most — *a target comes
back to its exact prior hash set* — spans both.

What this layer decides, and what is asserted here:

* **a target with no record is refused**, loudly, with nothing removed. `uninstall_artifact`,
  `rollback_install`, `prune_target` and `clean_foreign` all require a `Manifest` and none of
  them will accept `None`; `clean_foreign`'s docstring says outright that answering "what does
  this mean for a target nothing was installed into" belongs to the composition root, and this
  is that answer;
* **which backup a bare `hl rollback` puts back** — this target's most recent, never another
  target's (R43).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from tests.cli.write.conftest import (
    digests,
    library_with,
    run,
)

ONLY = "skills/only/SKILL.md"
OTHER = "skills/other/SKILL.md"


def payload_of(stdout: str) -> dict[str, Any]:
    """The `--json` payload, parsed. Plumbing; it renders no verdict (L29)."""
    parsed: dict[str, Any] = json.loads(stdout)
    return parsed


# -- Uninstall ------------------------------------------------------------------------------------


def test_uninstall_removes_only_what_the_record_names(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """Feature F-12: a foreign file in the same directory survives, asserted on the file.

    The list of paths comes from the manifest and never from a walk of the artifact's root, so
    the swap file beside the installed one is not in the list — nothing here has to know it
    exists. The emptied directory stays behind too, which is deliberate (C-12).
    """
    library = library_with(tmp_path, only="The one skill.", other="The other skill.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    swap = empty_target / "skills/only/SKILL.md.swp"
    swap.write_bytes(b"an editor left this here\n")

    result = run(runner, None, "uninstall", "skill/only", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["removed"] == [ONLY]
    assert not (empty_target / ONLY).exists()
    assert swap.read_bytes() == b"an editor left this here\n"
    assert (empty_target / OTHER).exists()
    assert (empty_target / "skills" / "only").is_dir()


def test_uninstalling_from_a_target_with_no_record_is_refused(
    runner: CliRunner, empty_target: Path
) -> None:
    """Nothing was installed here, so there is nothing of this artifact to remove.

    Loud rather than a quiet success: charter §13's posture, and the same one the use case keeps
    when the manifest exists but names no such artifact.
    """
    before = digests(empty_target)

    result = run(runner, None, "uninstall", "skill/only", "--target", str(empty_target), "--json")

    assert result.exit_code == 3
    assert json.loads(result.stderr)["error"]["code"] == "ARTIFACT_NOT_FOUND"
    assert digests(empty_target) == before


# -- Rollback --------------------------------------------------------------------------------------


def test_rollback_restores_the_exact_prior_hash_set(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """**Feature F-11, asserted per file**, and over a *first* install — the hard case.

    A first install creates paths that were not there, and a rollback that only overwrote would
    leave every one of them behind and call the target restored. Ruling R79 makes the backup
    describe the absences too, so putting it back removes them again; the digest map is empty
    before and must be empty after.
    """
    library = library_with(tmp_path, only="The one skill.", other="The other skill.")
    before = digests(empty_target)
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    assert digests(empty_target) != before

    result = run(runner, None, "rollback", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    assert sorted(payload_of(result.stdout)["removed"]) == sorted([ONLY, OTHER])
    assert {
        path: digest for path, digest in digests(empty_target).items() if digest != "<directory>"
    } == before


def test_a_bare_rollback_takes_this_targets_most_recent_backup(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Ruling R43: one state root holds every target's backups, so the choice is by target.

    A rollback that took the newest backup in the directory would put one user's target back
    over another's the moment they installed into two places, which is exactly what `--target`
    exists to keep apart.
    """
    library = library_with(tmp_path, only="The one skill.")
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert run(runner, library, "install", "--target", str(first)).exit_code == 0
    assert run(runner, library, "install", "--target", str(second)).exit_code == 0
    held_by_second = digests(second)

    result = run(runner, None, "rollback", "--target", str(first), "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["removed"] == [ONLY]
    assert not (first / ONLY).exists()
    # The newer backup belongs to the other target and was not the one put back.
    assert digests(second) == held_by_second


def test_rolling_back_a_target_with_no_backup_is_refused(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """There is nothing to put back, and saying so is not the same as doing nothing quietly."""
    library = library_with(tmp_path, only="The one skill.")
    other = tmp_path / "other"
    other.mkdir()
    assert run(runner, library, "install", "--target", str(other)).exit_code == 0

    result = run(runner, None, "rollback", "--target", str(empty_target), "--json")

    assert result.exit_code == 3
    assert digests(empty_target) == {}


def test_rollback_undoes_an_uninstall(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """The pair, closed. The reason uninstall takes a backup at all is this one command.

    Asserted on the file's bytes: after install, uninstall and rollback, the artifact is back
    exactly as the library wrote it.
    """
    library = library_with(tmp_path, only="The one skill.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    installed = (empty_target / ONLY).read_bytes()
    assert (
        run(runner, None, "uninstall", "skill/only", "--target", str(empty_target)).exit_code == 0
    )
    assert not (empty_target / ONLY).exists()

    result = run(runner, None, "rollback", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    assert (empty_target / ONLY).read_bytes() == installed


# -- A rollback with nothing to put back, and the listing that makes ids reachable (T-24) --------
#
# **Ruling R112.** A `MANIFEST_REPAIR`-only install writes the record and not one file, so it
# takes no backup — and `hl rollback` after one exited `BACKUP_FAILED = 9`, the same status as
# *the backup could not be taken*. C-14's whole point is that a script can tell "you must decide"
# from "it broke"; that made it tell a fact from a failure.
#
# **Ruling R113.** `hl rollback [BACKUP_ID]` takes an id and nothing in the tool would say one:
# `BackupStore.list()` has been on C-13 since T-16 and no command reached it, so "undo three
# installs rather than the last" (R54) was unreachable in practice.


def an_already_populated_target(tmp_path: Path, target: Path) -> Path:
    """A target already holding the library's exact bytes, with no record of them.

    That is the `MANIFEST_REPAIR` case and it is the ordinary one: a user's harness holds the
    artifacts already and the first `hl install` adopts them, writing the manifest and no file.
    Returns the library.
    """
    library = library_with(tmp_path, only="The one skill.")
    destination = target / ONLY
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((library / "skills" / "only" / "SKILL.md").read_bytes())
    return library


def test_an_install_that_wrote_nothing_takes_no_backup(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """The precondition, asserted so the test below cannot pass for the wrong reason.

    If this install did take a backup, the rollback after it would have one to put back and
    R112's branch would never be reached — the test would be green and about nothing.
    """
    library = an_already_populated_target(tmp_path, empty_target)
    before = digests(empty_target)

    result = run(runner, library, "install", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["backup_id"] is None
    assert payload_of(result.stdout)["written"] == []
    assert digests(empty_target) == before


def test_rolling_back_a_run_that_wrote_nothing_is_not_a_failure(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """**Ruling R112, on the integer.** A run that wrote nothing has nothing to undo.

    Exit 0 and a payload naming no backup, rather than `BACKUP_FAILED = 9` — which says *the
    backup could not be taken*, about a run that needed none, and shares a number with the
    genuine failure below.
    """
    library = an_already_populated_target(tmp_path, empty_target)
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    before = digests(empty_target)

    result = run(runner, None, "rollback", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["backup_id"] is None
    assert payload_of(result.stdout)["restored"] == []
    assert payload_of(result.stdout)["removed"] == []
    assert digests(empty_target) == before


def test_the_human_rendering_says_there_is_nothing_to_undo(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """A status a script reads and a sentence a person reads. Exit 0 with no output at all would
    be the tool doing nothing quietly, which is the one thing this product exists not to do."""
    library = an_already_populated_target(tmp_path, empty_target)
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0

    result = run(runner, None, "rollback", "--target", str(empty_target))

    assert result.exit_code == 0
    assert "nothing to roll back" in result.stdout
    assert result.stderr == ""


def test_a_backup_the_record_names_and_the_store_has_lost_is_still_a_failure(
    runner: CliRunner, tmp_path: Path, empty_target: Path, state_root: Path
) -> None:
    """**The control for R112, and the reason the predicate is not "the store is empty".**

    The record is what tells a fact from a failure: a run that took no backup recorded none, and
    a run that took one and cannot find it again has lost a rollback point the user still
    believes in. Reporting *there is nothing to put back* for the second would be the tool lying
    about its own undo — and it is not hypothetical, because a backup written by an older build
    is one this reader declines to offer (`infrastructure/backup.py`'s `SCHEMA_VERSION`).
    """
    library = library_with(tmp_path, only="The one skill.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    shutil.rmtree(state_root / "backups")

    result = run(runner, None, "rollback", "--target", str(empty_target), "--json")

    assert result.exit_code == 9
    assert payload_of(result.stderr)["error"]["code"] == "BACKUP_FAILED"


def test_backups_lists_an_id_rollback_accepts(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """**Ruling R113, and the assertion is that the two commands agree.**

    A listing whose ids `hl rollback` would not take is not a listing. So the id is read out of
    this command's payload and passed straight to the other one, which is the whole journey
    R54's argument describes and which no test could make before T-24.
    """
    library = library_with(tmp_path, only="The one skill.", other="The other skill.")
    before = digests(empty_target)
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0

    listed = run(runner, None, "backups", "--target", str(empty_target), "--json")

    assert listed.exit_code == 0
    payload = payload_of(listed.stdout)
    assert len(payload["backups"]) == 1
    backup_id = payload["backups"][0]["backup_id"]
    assert payload["backups"][0]["described"] == 2
    assert payload["backups"][0]["kept"] == 0

    result = run(runner, None, "rollback", backup_id, "--target", str(empty_target))

    assert result.exit_code == 0
    assert {
        path: digest for path, digest in digests(empty_target).items() if digest != "<directory>"
    } == before


def test_backups_lists_only_this_targets_own(runner: CliRunner, tmp_path: Path) -> None:
    """Ruling R43, the same filter `hl rollback` makes without an id, and one definition of it.

    One state root holds every target's backups. A listing that showed them all would offer a
    user ids that `hl rollback --target` would put back over a different directory — or refuse,
    which is no better for a command whose job is to say what can be undone.
    """
    library = library_with(tmp_path, only="The one skill.")
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert run(runner, library, "install", "--target", str(first)).exit_code == 0
    assert run(runner, library, "install", "--target", str(second)).exit_code == 0

    of_first = payload_of(run(runner, None, "backups", "--target", str(first), "--json").stdout)
    of_second = payload_of(run(runner, None, "backups", "--target", str(second), "--json").stdout)

    assert len(of_first["backups"]) == len(of_second["backups"]) == 1
    assert of_first["backups"][0]["backup_id"] != of_second["backups"][0]["backup_id"]
    assert of_first["target_path"] != of_second["target_path"]


def test_backups_of_a_target_with_none_is_an_empty_listing_and_not_a_failure(
    runner: CliRunner, empty_target: Path
) -> None:
    """The positive control for the two above: an empty listing is a value.

    And it needs **no manifest** — this command takes no lock and reads no record (R85), because
    a target whose record was deleted still has its backups and that is exactly when a user
    comes looking for them. `hl uninstall`, `hl rollback` and `hl clean` all refuse such a
    target; this one answers it.
    """
    result = run(runner, None, "backups", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["backups"] == []
