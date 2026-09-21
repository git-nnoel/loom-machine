"""`hl clean` and `hl export`. Features F-10, F-12 and F-16, ruling R96.

`hl clean` is the one command in this project that removes a path **nothing** describes — no
library, no manifest, no backup taken by anyone else. Its safety model is the listing, and
ruling R96 states it as two halves this layer owns: *it lists by default, and removes only when
asked*. Both are asserted here on the files, not on the report.

`hl export` is the opposite: it writes one archive and touches no target at all. The criterion
F-16 is stated as is a **path list**, so that is what is asserted — against `zipfile`'s own
`namelist()`, read back off the file the command wrote.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from tests.cli.write.conftest import (
    FIXTURE_LIBRARY,
    SETTINGS,
    SYNCED_MARKER,
    SYNCED_SKILL,
    TARGET_SYMLINK,
    digests,
    library_with,
    run,
)

ONLY = "skills/only/SKILL.md"


def payload_of(stdout: str) -> dict[str, Any]:
    """The `--json` payload, parsed. Plumbing; it renders no verdict (L29)."""
    parsed: dict[str, Any] = json.loads(stdout)
    return parsed


# -- clean --foreign -------------------------------------------------------------------------------


def test_clean_lists_the_foreign_paths_and_removes_nothing_by_default(
    runner: CliRunner, fixture_target: Path
) -> None:
    """**Ruling R96's first half**, asserted on the digests of every path in the target.

    The listing has to be non-empty for the absence to mean anything — a clean that found
    nothing would leave the target unchanged too — so the committed target is used, whose
    `settings.json`, editor swap file, escaping symlink and two-deep `synced/` bucket are all
    foreign and none of which has a named exclusion anywhere in this tool (R44).
    """
    assert run(runner, FIXTURE_LIBRARY, "install", "--target", str(fixture_target)).exit_code == 6
    before = digests(fixture_target)

    result = run(runner, FIXTURE_LIBRARY, "clean", "--target", str(fixture_target), "--json")

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    assert {SETTINGS, SYNCED_MARKER, SYNCED_SKILL, TARGET_SYMLINK} <= set(payload["listed"])
    assert payload["removed"] == []
    assert payload["removed_requested"] is False
    assert digests(fixture_target) == before


def test_clean_remove_deletes_exactly_what_it_listed(
    runner: CliRunner, fixture_target: Path
) -> None:
    """**Ruling R96's second half**, and the listing is still what the user is shown.

    `listed` and `removed` are the same set, so the report a user reads before authorising is
    the report of what went. The installed files and the emptied directories survive — a
    directory is never removed (C-12), and a path the manifest knows is never foreign.
    """
    assert run(runner, FIXTURE_LIBRARY, "install", "--target", str(fixture_target)).exit_code == 6
    installed = digests(fixture_target)["skills/messy/SKILL.md"]

    result = run(
        runner, FIXTURE_LIBRARY, "clean", "--target", str(fixture_target), "--remove", "--json"
    )

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    assert payload["listed"] == payload["removed"]
    assert payload["backup_id"]
    after = digests(fixture_target)
    assert SETTINGS not in after
    assert SYNCED_SKILL not in after
    assert TARGET_SYMLINK not in after
    # The bucket's directories are left behind, and so is everything this tool installed.
    assert after["skills/synced"] == "<directory>"
    assert after["skills/messy/SKILL.md"] == installed


def test_a_clean_can_be_rolled_back(runner: CliRunner, fixture_target: Path) -> None:
    """The backup is the only way back from this command, so it had better work.

    Asserted per path, including the **symlink**, which is the one ruling R94 exists for: a
    store that could not put a link back would make `clean --foreign` un-undoable for exactly
    the path most likely to be there by mistake.
    """
    assert run(runner, FIXTURE_LIBRARY, "install", "--target", str(fixture_target)).exit_code == 6
    before = digests(fixture_target)
    assert (
        run(runner, FIXTURE_LIBRARY, "clean", "--target", str(fixture_target), "--remove").exit_code
        == 0
    )

    result = run(runner, None, "rollback", "--target", str(fixture_target), "--json")

    assert result.exit_code == 0
    assert digests(fixture_target) == before


def test_cleaning_a_target_with_no_record_is_refused(
    runner: CliRunner, fixture_target: Path
) -> None:
    """**The refusal `clean_foreign` deliberately made inexpressible, answered here.**

    A target no manifest describes has no installed paths, so *every* path in it is foreign and
    `clean --remove` would mean `rm -rf` reached through a plan. The use case requires a
    manifest and says the answer belongs to the composition root; this is it, and nothing is
    removed.
    """
    before = digests(fixture_target)

    result = run(
        runner, FIXTURE_LIBRARY, "clean", "--target", str(fixture_target), "--remove", "--json"
    )

    assert result.exit_code == 3
    assert json.loads(result.stderr)["error"]["code"] == "ARTIFACT_NOT_FOUND"
    assert digests(fixture_target) == before


# -- clean --prune ---------------------------------------------------------------------------------


def test_clean_prune_lists_what_the_library_dropped_and_removes_it_only_when_asked(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """The other selector, over the other use case, keeping R96's rule.

    `--prune` acts on installed paths the library no longer holds, which is a different set and
    a different risk from `--foreign`: these were put there by this tool and the record still
    names them, so the manifest can say what went. They are still listed before they go.
    """
    library = library_with(tmp_path, only="The one skill.", leaving="Here for now.")
    assert run(runner, library, "install", "--target", str(empty_target)).exit_code == 0
    shutil.rmtree(library / "skills" / "leaving")
    before = digests(empty_target)

    listing = run(runner, library, "clean", "--prune", "--target", str(empty_target), "--json")

    assert listing.exit_code == 0
    assert payload_of(listing.stdout)["listed"] == ["skills/leaving/SKILL.md"]
    assert digests(empty_target) == before

    removal = run(
        runner, library, "clean", "--prune", "--remove", "--target", str(empty_target), "--json"
    )

    assert removal.exit_code == 0
    assert payload_of(removal.stdout)["removed"] == ["skills/leaving/SKILL.md"]
    assert not (empty_target / "skills/leaving/SKILL.md").exists()
    assert (empty_target / ONLY).exists()


def test_the_two_selectors_cannot_be_asked_for_at_once(
    runner: CliRunner, tmp_path: Path, empty_target: Path
) -> None:
    """Two sets of paths, two risks and two record orderings. Run one, look, then run the other."""
    library = library_with(tmp_path, only="The one skill.")

    result = run(runner, library, "clean", "--foreign", "--prune", "--target", str(empty_target))

    assert result.exit_code == 2


# -- export ----------------------------------------------------------------------------------------


def test_export_writes_an_archive_whose_entries_are_the_collections_files(
    runner: CliRunner, tmp_path: Path
) -> None:
    """**Feature F-16, asserted as a path list** — read back out of the file, not off the report.

    The entry names are target-relative (R73), which is what makes the archive unzip over a
    harness, and the binary file in the collection round-trips byte-identically because charter
    §7 stores and exports binary content without ever decoding it.
    """
    archive = tmp_path / "housekeeping.zip"

    result = run(
        runner, FIXTURE_LIBRARY, "export", "housekeeping", "--output", str(archive), "--json"
    )

    assert result.exit_code == 0
    payload = payload_of(result.stdout)
    with zipfile.ZipFile(archive) as opened:
        assert opened.namelist() == payload["entries"]
        assert (
            opened.read("skills/messy/references/diagram.png")
            == (FIXTURE_LIBRARY / "skills/messy/references/diagram.png").read_bytes()
        )


def test_export_defaults_its_output_to_the_collection_key(
    runner: CliRunner, tmp_path: Path, monkeypatch: Any
) -> None:
    """`./<key>.zip`, so the commonest invocation needs no flag at all."""
    monkeypatch.chdir(tmp_path)

    result = run(runner, FIXTURE_LIBRARY, "export", "housekeeping", "--json")

    assert result.exit_code == 0
    assert payload_of(result.stdout)["output"] == "housekeeping.zip"
    assert (tmp_path / "housekeeping.zip").is_file()


def test_exporting_an_unknown_collection_is_a_loud_failure(
    runner: CliRunner, tmp_path: Path
) -> None:
    """A collection key is declared, so an unrecognised one is a mistake and never an empty zip."""
    result = run(
        runner,
        FIXTURE_LIBRARY,
        "export",
        "no-such-collection",
        "--output",
        str(tmp_path / "out.zip"),
        "--json",
    )

    assert result.exit_code == 3
    assert json.loads(result.stderr)["error"]["code"] == "COLLECTION_NOT_FOUND"
    assert not (tmp_path / "out.zip").exists()


def test_an_archive_that_cannot_be_written_is_named(runner: CliRunner, tmp_path: Path) -> None:
    """A `--output` inside a directory that is not there. The path is in the diagnosis."""
    destination = tmp_path / "nowhere" / "out.zip"

    result = run(
        runner, FIXTURE_LIBRARY, "export", "housekeeping", "--output", str(destination), "--json"
    )

    assert result.exit_code == 7
    assert str(destination) in json.loads(result.stderr)["error"]["message"]
