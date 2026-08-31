"""The `library.yaml` domain types (DEC-8). Shape only — the reader is T-4."""

from __future__ import annotations

import pytest

from harness_library.domain.metadata import (
    EMPTY_ARTIFACT_METADATA,
    ArtifactMetadata,
    Collection,
    LibraryMetadata,
)


def test_an_absent_library_yaml_is_an_empty_metadata_object_not_none() -> None:
    empty = LibraryMetadata.empty()
    assert empty.artifacts == {}
    assert empty.collections == ()
    assert empty.for_artifact("skill/anything") is EMPTY_ARTIFACT_METADATA


def test_an_undeclared_artifact_gets_the_empty_declaration() -> None:
    metadata = LibraryMetadata(artifacts={"skill/known": ArtifactMetadata(tags=("process",))})
    assert metadata.for_artifact("skill/known").tags == ("process",)
    assert metadata.for_artifact("skill/unknown").tags == ()
    assert metadata.for_artifact("skill/unknown").superseded_by is None


def test_declaration_order_is_preserved() -> None:
    collection = Collection(key="delivery", members=("skill/b", "skill/a"))
    assert collection.members == ("skill/b", "skill/a")


def test_a_collection_needs_a_key() -> None:
    with pytest.raises(ValueError, match="key"):
        Collection(key="")


def test_a_collection_may_declare_a_member_that_does_not_resolve() -> None:
    """V7 reports it; the type must not make it unrepresentable, or the reader has to drop the
    member before validation ever sees it."""
    collection = Collection(key="delivery", members=("skill/gone",))
    assert collection.members == ("skill/gone",)


def test_metadata_is_frozen() -> None:
    metadata = LibraryMetadata(artifacts={"skill/known": ArtifactMetadata()})
    with pytest.raises(AttributeError):
        metadata.collections = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        metadata.artifacts["skill/other"] = ArtifactMetadata()  # type: ignore[index]


def test_supersession_is_recorded_as_an_id() -> None:
    declared = ArtifactMetadata(superseded_by="skill/delivery-lead")
    assert declared.superseded_by == "skill/delivery-lead"
