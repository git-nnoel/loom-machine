"""The artifact type registry — the single place a new artifact type is added.

Everything that differs between a skill and an agent is a column of `TypeSpec`: the directory it
lives under, whether it is a directory or a single file, where its entry document is, and which
frontmatter keys are required. A scanner, a validator or a CLI that reimplements one of those
answers is a second source of truth, and the one nobody edits is the one that drifts.

Adding a type is: add the member to `ArtifactType`, add its `TypeSpec` here. A member without a spec
fails `tests/domain/test_registry.py`, so the second half cannot be forgotten.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from harness_library.domain.artifact import ArtifactKind
from harness_library.domain.identity import ArtifactType

ENTRY_SUFFIX = ".md"


@dataclass(frozen=True, slots=True)
class TypeSpec:
    """Everything that varies between artifact types.

    Attributes:
        type: the type this spec describes.
        kind: its on-disk layout.
        directory: the directory under the library root that holds artifacts of this type.
        entry_filename: the entry document's name inside a `DIRECTORY`-kind artifact root, or
            `None` for a `FILE`-kind artifact, whose entry is the artifact itself.
        required_frontmatter_keys: keys whose absence — or emptiness — is a V5 finding. The rule
            that fires V5 belongs to the assembler; the list of keys belongs here.
    """

    type: ArtifactType
    kind: ArtifactKind
    directory: str
    entry_filename: str | None
    required_frontmatter_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        expects_entry_filename = self.kind is ArtifactKind.DIRECTORY
        if expects_entry_filename != (self.entry_filename is not None):
            raise ValueError(
                f"{self.type.value}: a {self.kind.value}-kind artifact "
                f"{'requires' if expects_entry_filename else 'must not declare'} an entry filename"
            )

    def root_path(self, name: str) -> str:
        """The artifact root relative to the library root. This is `Artifact.path`."""
        if self.kind is ArtifactKind.DIRECTORY:
            return f"{self.directory}/{name}"
        return f"{self.directory}/{name}{ENTRY_SUFFIX}"

    def entry_path(self, name: str) -> str:
        """The entry document relative to the **artifact root**. This is `ArtifactFile.path`."""
        if self.entry_filename is not None:
            return self.entry_filename
        return f"{name}{ENTRY_SUFFIX}"


ARTIFACT_TYPE_SPECS: Mapping[ArtifactType, TypeSpec] = MappingProxyType(
    {
        ArtifactType.SKILL: TypeSpec(
            type=ArtifactType.SKILL,
            kind=ArtifactKind.DIRECTORY,
            directory="skills",
            entry_filename="SKILL.md",
            required_frontmatter_keys=("name", "description"),
        ),
        ArtifactType.AGENT: TypeSpec(
            type=ArtifactType.AGENT,
            kind=ArtifactKind.FILE,
            directory="agents",
            entry_filename=None,
            required_frontmatter_keys=("name", "description"),
        ),
    }
)
"""The registry. Keyed by type; every `ArtifactType` member has exactly one entry."""


def spec_for(artifact_type: ArtifactType) -> TypeSpec:
    """The spec for a type. Total over `ArtifactType`, guarded by a test over the enum."""
    return ARTIFACT_TYPE_SPECS[artifact_type]


def spec_for_directory(directory: str) -> TypeSpec | None:
    """The spec whose artifacts live under `directory`, or `None` if none does.

    `None` rather than a raise: the scanner walks a real library root and must pass over
    directories it does not own without treating them as an error.
    """
    for spec in ARTIFACT_TYPE_SPECS.values():
        if spec.directory == directory:
            return spec
    return None


ARTIFACT_DIRECTORIES: tuple[str, ...] = tuple(
    spec.directory for spec in ARTIFACT_TYPE_SPECS.values()
)
"""Every directory a library may hold artifacts in, derived — never a second literal list."""


def target_path_of(artifact_type: ArtifactType, name: str, file_path: str) -> str:
    """Where one of an artifact's files lands inside an install target. **The join.**

    The third answer in the same family as `TypeSpec.root_path` and `TypeSpec.entry_path`, and
    here for that reason (**ruling R73**): all three say where something lives, all three read the
    same spec, and a second implementation of any of them would disagree exactly where it matters
    — install writing to one place and uninstall looking in another. It arrived in
    `application/read/drift.py` only because this module was outside T-15's scope.

    `file_path` is relative to the artifact root, as C-1 defines it and as both the scanner and the
    manifest record it. The result is relative to the **target** root, which is `PlanEntry.path`
    and `TargetFile.path`, because install mirrors the library's layout into the target.

    The two kinds differ and the difference is easy to get wrong:

    * a `DIRECTORY` artifact has a root *containing* its files, so the join is `root/file`;
    * a `FILE` artifact **is** its entry document. Its root path is `agents/<name>.md` and its one
      file's path is `<name>.md`, so joining onto the root would give `agents/scribe.md/scribe.md`.
      The prefix is the type's directory, and the result is exactly `root_path(name)` again.

    A function rather than a third `TypeSpec` method: it takes the type and resolves the spec
    itself, the way `spec_for` does, and the ruling moved it rather than renaming it.
    """
    spec = spec_for(artifact_type)
    if spec.kind is ArtifactKind.DIRECTORY:
        return f"{spec.root_path(name)}/{file_path}"
    return f"{spec.directory}/{file_path}"
