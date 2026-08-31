"""The `library.yaml` domain types.

Here rather than in the reader (DEC-8): T-3 implements V7, which validates that every `library.yaml`
entry resolves to an artifact, so it consumes these types. Keeping them in the reader's task would
force the two to run in sequence over a shared type.

These are the *shape* of the parsed document, not the parser. The reader (T-4, infrastructure) does
the shape validation and the line-numbered failures; nothing here touches a file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_EMPTY_ARTIFACTS: Mapping[str, ArtifactMetadata] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    """What `library.yaml` declares about one artifact, keyed by its `<type>/<name>` id.

    Attributes:
        tags: free-form labels, in declaration order, used by `hl list --tag`.
        superseded_by: the id of the artifact that replaces this one, or `None`. V4 checks that it
            resolves; V3's missing-reference rule is exempt while it is set, because a redirect stub
            cites its successor's paths as prose.
    """

    tags: tuple[str, ...] = ()
    superseded_by: str | None = None


EMPTY_ARTIFACT_METADATA = ArtifactMetadata()
"""The metadata of an artifact the library declares nothing about. Not `None`: an undeclared
artifact has no tags and no successor, which is a value, not an absence."""


@dataclass(frozen=True, slots=True)
class Collection:
    """A named group of artifacts declared in `library.yaml`.

    Attributes:
        key: the identifier `hl list --collection` takes.
        title: a human name, or `None` when the document declares none.
        description: prose, or `None`.
        members: artifact ids, in declaration order. A member resolving to nothing is a V7 finding
            — the collection is still returned, carrying it.
    """

    key: str
    members: tuple[str, ...] = ()
    title: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Collection.key must not be empty")


@dataclass(frozen=True, slots=True)
class LibraryMetadata:
    """The whole of `library.yaml`, parsed.

    A library with no `library.yaml` is represented by `LibraryMetadata.empty()`, not by `None`:
    tags, collections and supersession then read as empty, which is what they are, and no caller
    needs a null check that one of them will forget.
    """

    artifacts: Mapping[str, ArtifactMetadata] = _EMPTY_ARTIFACTS
    collections: tuple[Collection, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, MappingProxyType):
            object.__setattr__(self, "artifacts", MappingProxyType(dict(self.artifacts)))

    @classmethod
    def empty(cls) -> LibraryMetadata:
        """The metadata of a library that declares none."""
        return cls()

    def for_artifact(self, artifact_id: str) -> ArtifactMetadata:
        """What the library declares about `artifact_id`, or the empty declaration."""
        return self.artifacts.get(artifact_id, EMPTY_ARTIFACT_METADATA)
