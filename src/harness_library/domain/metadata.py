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
class DuplicateKey:
    """A key `library.yaml` declares more than once. One V9 ERROR each.

    Recorded rather than decided: the reader is the only thing that sees the composed node tree, so
    it is the only thing that *can* observe a duplicate — `YamlMapping.pairs` is a list, and both
    entries survive there where a dict would already have collapsed them. What the observation
    *means* is charter §8's business, so the wording and the severity belong to the assembler. This
    is exactly `SkippedPath`'s shape: the scanner records, the assembler judges.

    Attributes:
        key: the key text that appears twice.
        context: the ancestor keys the duplicate sits under, outermost first — `()` at the top
            level, `("artifacts",)` for a repeated artifact id, `("artifacts", "skill/foo")` for a
            `tags:` written twice inside one entry. Present so a report can say *which* mapping,
            since the same id may legitimately appear under `artifacts` and inside a collection.
        line: 1-based line of the later declaration — the one whose value wins.
        first_line: 1-based line of the earlier declaration — the one whose value is discarded.
            Both are carried because a diagnosis naming one location leaves the reader hunting for
            the other, and the pair is the whole fault.
    """

    key: str
    line: int
    first_line: int
    context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.line < 1 or self.first_line < 1:
            raise ValueError("DuplicateKey line numbers are 1-based and must be positive")

    @property
    def within(self) -> str:
        """Where the duplicate sits, as prose for a report."""
        if not self.context:
            return "the document"
        return " -> ".join(repr(name) for name in self.context)


@dataclass(frozen=True, slots=True)
class LibraryMetadata:
    """The whole of `library.yaml`, parsed.

    A library with no `library.yaml` is represented by `LibraryMetadata.empty()`, not by `None`:
    tags, collections and supersession then read as empty, which is what they are, and no caller
    needs a null check that one of them will forget.

    `duplicate_keys` is the one field that is not "what the document declares" but "what is wrong
    with how it declares it". It is here rather than raised because charter §8 makes V9 an ERROR
    *finding*, and a fault that can never reach a report can never make `is_valid` false. For a
    duplicated key the surviving value is the last one written, unchanged from before — neither
    block can be preferred on merit, so the answer is the ERROR, not a cleverer merge.
    """

    artifacts: Mapping[str, ArtifactMetadata] = _EMPTY_ARTIFACTS
    collections: tuple[Collection, ...] = ()
    duplicate_keys: tuple[DuplicateKey, ...] = ()

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
