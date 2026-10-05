"""`loom install --resolve` — two write use cases in one command. Feature F-15, rulings R54, R104.

This is the only command in the project that runs **two** write use cases, and the two things
that can go wrong with it are invisible to every layer below:

* **the lock is not re-entrant** (C-16), so they run in sequence and never nested. Nothing here
  asserts that directly — `tests/test_single_writer.py` owns the lock — but every test in this
  module would deadlock or exit `LOCK_HELD = 10` if it were got wrong, which is why they all
  assert an exit status;
* **the second use case must be handed the manifest the first one wrote** (R104). `ManifestStore`
  has one member (C-15), so there is no way for `application/` to refresh a record between them,
  and a resolve given the stale one silently drops every artifact the apply just installed. That
  is T-22's mutation (c) and `test_a_resolving_install_keeps_the_record_the_apply_wrote` is the
  assertion named for it.

**The apply runs first and the resolution last**, which is what makes F-15's criterion reachable
through the CLI at all: recording the target's digest turns the path into an `update`, so a
re-planned apply *after* a `--resolve target` would overwrite the very file the user asked to
keep. Ruling R100 puts that overwrite on the **next** install, and
`test_the_next_install_overwrites_a_kept_copy` proves it is where the help text says it is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from loom.infrastructure.manifest_store import read_manifest
from tests.cli.write.conftest import (
    FIXTURE_LIBRARY,
    digests,
    library_with,
    run,
    write,
)
from tests.rendering import flattened

ALPHA = "skills/alpha/SKILL.md"
BETA = "skills/beta/SKILL.md"

THEIRS = "what the user wrote in their own target\n"
"""The bytes a `--resolve target` has to leave exactly where they are."""


def payload_of(stdout: str) -> dict[str, Any]:
    """The `--json` payload, parsed. Plumbing; it renders no verdict (L29)."""
    parsed: dict[str, Any] = json.loads(stdout)
    return parsed


def conflicted(tmp_path: Path, target: Path, *, others: bool = False) -> Path:
    """A library and a target that disagree about `beta`, and agree about nothing else yet.

    `alpha` is absent from the target, so the apply **installs** it — which is the artifact the
    stale-manifest mutation drops. `beta` is in both, with different bytes and no record of an
    install, so it is a `conflict` for the resolution to settle.
    """
    library = library_with(tmp_path, alpha="Alpha's prose.", beta="Beta's prose.")
    write(target / BETA, THEIRS)
    if others:
        write(target / ALPHA, "and the user wrote this one too\n")
    return library


# -- The two sides ---------------------------------------------------------------------------------


def test_resolve_library_writes_the_librarys_version(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """F-15's first half: the library's bytes land in the target and the run exits 0."""
    library = conflicted(tmp_path, empty_target)

    result = run(
        runner,
        library,
        "install",
        "skill/beta",
        "--resolve",
        "library",
        "--target",
        str(empty_target),
        "--json",
    )

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    assert payload["resolution"]["side"] == "library"
    assert payload["resolution"]["written"] == [BETA]
    assert (empty_target / BETA).read_bytes() == (library / BETA).read_bytes()


def test_resolve_target_leaves_the_conflicted_file_byte_identical(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """F-15's second half — **and the named control for T-22's mutation (c)**.

    It asserts the conflicted file's bytes, the exit status and which paths the record was
    repaired for: three facts about the *resolved* artifact, every one of which a stale manifest
    still gets right. It deliberately asserts nothing about `alpha` and nothing about the
    manifest's contents, which is what keeps it a control rather than a second subject.
    """
    conflicted(tmp_path, empty_target)
    kept = (empty_target / BETA).read_bytes()

    result = run(
        runner,
        library_at(tmp_path),
        "install",
        "skill/beta",
        "--resolve",
        "target",
        "--target",
        str(empty_target),
        "--json",
    )

    assert result.exit_code == 0
    assert payload_of(result.stdout)["resolution"]["repaired"] == [BETA]
    assert (empty_target / BETA).read_bytes() == kept


def library_at(tmp_path: Path) -> Path:
    """Where `conflicted` put the library. Spelled once so the test above reads as one claim."""
    return tmp_path / "library"


# -- Ruling R104. The second run gets the record the first one wrote -------------------------------


def test_a_resolving_install_keeps_the_record_the_apply_wrote(
    runner: CliRunner, tmp_path: Path, empty_target: Path, state_root: Path
) -> None:
    """**T-22's mutation (c).** The artifact the apply installed must still be in the record.

    `resolve_conflict` composes the new manifest from the one it is *given* — every artifact it
    did not decide about is carried over verbatim — and `ManifestStore` has no `read`, so the
    only way it can know about `skill/alpha` is if the command hands it `ApplyResult.manifest`
    rather than the manifest read before the command started.

    Handed the stale one, the record that lands on disk names `skill/beta` alone, and every file
    the apply wrote for `skill/alpha` becomes `FOREIGN` on the next scan: install will not touch
    it, uninstall cannot remove it, and nothing in this initiative can recover it. Nothing fails
    at the time, which is the whole reason this assertion exists.
    """
    conflicted(tmp_path, empty_target)

    result = run(
        runner,
        library_at(tmp_path),
        "install",
        "skill/beta",
        "--resolve",
        "target",
        "--target",
        str(empty_target),
        "--json",
    )

    assert result.exit_code == 0
    recorded = read_manifest(empty_target, state_root=state_root)
    assert recorded is not None
    assert sorted(record.artifact_id for record in recorded.artifacts) == [
        "skill/alpha",
        "skill/beta",
    ]
    # The positive control for the line above: the apply really did write alpha's file, so
    # "recorded" cannot mean "recorded something that was never installed".
    assert (empty_target / ALPHA).exists()


# -- Ruling R54. Per artifact, never per run -------------------------------------------------------


def test_resolving_one_conflict_leaves_the_other_refused_and_byte_identical(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """Two conflicts, one resolved: the other keeps its bytes and the run is still incomplete.

    That is what makes `--resolve` a decision about a thing the user looked at rather than a
    switch that turns the refusal posture off for the whole run.
    """
    conflicted(tmp_path, empty_target, others=True)
    untouched = (empty_target / ALPHA).read_bytes()

    result = run(
        runner,
        library_at(tmp_path),
        "install",
        "skill/beta",
        "--resolve",
        "library",
        "--target",
        str(empty_target),
        "--json",
    )

    assert result.exit_code == 6
    payload = payload_of(result.stdout)
    assert [entry["artifact_id"] for entry in payload["left_alone"]] == ["skill/alpha"]
    assert (empty_target / ALPHA).read_bytes() == untouched


# -- Ruling R100. It settles the refusal; it does not pin the file ---------------------------------


def test_the_resolve_help_says_that_target_does_not_pin(runner: CliRunner) -> None:
    """**Ruling R100, asserted on the help text**, because that is where the ruling puts it.

    A user reading "keep what is on disk" will expect the opposite of what happens next, and the
    only place this tool can tell them before they choose is the flag's own help.

    **The assertion is about the wording and nothing else** (R117). The rendering is decoration,
    not contract: Typer wraps every option's help to the terminal width, boxes it, and \u2014 where
    Rich thinks it has a terminal \u2014 colours the box rules, which puts escapes inside any phrase
    that crossed the panel's edge. `flattened` takes all three out. The width that decides
    where the wrap falls is pinned by `pinned_terminal_width`, so this reads the same here as in
    CI; it is pinned narrow enough that the phrase still wraps, because a wrap it never meets is
    a wrap it cannot survive.
    """
    result = run(runner, None, "install", "--help")

    assert result.exit_code == 0
    rendered = flattened(result.stdout)
    assert "does NOT pin the file" in rendered
    assert "NEXT loom install writes the library's version over the copy you kept" in rendered


def test_the_next_install_overwrites_a_kept_copy(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """**The behaviour the help text promises, proven rather than described.**

    After `--resolve target` the record agrees with the disk, so the path reads `update` — the
    library has moved on and the target holds exactly what this tool considers installed. The
    next install therefore overwrites it without asking, which is correct and is the thing a
    user will not expect. If this test ever goes red, the help text above has become a lie and
    one of the two has to change.
    """
    library = conflicted(tmp_path, empty_target)
    kept = (empty_target / BETA).read_bytes()
    first = run(
        runner,
        library,
        "install",
        "skill/beta",
        "--resolve",
        "target",
        "--target",
        str(empty_target),
    )
    assert first.exit_code == 0
    assert (empty_target / BETA).read_bytes() == kept

    second = run(runner, library, "install", "--target", str(empty_target), "--json")

    assert second.exit_code == 0
    assert payload_of(second.stdout)["written"] == [BETA]
    assert (empty_target / BETA).read_bytes() == (library / BETA).read_bytes()


# -- Ruling R99. `--resolve` does not lift V11 either ----------------------------------------------


def test_resolve_does_not_lift_a_symlinked_artifact_root(
    runner: CliRunner, fixture_target: Path
) -> None:
    """A `skipped` artifact has no two versions to choose between, so no side can take it.

    The committed library's `skill/linked-skill` is an artifact root that is a symlink: the scan
    never followed it, so the library holds no bytes for it at all. The entry comes back still
    refused, carrying its own V11 reason, and neither the link nor its destination appears in the
    target.
    """
    result = run(
        runner,
        FIXTURE_LIBRARY,
        "install",
        "skill/linked-skill",
        "--resolve",
        "library",
        "--target",
        str(fixture_target),
        "--json",
    )

    assert result.exit_code == 6
    resolution = payload_of(result.stdout)["resolution"]
    refused = resolution["left_alone"]
    assert [entry["verdict"] for entry in refused] == ["skipped"]
    assert "V11" in refused[0]["reason"]
    assert resolution["written"] == []
    assert "skills/linked-skill" not in digests(fixture_target)


# -- Ruling R102. The editor's failures have a code, and no test ever opens one --------------------


def test_an_unset_editor_is_reported_with_its_own_status(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """`EDITOR_FAILED = 14`. Without it the user meets a traceback for an unset shell variable.

    `sandbox_home` removes `$EDITOR` from every test in this module, so this is the state a user
    who has never set it is in. **Nothing is spawned**: the refusal is raised before a version is
    materialised, let alone a process started.
    """
    conflicted(tmp_path, empty_target)
    before = digests(empty_target)

    result = run(
        runner,
        library_at(tmp_path),
        "install",
        "skill/beta",
        "--resolve",
        "edit",
        "--target",
        str(empty_target),
    )

    assert result.exit_code == 14
    assert "EDITOR_FAILED" in result.stderr
    # The apply ran before the resolution, so the target has changed — but not the refused path.
    assert digests(empty_target)[BETA] == before[BETA]


def test_an_editor_that_cannot_be_run_is_reported_with_the_same_status(
    runner: CliRunner, tmp_path: Path, empty_target: Path, monkeypatch: Any
) -> None:
    """The other half of R102: `$EDITOR` set to something that is not there.

    The command really is attempted and `execve` really does fail, which is the point — this is
    the path `SubprocessConflictEditor` takes and `ReportingConflictEditor` translates. It cannot
    hang: there is no such program to wait for.
    """
    conflicted(tmp_path, empty_target)
    monkeypatch.setenv("EDITOR", "loom-no-such-editor --wait")

    result = run(
        runner,
        library_at(tmp_path),
        "install",
        "skill/beta",
        "--resolve",
        "edit",
        "--target",
        str(empty_target),
    )

    assert result.exit_code == 14
    assert "loom-no-such-editor --wait" in result.stderr
