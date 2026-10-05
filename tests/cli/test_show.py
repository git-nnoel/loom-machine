"""Feature F-2 — `loom show`, and the case the whole validation system exists to serve.

**The superseded plan crashed with an unhandled exception on a skill directory with no entry
document.** That is the one artifact a user most needs to see, because it is the artifact that
otherwise loads silently as nothing. The fixture library holds one (`skills/no-entry/`) and it is
the subject of the mutation check named for this task.
"""

from __future__ import annotations

from loom.cli.exit_codes import NOT_FOUND
from tests.cli.conftest import Invoke, error_of, payload_of


def test_show_renders_a_valid_artifact(loom_cli: Invoke) -> None:
    """The control. Entry text, file list and frontmatter, per F-2's first clause.

    Named in the mutation check as the test that must **stay green**: a change that makes `loom
    show`
    raise on a broken artifact must not also be a change that broke `loom show` outright."""
    payload = payload_of(loom_cli("show", "skill/delivery-lead", "--json"))

    assert payload["id"] == "skill/delivery-lead"
    assert payload["is_valid"] is True
    assert payload["entry_path"] == "SKILL.md"
    assert payload["entry_text"] is not None
    assert payload["frontmatter"]["name"] == "delivery-lead"
    assert [file["path"] for file in payload["files"]]


def test_show_renders_findings_for_the_entry_less_skill(loom_cli: Invoke) -> None:
    """**Feature F-2's whole point, and mutation check (b).**

    A skill directory with no `SKILL.md` is *shown*, with its V1 finding and a null entry document,
    and the command exits zero. The artifact's own defect is the answer, not an error."""
    result = loom_cli("show", "skill/no-entry", "--json")

    assert result.exit_code == 0, f"F-2: showing a broken artifact must not fail: {result.stderr}"
    payload = payload_of(result)
    assert payload["id"] == "skill/no-entry"
    assert payload["is_valid"] is False
    assert payload["entry_text"] is None
    assert [finding["code"] for finding in payload["findings"]] == ["V1"]


def test_the_human_rendering_of_a_broken_artifact_also_survives(loom_cli: Invoke) -> None:
    """The same case without `--json`. The two renderings share a payload but not a code path, and
    F-2 is about what a human sees — a crash in the table renderer would be the same defect."""
    result = loom_cli("show", "skill/no-entry")

    assert result.exit_code == 0
    assert "V1" in result.stdout


def test_every_invalid_fixture_artifact_can_be_shown(loom_cli: Invoke) -> None:
    """The generalisation of F-2: *no* artifact in the library is unshowable. Each of these is a
    different fault — a missing entry, a name disagreement, a broken citation, an empty required
    key, a dangling successor — and a renderer that copes with one may still crash on another."""
    for artifact_id in (
        "skill/no-entry",
        "skill/misnamed",
        "skill/broken-links",
        "skill/incomplete",
        "skill/dangling-successor",
        "agent/nameless",
        "skill/messy",
    ):
        payload = payload_of(loom_cli("show", artifact_id, "--json"))
        assert payload["id"] == artifact_id


def test_a_superseded_artifact_says_so_on_its_detail(loom_cli: Invoke) -> None:
    """Ruling R8 requires the marker on every payload, not only in a listing."""
    payload = payload_of(loom_cli("show", "skill/legacy-orchestration", "--json"))

    assert payload["superseded_by"] == "skill/delivery-lead"


def test_an_unknown_id_is_the_only_thing_show_fails_on(loom_cli: Invoke) -> None:
    """The positive control for F-2: `loom show` *can* fail, so the passes above are not vacuous."""
    result = loom_cli("show", "skill/never-heard-of-it", "--json")

    assert result.exit_code == NOT_FOUND
    assert error_of(result)["code"] == "ARTIFACT_NOT_FOUND"
