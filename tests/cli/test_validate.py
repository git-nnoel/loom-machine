"""Feature F-4 — `hl validate` and its exit status. Ruling R22.

The two tests this task's mutation check names live here. They are a pair on purpose: "exit
non-zero on ERROR" and "exit zero on WARNING-only" are each trivially satisfiable alone, by
returning a constant, and only together do they describe the behaviour F-4 asks for.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from harness_library.cli.exit_codes import OK, VALIDATION_FAILED
from harness_library.cli.main import app
from tests.cli.conftest import Invoke, payload_of, write_skill


def test_validate_exits_non_zero_when_an_error_finding_exists(hl: Invoke) -> None:
    """**Mutation check (a): the assertion that must fail.**

    The committed fixture library carries V1 through V7. A CI job or a pre-commit hook branches on
    exactly this status, so a validate that always exits zero is a validate that never blocks
    anything — which is the decorative-rule failure charter §8 exists to close."""
    result = hl("validate", "--json")

    assert result.exit_code == VALIDATION_FAILED
    assert result.stdout != ""


def test_validate_exits_zero_when_the_only_findings_are_warnings(
    tmp_path: Path, runner: CliRunner
) -> None:
    """**Mutation check (a): the assertion that must STAY GREEN.** Ruling R22.

    A stray editor swap file is a V6 WARNING. It is reported, and it must not fail the command —
    "always exit 1" would satisfy the test above and break this one, which is the point of the
    pair."""
    library = tmp_path / "warned"
    skill = write_skill(library, "tidy")
    (skill / "SKILL.md.swp").write_bytes(b"editor leftovers")

    result = runner.invoke(app, ["--library", str(library), "validate", "--json"])
    payload = json.loads(result.stdout)

    assert payload["warning_count"] >= 1, "the V6 warning must actually be present"
    assert payload["error_count"] == 0
    assert payload["is_valid"] is True
    assert result.exit_code == OK


def test_a_clean_library_exits_zero_with_nothing_to_report(
    tmp_path: Path, runner: CliRunner
) -> None:
    """The floor. A library with no findings at all must not be reported as warned or invalid."""
    library = tmp_path / "clean"
    write_skill(library, "tidy")

    result = runner.invoke(app, ["--library", str(library), "validate", "--json"])
    payload = payload_of(result)

    assert result.exit_code == OK
    assert payload["is_valid"] is True
    assert payload["error_count"] == 0
    assert payload["warning_count"] == 0
    assert payload["artifacts"] == []
    assert payload["artifact_count"] == 1


def test_the_report_reaches_the_library_level_findings(hl: Invoke) -> None:
    """Ruling R23. V7 belongs to `library.yaml` and has no artifact to hang on; a CLI that rendered
    only the artifact loop would print a report missing two rows of charter §8's register."""
    result = hl("validate", "--json")
    payload = json.loads(result.stdout)

    assert [finding["code"] for finding in payload["library_findings"]] == ["V7", "V7"]


def test_the_exit_status_is_the_reports_verdict_and_not_a_recount(hl: Invoke) -> None:
    """The CLI must not hold a second opinion about validity. Asserted by tying the status to
    `is_valid` from the payload rather than to a number this test also knows."""
    result = hl("validate", "--json")
    payload = json.loads(result.stdout)

    expected = OK if payload["is_valid"] else VALIDATION_FAILED
    assert result.exit_code == expected


def test_the_human_report_names_the_warnings_without_failing(
    tmp_path: Path, runner: CliRunner
) -> None:
    """A warning that is not shown is a warning that does not exist (ruling R27), and showing it
    must still not change the status."""
    library = tmp_path / "warned"
    skill = write_skill(library, "tidy")
    (skill / "SKILL.md.swp").write_bytes(b"editor leftovers")

    result = runner.invoke(app, ["--library", str(library), "validate"])

    assert result.exit_code == OK
    assert "V6" in result.stdout
