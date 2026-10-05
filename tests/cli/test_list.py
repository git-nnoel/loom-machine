"""Feature F-1 — `loom list`, and ruling R8's ranking rendered without being recomputed.

Every assertion is against the `--json` payload (ruling R7). The columnar format is presentation
and carries no guarantee; a test pinned to its spacing would fail on a change nobody promised not
to make, and would pass a change to the contract nobody noticed.
"""

from __future__ import annotations

from typing import Any

from tests.cli.conftest import Invoke, payload_of

EVERY_FIXTURE_ARTIFACT = {
    "agent/nameless",
    "agent/scribe",
    "skill/broken-links",
    "skill/dangling-successor",
    "skill/delivery-lead",
    "skill/incomplete",
    "skill/legacy-ctg-pattern",
    "skill/legacy-orchestration",
    "skill/messy",
    "skill/misnamed",
    "skill/no-entry",
}
"""Every artifact the committed fixture library holds, **including the invalid ones** (F-1)."""


def ids_of(payload: dict[str, Any]) -> list[str]:
    return [artifact["id"] for artifact in payload["artifacts"]]


def test_every_artifact_appears_including_the_invalid_ones(loom_cli: Invoke) -> None:
    """F-1's first clause. An artifact that cannot be loaded is exactly the one a user must see."""
    payload = payload_of(loom_cli("list", "--json"))

    assert set(ids_of(payload)) == EVERY_FIXTURE_ARTIFACT
    assert payload["total"] == len(EVERY_FIXTURE_ARTIFACT)


def test_the_invalid_artifacts_carry_their_findings_in_the_listing(loom_cli: Invoke) -> None:
    """A listing that showed a broken artifact without saying it was broken would be worse than
    one that omitted it: it would look like a clean library."""
    payload = payload_of(loom_cli("list", "--json"))
    by_id = {artifact["id"]: artifact for artifact in payload["artifacts"]}

    assert by_id["skill/no-entry"]["is_valid"] is False
    assert [finding["code"] for finding in by_id["skill/no-entry"]["findings"]] == ["V1"]


def test_superseded_artifacts_appear_by_default_and_rank_below_the_rest(loom_cli: Invoke) -> None:
    """Ruling R8, as rendered. The CLI does not sort — it prints the order it was handed — so this
    asserts that the order survived the adapter, which is the only thing this layer can break."""
    ids = ids_of(payload_of(loom_cli("list", "--json")))
    superseded = {
        "skill/dangling-successor",
        "skill/legacy-ctg-pattern",
        "skill/legacy-orchestration",
    }

    assert superseded <= set(ids)
    first_superseded = min(ids.index(artifact_id) for artifact_id in superseded)
    last_live = max(index for index, artifact_id in enumerate(ids) if artifact_id not in superseded)
    assert first_superseded > last_live


def test_no_superseded_narrows_the_listing(loom_cli: Invoke) -> None:
    """The flag exists so the narrowing is explicit; the *default* is what R8 fixes."""
    ids = set(ids_of(payload_of(loom_cli("list", "--no-superseded", "--json"))))

    assert "skill/legacy-orchestration" not in ids
    assert "skill/delivery-lead" in ids


def test_the_type_filter_returns_exactly_the_expected_id_set(loom_cli: Invoke) -> None:
    assert set(ids_of(payload_of(loom_cli("list", "--type", "agent", "--json")))) == {
        "agent/nameless",
        "agent/scribe",
    }


def test_the_tag_filter_returns_exactly_the_expected_id_set(loom_cli: Invoke) -> None:
    assert set(ids_of(payload_of(loom_cli("list", "--tag", "process", "--json")))) == {
        "skill/delivery-lead",
        "skill/messy",
    }


def test_the_collection_filter_returns_exactly_the_declared_members_that_exist(
    loom_cli: Invoke,
) -> None:
    assert set(ids_of(payload_of(loom_cli("list", "--collection", "delivery", "--json")))) == {
        "skill/delivery-lead",
        "agent/scribe",
    }


def test_invalid_only_returns_the_artifacts_with_an_error_finding(loom_cli: Invoke) -> None:
    """Ruling R22 in the filter: `skill/messy` carries three V6 WARNINGs and is **valid**, so it
    must not appear here. That absence is the assertion — the rest of the set is its control."""
    ids = set(ids_of(payload_of(loom_cli("list", "--invalid-only", "--json"))))

    assert ids == {
        "agent/nameless",
        "skill/broken-links",
        "skill/dangling-successor",
        "skill/incomplete",
        "skill/misnamed",
        "skill/no-entry",
    }
    assert "skill/messy" not in ids


def test_a_tag_nothing_carries_lists_nothing_rather_than_failing(loom_cli: Invoke) -> None:
    """Tags are free-form, so an unused one is indistinguishable from a misspelt one."""
    payload = payload_of(loom_cli("list", "--tag", "no-such-tag", "--json"))

    assert payload["artifacts"] == []
    assert payload["total"] == 0


def test_each_sort_key_returns_a_defined_stable_order(loom_cli: Invoke) -> None:
    """F-1's last clause. Stability is asserted by running each key twice: an order that differs
    between two runs over one snapshot is not an order, and would make truncation arbitrary."""
    for key in ("name", "updated", "size"):
        first = payload_of(loom_cli("list", "--sort", key, "--json"))
        second = payload_of(loom_cli("list", "--sort", key, "--json"))

        assert first["sort"] == key
        assert ids_of(first) == ids_of(second)
        assert set(ids_of(first)) == EVERY_FIXTURE_ARTIFACT


def test_an_unknown_sort_key_is_a_usage_error_not_a_silent_default(loom_cli: Invoke) -> None:
    """A closed enum at the boundary. Falling back to `name` would answer a question nobody
    asked."""
    result = loom_cli("list", "--sort", "sideways", "--json")

    assert result.exit_code != 0
    assert result.stdout == ""


def test_the_human_format_renders_without_the_json_flag(loom_cli: Invoke) -> None:
    """The human format is **not** contract (ruling R7), so this asserts only that it exists, is
    non-empty and mentions the ids. Nothing here pins a column, a width or a heading."""
    result = loom_cli("list")

    assert result.exit_code == 0
    assert "skill/delivery-lead" in result.stdout
