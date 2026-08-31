"""`RawArtifact` — what a scanner found on disk, as a value.

This is the seam that keeps every validation rule out of `infrastructure/`. The scanner (T-5)
walks the tree, hashes what it reads, records what it refused to read, parses the entry document,
and hands the result here; `assembly.assemble_library` turns it into finished `Artifact` values
carrying their findings. Nothing in this module or in the assembler touches a filesystem, which is
what lets the whole of charter §8 be tested from literals.

**Derived, never carried.** `kind`, the artifact root path and the entry document's path are all
functions of the type registry. A raw value that carried them would be a second source of truth for
the disk layout, and the copy nobody edits is the one that drifts from the scanner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from harness_library.domain.artifact import ArtifactFile, ArtifactKind
from harness_library.domain.identity import ArtifactType, make_artifact_id
from harness_library.domain.registry import TypeSpec, spec_for

_EMPTY_FRONTMATTER: Mapping[str, Any] = MappingProxyType({})


class SkipReason(StrEnum):
    """Why the scanner refused to take a path into the artifact. Closed.

    Every reason produces the same V6 WARNING; the member shapes the message and lets a reader of
    the report tell a symlink apart from an editor's leftovers. Charter §8 names the three that
    matter — swap files, vendor trees, symlinks — and `OTHER` catches the rest so a scanner never
    has to choose between silence and a domain change.
    """

    SYMLINK = "symlink"
    """Ruling R6. Never followed, never hashed, never installed: a link resolving outside the
    artifact root is how a copy writes outside its target."""

    EDITOR_SWAP = "editor-swap"
    """A `.swp`, `~` or similar. Observed destroying real content when a copy took it along."""

    VENDOR_TREE = "vendor-tree"
    """A checked-in dependency tree under an artifact root: `node_modules` or `.venv`."""

    OTHER = "other"
    """Anything else the scanner would not read. `SkippedPath.detail` says what."""


@dataclass(frozen=True, slots=True)
class SkippedPath:
    """One path under the artifact root that the scan left out.

    Skipped paths are **reported, never deleted** (charter §8) and never fed to the content hash
    (charter §7). They arrive here already decided: the assembler turns them into findings and never
    consults a filesystem to discover one.

    Attributes:
        path: relative to the artifact root, like `ArtifactFile.path`.
        reason: which of the closed reasons applied.
        detail: extra context for the message — a symlink's target, say. Never contract.
    """

    path: str
    reason: SkipReason
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("SkippedPath.path must not be empty")


@dataclass(frozen=True, slots=True)
class RawEntry:
    """The entry document, parsed.

    Attributes:
        frontmatter: the parsed frontmatter mapping. Empty when the document has none — never
            `None`, because "no frontmatter" and "an empty frontmatter block" are the same fault
            (V5) and a null check nobody writes is how one of them escapes.
        body: everything after the frontmatter. V3 reads its citations from here.
    """

    frontmatter: Mapping[str, Any] = _EMPTY_FRONTMATTER
    body: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.frontmatter, MappingProxyType):
            object.__setattr__(self, "frontmatter", MappingProxyType(dict(self.frontmatter)))


@dataclass(frozen=True, slots=True)
class RawArtifact:
    """What the scanner found at one artifact root. The assembler's only input about the disk.

    Attributes:
        type: which registry entry this root was found under.
        name: the on-disk name, compared case-sensitively (charter §7).
        files: every file the scan took, already hashed and sized (contract C-1). The scanner has
            read each one once; the assembler re-reads nothing.
        skipped: every path the scan refused, with its reason. One V6 WARNING each.
        entry: the parsed entry document, or `None` when there is none — which is V1.
        updated_at: timezone-aware, derived by the scanner per ruling R5.
        is_dirty: `True` when `updated_at` came from the mtime fallback rather than from git.
    """

    type: ArtifactType
    name: str
    updated_at: datetime
    files: tuple[ArtifactFile, ...] = ()
    skipped: tuple[SkippedPath, ...] = ()
    entry: RawEntry | None = None
    is_dirty: bool = False

    def __post_init__(self) -> None:
        # `make_artifact_id` owns the name rules (non-empty, no separator); calling it here means a
        # malformed name is rejected where the scanner can still say which directory it came from,
        # rather than much later when something asks for the id.
        make_artifact_id(self.type, self.name)
        if self.updated_at.tzinfo is None:
            raise ValueError(
                "RawArtifact.updated_at must be timezone-aware: it becomes Artifact.updated_at, "
                "where mixing a naive value from the mtime path with an aware value from the git "
                "path raises inside sorting, far from the cause"
            )

    @property
    def id(self) -> str:
        """The canonical `<type>/<name>` identity this root will be known by."""
        return make_artifact_id(self.type, self.name)

    @property
    def spec(self) -> TypeSpec:
        """The registry entry for this artifact's type."""
        return spec_for(self.type)

    @property
    def kind(self) -> ArtifactKind:
        """The on-disk layout, from the registry."""
        return self.spec.kind

    @property
    def root_path(self) -> str:
        """The artifact root relative to the library root. This becomes `Artifact.path`."""
        return self.spec.root_path(self.name)

    @property
    def entry_path(self) -> str:
        """The entry document relative to the artifact root."""
        return self.spec.entry_path(self.name)

    @property
    def file_paths(self) -> frozenset[str]:
        """Every path the scan took, for the existence questions V3 asks."""
        return frozenset(file.path for file in self.files)
