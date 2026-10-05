"""`loom install` — the first command in this project that can destroy a file. Features F-9, F-13.

Everything the install *decides* was decided and proven below: the verdict table in T-12, the
record ordering in T-16, the lock in T-17, V11's refusal in T-20. What is decided at this layer
and nowhere else is what this module asserts:

* the **exit status**, on the integer, through Typer's runner. `INCOMPLETE = 6` is a contract
  (R57) and initiative 03 maps the same codes to HTTP statuses;
* that **`--dry-run` writes nothing**, asserted on the files rather than on the report (R31);
* that a **missing `--target` is named and not created** (R71);
* that two targets stay independent (F-13, R43);
* that **nothing but the payload reaches stdout** (charter §11, R3).

Assertions are against the `--json` payload (R7) and against file digests. The columnar format is
presentation and may be re-tasted at any time; a test pinning a substring of it would claim a
guarantee this project has not made.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from loom.cli.main import app
from tests.cli.write.conftest import (
    FIXTURE_LIBRARY,
    SETTINGS,
    SYNCED_MARKER,
    digests,
    library_with,
    run,
    write,
)

ONLY = "skills/only/SKILL.md"
"""Where the one-skill library below lands in a target. The forward join, spelled out once."""


def payload_of(stdout: str) -> dict[str, Any]:
    """The `--json` payload, parsed. Plumbing: it collects evidence and renders no verdict (L29)."""
    parsed: dict[str, Any] = json.loads(stdout)
    return parsed


def error_of(stderr: str) -> dict[str, Any]:
    """The `--json` error envelope from stderr, parsed."""
    envelope: dict[str, Any] = json.loads(stderr)
    error: dict[str, Any] = envelope["error"]
    return error


# -- The complete run. The named control for mutations (a) and (b) -------------------------------


def test_a_complete_install_exits_zero_and_writes_the_library(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """A library with no faults into an empty target: everything is `create`, nothing is refused.

    **The named control for both of T-22's first two mutations.** It asserts exit 0 and the
    written bytes, which is what lets it catch "always exit 0" doing no harm here while
    "--dry-run applies the plan" still writes. A purpose-built library rather than the committed
    fixture one, because that one reproduces every failure charter §8 names and can therefore
    never produce a complete plan.
    """
    library = library_with(tmp_path, only="The one skill.")

    result = run(runner, library, "install", "--target", str(empty_target), "--json")

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    assert payload["written"] == [ONLY]
    assert payload["is_complete"] is True
    assert (empty_target / ONLY).read_bytes() == (library / ONLY).read_bytes()


# -- The refusal. F-9's three claims in one test, as the criterion requires -----------------------


def test_an_install_that_hits_a_conflict_exits_incomplete(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """**Exit 6, the artifact named, and every safe entry still written** — all three at once.

    DEC-11 exists to settle exactly that combination, so asserting it in three tests would let
    two of them pass while the one that mattered failed. The status is asserted **on the
    integer**, because that is what a script branches on and what initiative 03 maps to an HTTP
    status.
    """
    library = library_with(tmp_path, only="The one skill.", other="The other skill.")
    theirs = write(empty_target / "skills/other/SKILL.md", "the user wrote this\n").read_bytes()

    result = run(runner, library, "install", "--target", str(empty_target), "--json")

    assert result.exit_code == 6
    payload = payload_of(result.stdout)
    refused = payload["left_alone"]
    assert [(entry["verdict"], entry["artifact_id"]) for entry in refused] == [
        ("conflict", "skill/other")
    ]
    assert refused[0]["reason"]
    assert payload["written"] == [ONLY]
    assert (empty_target / "skills/other/SKILL.md").read_bytes() == theirs


# -- The dry run. Asserted on the files, never on the report --------------------------------------


def test_a_dry_run_writes_nothing(
    runner: CliRunner, tmp_path: Path, fixture_target: Path, state_root: Path
) -> None:
    """**On the digests of every path in the target**, before and after (R31, L37).

    Deliberately asserts **no exit status**: T-22's mutation (a) makes every install exit 0, and
    a dry-run test that also pinned a status would redden under a mutation that has nothing to do
    with dry runs — making it that mutation's second subject instead of this one's control. What
    it does assert beyond the files is that the plan was rendered, so the command cannot pass by
    doing nothing at all, and that no record was written: a dry run that wrote a manifest would
    be claiming an install.
    """
    library = library_with(tmp_path, only="The one skill.")
    before = digests(fixture_target)

    result = run(runner, library, "install", "--target", str(fixture_target), "--dry-run")

    assert digests(fixture_target) == before
    assert result.stdout.strip()
    assert not state_root.exists()


# -- Ruling R71. A typo in --target is a question, not a directory to create -----------------------


def test_a_missing_target_is_named_and_not_created(runner: CliRunner, tmp_path: Path) -> None:
    """`loom install --target ~/.clade` must fail naming the path and build nothing there.

    The temptation is one `mkdir -p`, and the cost of giving in is a complete harness in a typo,
    reported as a success, with the user's real one untouched.
    """
    library = library_with(tmp_path, only="The one skill.")
    typo = tmp_path / "clade"

    result = run(runner, library, "install", "--target", str(typo), "--json")

    assert result.exit_code == 7
    error = error_of(result.stderr)
    assert error["code"] == "TARGET_UNWRITABLE"
    assert str(typo) in error["message"]
    assert not typo.exists()


# -- Feature F-13. Two targets from one library ----------------------------------------------------


def test_installing_into_one_target_leaves_the_others_manifest_and_files_untouched(
    runner: CliRunner, tmp_path: Path, state_root: Path
) -> None:
    """Ruling R43: one manifest per target, and installing into A must not reach B.

    Asserted on **B's manifest bytes and B's files**, not on a report: the manifests live in one
    directory keyed by a digest of the target path, so a keying mistake would put both installs
    in one file and nothing above this layer would notice.
    """
    library = library_with(tmp_path, only="The one skill.")
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert run(runner, library, "install", "--target", str(second)).exit_code == 0
    recorded = {path: path.read_bytes() for path in (state_root / "manifests").iterdir()}
    held_by_second = digests(second)

    assert run(runner, library, "install", "--target", str(first)).exit_code == 0

    assert digests(second) == held_by_second
    assert {path: path.read_bytes() for path in recorded} == recorded
    assert len(list((state_root / "manifests").iterdir())) == len(recorded) + 1


# -- --prune and --force ---------------------------------------------------------------------------


def test_prune_removes_only_what_the_library_dropped(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """A file installed from an artifact the library has since dropped, and nothing beside it."""
    library = library_with(tmp_path, only="The one skill.", leaving="Here for now.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    (empty_target / "untouched.txt").write_bytes(b"nobody installed this\n")
    shutil.rmtree(library / "skills" / "leaving")

    result = run(runner, library, "install", "--target", str(empty_target), "--prune", "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["deleted"] == ["skills/leaving/SKILL.md"]
    assert not (empty_target / "skills/leaving/SKILL.md").exists()
    assert (empty_target / "untouched.txt").exists()


def test_force_installs_what_does_not_validate_and_still_refuses_a_symlinked_root(
    runner: CliRunner, fixture_target: Path
) -> None:
    """**Ruling R99: `--force` does not lift V11.**

    The committed fixture library holds both kinds of refusal — six artifacts that do not
    validate (R75) and one whose root is a symlink (V11, R46) — so one run over it shows the two
    behaving differently, which is the whole of the ruling. `skipped` is the verdict both would
    carry, so the assertion is that **exactly one artifact still carries it** and that it is the
    link.
    """
    result = run(
        runner, FIXTURE_LIBRARY, "install", "--target", str(fixture_target), "--force", "--json"
    )

    assert result.exit_code == 6
    payload = payload_of(result.stdout)
    skipped = [entry for entry in payload["left_alone"] if entry["verdict"] == "skipped"]
    assert [entry["artifact_id"] for entry in skipped] == ["skill/linked-skill"]
    # The artifacts that merely fail validation were installed, which is what --force is for.
    assert "skills/misnamed/SKILL.md" in payload["written"]
    # And the link itself was neither followed nor written over.
    assert "skills/linked-skill" not in digests(fixture_target)


# -- Charter §11. stdout carries the payload and nothing else --------------------------------------


def test_a_write_command_leaves_stdout_carrying_only_its_payload(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """One JSON document on stdout, with `--verbose` turning logging as far up as it goes.

    The write path is the first in this project that moves a user's files while holding a lock,
    so charter §11's guarantee is re-proven over it rather than inherited from `loom list`. Its
    positive control is the sibling below: without one, a command that printed nothing anywhere
    would pass this.
    """
    library = library_with(tmp_path, only="The one skill.")

    result = runner.invoke(
        app,
        [
            "--verbose",
            "--library",
            str(library),
            "install",
            "--target",
            str(empty_target),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert payload_of(result.stdout)["is_complete"] is True


def test_a_failing_write_command_writes_nothing_at_all_to_stdout(
    runner: CliRunner, tmp_path: Path
) -> None:
    """**The positive control**, and the sharper half of it.

    A diagnosis on stdout would break `loom install --json | jq` exactly as a log line would, and
    the failure path is where a command is most tempted to print one. The assertion that stderr
    is *not* empty is what stops this passing against a command that said nothing at all.
    """
    library = library_with(tmp_path, only="The one skill.")

    result = run(runner, library, "install", "--target", str(tmp_path / "nope"), "--json")

    assert result.exit_code != 0
    assert result.stdout == ""
    assert result.stderr != ""


# -- The four argument combinations `loom install` will not accept
# -----------------------------------


def test_naming_an_artifact_without_resolve_is_a_usage_error(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """Install installs every artifact; naming one would silently mean something it does not."""
    library = library_with(tmp_path, only="The one skill.")

    result = run(runner, library, "install", "skill/only", "--target", str(empty_target))

    assert result.exit_code == 2
    assert digests(empty_target) == {}


def test_resolve_without_an_artifact_is_a_usage_error(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """Resolution is per artifact and never per run (R54)."""
    library = library_with(tmp_path, only="The one skill.")

    result = run(runner, library, "install", "--resolve", "library", "--target", str(empty_target))

    assert result.exit_code == 2
    assert digests(empty_target) == {}


def test_resolve_with_a_dry_run_is_a_usage_error(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """A dry run of a resolution would have to write the record it promises not to write."""
    library = library_with(tmp_path, only="The one skill.")

    result = run(
        runner,
        library,
        "install",
        "skill/only",
        "--resolve",
        "target",
        "--dry-run",
        "--target",
        str(empty_target),
    )

    assert result.exit_code == 2
    assert digests(empty_target) == {}


def test_resolve_edit_with_json_is_a_usage_error(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """Charter §11: an editor inherits this process's stdout, which `--json` promises carries one
    payload and nothing else. Refused, rather than silently emitting what no parser can read."""
    library = library_with(tmp_path, only="The one skill.")

    result = run(
        runner,
        library,
        "install",
        "skill/only",
        "--resolve",
        "edit",
        "--json",
        "--target",
        str(empty_target),
    )

    assert result.exit_code == 2
    assert digests(empty_target) == {}


# -- The committed fixtures, end to end ------------------------------------------------------------


def test_the_committed_library_into_the_committed_target_names_every_refusal(
    runner: CliRunner, fixture_target: Path
) -> None:
    """The run a user actually meets, over the two committed trees. Exit 6, and nothing lost.

    Both foreign paths this suite cares about survive it — the loose `settings.json` under no
    artifact root (R60) and Claude Code's own sync bucket, which has no named exclusion anywhere
    in this tool (R44) and is protected only by install never writing a foreign path (F-10).
    """
    before = digests(fixture_target)

    result = run(runner, FIXTURE_LIBRARY, "install", "--target", str(fixture_target), "--json")

    assert result.exit_code == 6
    assert payload_of(result.stdout)["is_complete"] is False
    after = digests(fixture_target)
    assert after[SETTINGS] == before[SETTINGS]
    assert after[SYNCED_MARKER] == before[SYNCED_MARKER]
