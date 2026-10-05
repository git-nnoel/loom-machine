"""`loom diff` — the read half of the install path. Feature F-8.

The one command in this initiative that **cannot** write, and the difference between it and
`loom install --dry-run` is worth stating because both print a plan:

* `loom diff` calls `diff_against_target`, the read use case, so it takes no lock (R85) and
  `mcp/` could reach the same composition. It describes drift and nothing else;
* `loom install --dry-run` calls `plan_install`, the **write**-side planner, so it also applies
  R75's refusal of an artifact that does not validate and V11's refusal of a symlinked root —
  and its exit status says whether the plan could be applied without a decision.

`loom diff` therefore exits 0 whatever it finds, like `loom list`. That is a decision this task made
and no criterion fixes; it is in T-22's task plan §8.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from tests.cli.write.conftest import (
    FIXTURE_LIBRARY,
    digests,
    library_with,
    run,
)


def payload_of(stdout: str) -> dict[str, Any]:
    """The `--json` payload, parsed. Plumbing; it renders no verdict (L29)."""
    parsed: dict[str, Any] = json.loads(stdout)
    return parsed


def test_diff_on_an_untouched_target_is_unchanged_everywhere_and_exits_zero(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """**Feature F-8's own sentence**, and it needs a target this tool has just installed into.

    Every path is `unchanged` because the library, the record and the disk agree about all
    three, which is the only state in C-9's table where nothing at all is proposed.
    """
    library = library_with(tmp_path, only="The one skill.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0

    result = run(runner, library, "diff", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    assert {entry["verdict"] for entry in payload["entries"]} == {"unchanged"}
    assert payload["is_complete"] is True


def test_diff_reports_drift_and_still_exits_zero(runner: CliRunner, fixture_target: Path) -> None:
    """A report says what it found; it does not fail because it found something.

    The committed pair drifts in every direction at once — paths the library holds and the
    target does not, paths the target holds and nobody claims, and one the two disagree about —
    and `loom diff` exits 0 over all of it. `loom install --dry-run` is the command whose status
    answers "could this be applied without a decision".
    """
    result = run(runner, FIXTURE_LIBRARY, "diff", "--target", str(fixture_target), "--json")

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    assert payload["is_complete"] is False
    present = {verdict for verdict, count in payload["counts"].items() if count}
    assert {"create", "foreign", "conflict"} <= present
    # Dense over all nine verdicts, zeros included (R62) — a consumer can count any of them.
    assert len(payload["counts"]) == 9


def test_diff_writes_nothing_at_all(
    runner: CliRunner, fixture_target: Path, state_root: Path
) -> None:
    """Asserted on the target's digests **and** on the absence of a state directory.

    The second half is the one that matters: `loom diff` composes a plan from the same three
    sources an install does, and a read command that wrote a manifest would make the next
    install believe it had installed something it never did.
    """
    before = digests(fixture_target)

    result = run(runner, FIXTURE_LIBRARY, "diff", "--target", str(fixture_target))

    assert result.exit_code == 0
    assert digests(fixture_target) == before
    assert not state_root.exists()


def test_diff_names_a_missing_target_rather_than_creating_it(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Ruling R71 is not only install's: a read against a typo must say so too."""
    typo = tmp_path / "clade"

    result = run(runner, FIXTURE_LIBRARY, "diff", "--target", str(typo), "--json")

    assert result.exit_code == 7
    assert not typo.exists()
