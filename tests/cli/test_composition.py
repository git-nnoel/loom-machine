"""Contract C-8 — the precedence, and the loud failure. Charter §13.

Every step of `--library` → `$LOOM_LIBRARY` → current directory is exercised, **including the one
that supplies no flag at all**, because a precedence chain tested only through its first link is a
chain whose other two links have never run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from loom.cli.composition import (
    LibraryRootError,
    is_library,
    open_library,
    resolve_library_root,
)
from loom.cli.exit_codes import LIBRARY_UNUSABLE
from loom.cli.main import app
from loom.cli.settings import Settings
from tests.cli.conftest import payload_of, write_skill


def test_the_library_flag_wins_over_the_environment(
    tmp_path: Path, fixture_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step one of C-8. The flag is "this run" and it outranks the shell."""
    other = tmp_path / "other"
    write_skill(other, "only-here")
    monkeypatch.setenv("LOOM_LIBRARY", str(other))

    assert resolve_library_root(fixture_library) == fixture_library.resolve()


def test_the_environment_is_used_when_no_flag_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step two. `$LOOM_LIBRARY` is read through the one settings object (ruling R2)."""
    library = tmp_path / "from-env"
    write_skill(library, "env-skill")
    monkeypatch.setenv("LOOM_LIBRARY", str(library))

    assert resolve_library_root(None, settings=Settings()) == library.resolve()


def test_the_current_directory_is_used_when_nothing_else_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step three: **no flag and no variable at all**, which is how `loom list` is usually run."""
    library = tmp_path / "cwd-library"
    write_skill(library, "cwd-skill")
    monkeypatch.chdir(library)

    assert resolve_library_root(None, settings=Settings()) == library.resolve()


def test_the_whole_precedence_holds_end_to_end_through_the_command(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same three steps through the real entry point, so the wiring is proven and not only the
    helper. Each library holds one uniquely-named skill, so the answer says which root was used."""
    flagged = tmp_path / "flagged"
    from_env = tmp_path / "from-env"
    here = tmp_path / "here"
    write_skill(flagged, "flag-skill")
    write_skill(from_env, "env-skill")
    write_skill(here, "cwd-skill")
    monkeypatch.chdir(here)

    monkeypatch.setenv("LOOM_LIBRARY", str(from_env))
    flagged_result = runner.invoke(app, ["--library", str(flagged), "list", "--json"])
    env_result = runner.invoke(app, ["list", "--json"])

    monkeypatch.delenv("LOOM_LIBRARY")
    cwd_result = runner.invoke(app, ["list", "--json"])

    assert [a["id"] for a in payload_of(flagged_result)["artifacts"]] == ["skill/flag-skill"]
    assert [a["id"] for a in payload_of(env_result)["artifacts"]] == ["skill/env-skill"]
    assert [a["id"] for a in payload_of(cwd_result)["artifacts"]] == ["skill/cwd-skill"]


def test_a_directory_that_is_not_a_library_fails_loudly(tmp_path: Path) -> None:
    """Charter §13. The alternative — an empty listing — is confidently wrong in the one direction
    a user cannot detect, and it is the failure this product exists to eliminate."""
    not_a_library = tmp_path / "just-a-directory"
    not_a_library.mkdir()
    (not_a_library / "README.md").write_text("nothing to do with harnesses\n", encoding="utf-8")

    with pytest.raises(LibraryRootError) as raised:
        resolve_library_root(not_a_library)

    assert "not a harness library" in str(raised.value)


def test_the_command_reports_a_non_library_on_stderr_and_exits_library_unusable(
    tmp_path: Path, runner: CliRunner
) -> None:
    """The loud failure as a user meets it: a diagnosis on stderr, an empty stdout, and a status a
    script can branch on. **stdout stays empty**, so a `--json` consumer never sees half an
    answer."""
    not_a_library = tmp_path / "just-a-directory"
    not_a_library.mkdir()

    result = runner.invoke(app, ["--library", str(not_a_library), "list"])

    assert result.exit_code == LIBRARY_UNUSABLE
    assert result.stdout == ""
    assert "not a harness library" in result.stderr


def test_a_non_library_that_would_otherwise_have_listed_nothing(
    tmp_path: Path, runner: CliRunner
) -> None:
    """The positive control for the test above, and the point of the whole ruling.

    An **empty library** — a real one, with an empty `skills/` — lists nothing and exits zero. A
    **non-library** with the same visible content exits `LIBRARY_UNUSABLE`. Without this pair, the
    loud failure could be nothing more than "the directory was empty"."""
    empty_library = tmp_path / "empty-library"
    (empty_library / "skills").mkdir(parents=True)
    not_a_library = tmp_path / "not-a-library"
    not_a_library.mkdir()

    empty = runner.invoke(app, ["--library", str(empty_library), "list", "--json"])
    absent = runner.invoke(app, ["--library", str(not_a_library), "list", "--json"])

    assert payload_of(empty) == {"artifacts": [], "total": 0, "sort": "name"}
    assert absent.exit_code == LIBRARY_UNUSABLE


def test_a_path_that_does_not_exist_at_all_fails_loudly(tmp_path: Path) -> None:
    """Distinguished from "not a library" in the message, because the remedies differ."""
    with pytest.raises(LibraryRootError) as raised:
        resolve_library_root(tmp_path / "nowhere")

    assert "no such directory" in str(raised.value)


def test_a_file_is_not_a_library_root(tmp_path: Path) -> None:
    """`--library ./library.yaml` is a plausible mistake and must not read as an empty library."""
    file = tmp_path / "library.yaml"
    file.write_text("artifacts: {}\n", encoding="utf-8")

    with pytest.raises(LibraryRootError) as raised:
        resolve_library_root(file)

    assert "not a directory" in str(raised.value)


def test_library_yaml_alone_makes_a_directory_a_library(tmp_path: Path) -> None:
    """A library that declares metadata but holds no artifacts yet is still a library."""
    root = tmp_path / "declared"
    root.mkdir()
    (root / "library.yaml").write_text("artifacts: {}\n", encoding="utf-8")

    assert is_library(root)


def test_an_artifact_directory_alone_makes_a_directory_a_library(tmp_path: Path) -> None:
    """`library.yaml` is optional (T-4): a tree with `agents/` and no metadata is still a
    valid library."""
    root = tmp_path / "undeclared"
    (root / "agents").mkdir(parents=True)

    assert is_library(root)


def test_open_library_returns_a_repository_over_the_resolved_root(fixture_library: Path) -> None:
    """The composition root's one job, end to end: a resolved path becomes an open library."""
    repository = open_library(fixture_library)

    assert [artifact.id for artifact in repository.list_all()]
