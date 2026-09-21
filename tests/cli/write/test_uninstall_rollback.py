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
