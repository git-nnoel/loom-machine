"""Collections — feature F-5.

A collection is a *declaration*, and the difference between what `library.yaml` declares and what
the library actually holds is the whole point of these two use cases. `list_collections` reports
the declaration verbatim, member ids included whether or not they resolve. `get_collection`
resolves them and says plainly which ones resolved to nothing.

The unresolved ids are also V7 ERROR findings in `validate_library`. Repeating them here is not
duplication: a caller showing one collection should not have to validate the whole library to
discover that a third of the collection is missing.
"""

from __future__ import annotations

from harness_library.application.read.dtos import (
    ArtifactSummary,
    CollectionDetail,
    CollectionListPayload,
    CollectionSummary,
)
from harness_library.domain.errors import CollectionNotFoundError
from harness_library.domain.metadata import Collection
from harness_library.domain.repository import ArtifactRepository


def list_collections(repository: ArtifactRepository) -> CollectionListPayload:
    """Every collection the library declares, in declaration order.

    Declaration order and not alphabetical: `library.yaml` is authored by a human who grouped
    things in an order that means something, and re-sorting it would discard that intent.
    """
    collections = repository.list_collections()
    return CollectionListPayload(
        collections=tuple(CollectionSummary.of(collection) for collection in collections),
        total=len(collections),
    )


def get_collection(repository: ArtifactRepository, key: str) -> CollectionDetail:
    """One collection with its members resolved to artifact summaries. Feature F-5.

    Members come back in **declaration order**, not in listing order: a collection is a curated
    sequence, and ruling R8's ranking answers "what is current in this library", which is not the
    question a curated group is asking.

    A member that resolves to nothing does not remove the collection and does not raise — it is
    listed in `unresolved_member_ids` and is a V7 ERROR in the validation report.

    Raises:
        CollectionNotFoundError: the library declares no collection with this key.
    """
    collection = _require_collection(repository, key)
    by_id = {artifact.id: artifact for artifact in repository.list_all()}

    members: list[ArtifactSummary] = []
    unresolved: list[str] = []
    for member_id in collection.members:
        artifact = by_id.get(member_id)
        if artifact is None:
            unresolved.append(member_id)
        else:
            members.append(ArtifactSummary.of(artifact))

    return CollectionDetail(
        key=collection.key,
        title=collection.title,
        description=collection.description,
        members=tuple(members),
        unresolved_member_ids=tuple(unresolved),
    )


def _require_collection(repository: ArtifactRepository, key: str) -> Collection:
    """The declared collection, or a loud failure.

    Charter §13's posture: a collection key is declared, so an unrecognised one is a mistake and
    not a query that happens to match nothing. Returning an empty collection would read as "this
    collection is empty", which is a different and confidently wrong answer.
    """
    for collection in repository.list_collections():
        if collection.key == key:
            return collection
    raise CollectionNotFoundError(key)


__all__ = ["get_collection", "list_collections"]
