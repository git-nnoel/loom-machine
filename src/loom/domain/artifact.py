"""The two records every layer and every later initiative consumes: contracts C-1 and C-2.

Frozen dataclasses, not Pydantic — charter §3. This layer imports nothing from the project outside
`domain/` and nothing from a framework, and Pydantic's validation belongs at the adapter boundary
where untrusted input actually arrives.

Nothing here performs I/O. `content_hash`, `updated_at` and `is_dirty` are *typed* here and
*derived* by the scanner (T-5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from loom.domain.identity import ArtifactType, make_artifact_id
from loom.domain.validation import Severity, ValidationFinding

_EMPTY_FRONTMATTER: Mapping[str, Any] = MappingProxyType({})


class ArtifactKind(StrEnum):
    """How an artifact is laid out on disk. Closed."""

    DIRECTORY = "directory"
    """A directory with an entry document inside it — a skill and its `references/`."""

    FILE = "file"
    """A single markdown document that is the whole artifact — an agent."""


@dataclass(frozen=True, slots=True)
class ArtifactFile:
    """Contract C-1. One file belonging to an artifact.

    The per-file digest is not a convenience: initiative 02 judges install **per path**, and without
    it that initiative rebuilds the scanner on a second code path which then drifts from this one.

    Attributes:
        path: relative to the artifact root. For a `FILE`-kind artifact the single entry's path is
            its own basename.
        sha256: `hashing.hash_bytes` of the file's contents, lowercase hex.
        size: the file's size in bytes.
        is_text: whether the file is searchable and diffable. Binary files are stored, hashed,
            exported and installed — never searched (charter §7).
    """

    path: str
    sha256: str
    size: int
    is_text: bool

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("ArtifactFile.path must not be empty")
        if self.size < 0:
            raise ValueError(f"ArtifactFile.size must not be negative: {self.size}")


@dataclass(frozen=True, slots=True)
class Artifact:
    """Contract C-2. One skill or agent, as scanned.

    An artifact exists whether or not it is valid: a skill directory with no `SKILL.md` is still an
    artifact, carrying its V1 finding. Reporting it is the reason this product exists, so nothing in
    this type may make an invalid artifact unrepresentable.

    Attributes:
        type: skill or agent.
        name: the on-disk name, compared case-sensitively (charter §7).
        kind: the disk layout, from the type registry.
        path: the artifact root, relative to the library root — `skills/<name>`, or
            `agents/<name>.md` for a `FILE`-kind artifact.
        description: the frontmatter `description`, or `None` when absent or unreadable.
        frontmatter: the parsed frontmatter mapping, wrapped read-only. Empty when the entry
            document is missing or has no frontmatter — never `None`.
        content_hash: `hashing.content_hash` over this artifact's files.
        updated_at: timezone-aware. Ruling R5: the last git commit touching the artifact's paths,
            falling back to the maximum mtime of its files when the library is not a repository or
            the artifact has uncommitted changes.
        is_dirty: `True` when `updated_at` came from the mtime fallback rather than from git.
        superseded_by: the id of the artifact that replaces this one, or `None`. Drives V3's
            exemption and R8's ranking.
        tags: from `library.yaml`; empty when the library declares none.
        files: every file under the artifact root that was not skipped, in the scanner's order.
        findings: everything validation reported about this artifact.
    """

    type: ArtifactType
    name: str
    kind: ArtifactKind
    path: str
    content_hash: str
    updated_at: datetime
    is_dirty: bool = False
    description: str | None = None
    frontmatter: Mapping[str, Any] = _EMPTY_FRONTMATTER
    superseded_by: str | None = None
    tags: tuple[str, ...] = ()
    files: tuple[ArtifactFile, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError(
                "Artifact.updated_at must be timezone-aware: R5 derives it from git or from mtime, "
                "and mixing a naive value from one path with an aware value from the other raises "
                "inside sorting, far from the cause"
            )
        if not isinstance(self.frontmatter, MappingProxyType):
            object.__setattr__(self, "frontmatter", MappingProxyType(dict(self.frontmatter)))

    @property
    def id(self) -> str:
        """The canonical `<type>/<name>` identity."""
        return make_artifact_id(self.type, self.name)

    @property
    def is_valid(self) -> bool:
        """`True` when no finding has severity ERROR.

        A WARNING never makes an artifact invalid. Charter §8: an editor swap file under an
        artifact root (V6) must be *reported* without making the artifact refuse to install.
        """
        return not any(finding.severity is Severity.ERROR for finding in self.findings)

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        """The ERROR findings — the ones `is_valid` is decided by."""
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationFinding, ...]:
        """The WARNING findings — reported, never blocking."""
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)
