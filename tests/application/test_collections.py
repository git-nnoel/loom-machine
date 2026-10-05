"""Feature F-5 — collections, and the gap between what is declared and what exists."""

from __future__ import annotations

import pytest

from loom.application.read import get_collection, list_collections
from loom.domain.errors import CollectionNotFoundError, ErrorCode
from loom.domain.metadata import Collection
from tests.application.fakes import FakeArtifactRepository, make_artifact


def _library() -> FakeArtifactRepository:
    return FakeArtifactRepository(
        [make_artifact("alpha"), make_artifact("beta"), make_artifact("gamma")],
        collections=[
            Collection(
                key="core",
                members=("skill/gamma", "skill/ghost", "skill/alpha"),
                title="Core",
                description="the ones that matter",
            ),
            Collection(key="empty"),
        ],
    )


def test_collections_are_listed_in_declaration_order() -> None:
    """Not alphabetical: a human grouped these, and re-sorting discards the intent."""
    payload = list_collections(_library())

    assert [c.key for c in payload.collections] == ["core", "empty"]
    assert payload.total == 2


def test_a_summary_reports_the_declaration_verbatim_including_ids_that_resolve_to_nothing() -> None:
    payload = list_collections(_library())

    core = payload.collections[0]
    assert core.member_ids == ("skill/gamma", "skill/ghost", "skill/alpha")
    assert core.member_count == 3
    assert (core.title, core.description) == ("Core", "the ones that matter")


def test_members_resolve_in_declaration_order_not_listing_order() -> None:
    """A curated sequence answers a different question from `loom list`, so it keeps its order."""
    detail = get_collection(_library(), "core")

    assert [m.id for m in detail.members] == ["skill/gamma", "skill/alpha"]


def test_a_member_that_resolves_to_nothing_is_named_rather_than_dropped() -> None:
    """Feature F-5. It is also a V7 ERROR in the validation report; a caller showing one
    collection should not have to validate the library to find out a third of it is missing."""
    detail = get_collection(_library(), "core")

    assert detail.unresolved_member_ids == ("skill/ghost",)


def test_a_collection_with_no_members_resolves_to_nothing_without_failing() -> None:
    detail = get_collection(_library(), "empty")

    assert (detail.members, detail.unresolved_member_ids) == ((), ())
    assert detail.title is None


def test_an_undeclared_key_fails_loudly() -> None:
    """Charter §13. The positive control is every test above: a declared key demonstrably works."""
    with pytest.raises(CollectionNotFoundError) as raised:
        get_collection(_library(), "absent")

    assert raised.value.code is ErrorCode.COLLECTION_NOT_FOUND
    assert raised.value.key == "absent"
