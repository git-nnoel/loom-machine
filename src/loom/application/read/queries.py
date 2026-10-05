"""What a caller *asks* for: the filter and the sort key of contract C-5.

Kept apart from `dtos.py`, which is what a caller gets *back*. The two travel in opposite
directions and freeze for different reasons — a payload field is frozen because initiative 04's SPA
branches on it, a filter field because initiative 03's query string carries it.

Frozen dataclasses rather than Pydantic models, per charter §3's reasoning applied one layer out:
these are constructed in Python by an adapter that has already validated its own input, not parsed
from an untrusted document. `SortKey` is a closed enum, so a bad sort key fails at the boundary
that builds it rather than deep inside a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loom.domain.identity import ArtifactType


class SortKey(StrEnum):
    """How a listing is ordered. Closed.

    Ruling R8 sits *above* every one of these: a superseded artifact is ranked below the live ones
    whatever the key, and is never hidden. See `application.read.artifacts.sort_artifacts`.
    """

    NAME = "name"
    """By artifact name, then by type. The default, and the only key a human predicts."""

    UPDATED = "updated"
    """Most recently updated first. Ruling R5 decides where `updated_at` comes from."""

    SIZE = "size"
    """Largest first, by the total size of the artifact's files."""


@dataclass(frozen=True, slots=True)
class ArtifactFilter:
    """Which artifacts a listing or a search covers. Typed, never a bag of strings.

    Every field is ANDed with the others; the default value of each is "do not narrow on this". An
    unset filter therefore means the whole library, which is what `loom list` with no flags shows.

    Attributes:
        type: only artifacts of this type.
        tag: only artifacts carrying this tag in `library.yaml`. Compared exactly. A tag nothing
            carries yields an empty listing rather than an error — tags are free-form, so an
            unrecognised one is indistinguishable from an unused one.
        collection: only members of this collection, by key. A key `library.yaml` does not declare
            raises `CollectionNotFoundError`, because a collection key *is* declared and charter
            §13's fail-loudly posture applies: silently returning nothing would read as an empty
            collection.
        invalid_only: only artifacts with at least one ERROR finding. Ruling R22 — a WARNING never
            makes an artifact invalid, so a V6 warning alone does not put an artifact in this set.
        include_superseded: ruling R8, and it defaults to **true**. Superseded artifacts are part
            of the default listing; they are ranked below their successors, never dropped. The
            field exists so an adapter can offer the narrowing explicitly, not so the default can
            drift.
    """

    type: ArtifactType | None = None
    tag: str | None = None
    collection: str | None = None
    invalid_only: bool = False
    include_superseded: bool = True

    @property
    def is_empty(self) -> bool:
        """True when this filter narrows nothing."""
        return (
            self.type is None
            and self.tag is None
            and self.collection is None
            and not self.invalid_only
            and self.include_superseded
        )


NO_FILTER = ArtifactFilter()
"""The whole library. Not `None`: a use case should not have to null-check its own vocabulary."""


__all__ = ["NO_FILTER", "ArtifactFilter", "SortKey"]
