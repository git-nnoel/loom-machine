"""Feature F-5 — `loom collections`, listing and showing.

One command with an optional key: no key lists every declared collection, a key shows one with its
members resolved. The distinction the tests care about is between what `library.yaml` *declares*
and what the library actually *holds*, because that gap is the whole reason collections are
validated at all.
"""

from __future__ import annotations

from loom.cli.exit_codes import NOT_FOUND
from tests.cli.conftest import Invoke, error_of, payload_of


def test_every_declared_collection_is_listed_in_declaration_order(loom_cli: Invoke) -> None:
    """Declaration order, not alphabetical: a human grouped these and the order means something."""
    payload = payload_of(loom_cli("collections", "--json"))

    assert [collection["key"] for collection in payload["collections"]] == [
        "delivery",
        "housekeeping",
    ]
    assert payload["total"] == 2


def test_a_listed_collection_counts_every_declared_member_including_the_absent_ones(
    loom_cli: Invoke,
) -> None:
    """The declaration is what the document says; V7 is what is wrong with it. A listing that
    quietly counted only the members that resolve would hide the fault it exists to expose."""
    payload = payload_of(loom_cli("collections", "--json"))
    delivery = next(c for c in payload["collections"] if c["key"] == "delivery")

    assert delivery["member_count"] == 3
    assert "skill/also-never-existed" in delivery["member_ids"]


def test_showing_one_collection_returns_exactly_the_declared_members_that_resolve(
    loom_cli: Invoke,
) -> None:
    """F-5's first clause."""
    payload = payload_of(loom_cli("collections", "delivery", "--json"))

    assert [member["id"] for member in payload["members"]] == [
        "skill/delivery-lead",
        "agent/scribe",
    ]


def test_a_member_that_resolves_to_nothing_is_named_rather_than_dropped(loom_cli: Invoke) -> None:
    """It is also a V7 ERROR in `loom validate`; repeating it here means a user reading one
    collection is not required to validate the whole library to see that part of it is missing."""
    payload = payload_of(loom_cli("collections", "delivery", "--json"))

    assert payload["unresolved_member_ids"] == ["skill/also-never-existed"]


def test_a_collection_whose_members_all_resolve_reports_none_unresolved(loom_cli: Invoke) -> None:
    """The positive control for the assertion above: `unresolved_member_ids` is capable of being
    empty, so a non-empty one is a finding and not an artefact of how the field is built."""
    payload = payload_of(loom_cli("collections", "housekeeping", "--json"))

    assert payload["unresolved_member_ids"] == []
    assert [member["id"] for member in payload["members"]] == ["skill/messy"]


def test_an_undeclared_collection_key_fails_loudly(loom_cli: Invoke) -> None:
    """Charter §13's posture. A collection key is *declared*, unlike a tag, so an unrecognised one
    is a mistake — and an empty collection would be a different, confidently wrong answer."""
    result = loom_cli("collections", "no-such-collection", "--json")

    assert result.exit_code == NOT_FOUND
    assert error_of(result)["code"] == "COLLECTION_NOT_FOUND"
    assert result.stdout == ""


def test_the_human_rendering_names_the_unresolved_member(loom_cli: Invoke) -> None:
    """Ruling R27 again: the gap between declaration and reality must be visible in the terminal."""
    result = loom_cli("collections", "delivery")

    assert result.exit_code == 0
    assert "skill/also-never-existed" in result.stdout
