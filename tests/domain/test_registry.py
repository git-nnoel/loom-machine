"""The type registry — the single place a new artifact type is added."""

from __future__ import annotations

import pytest

from harness_library.domain.artifact import ArtifactKind
from harness_library.domain.identity import ArtifactType
from harness_library.domain.registry import (
    ARTIFACT_DIRECTORIES,
    ARTIFACT_TYPE_SPECS,
    TypeSpec,
    spec_for,
    spec_for_directory,
)


def test_every_artifact_type_has_a_spec() -> None:
    """The half of 'add a type' that is easy to forget. A member with no spec fails here rather
    than raising a KeyError inside the scanner."""
    assert set(ARTIFACT_TYPE_SPECS) == set(ArtifactType)
    for artifact_type in ArtifactType:
        assert spec_for(artifact_type).type is artifact_type


def test_directories_are_distinct_and_derived() -> None:
    assert sorted(ARTIFACT_DIRECTORIES) == sorted(set(ARTIFACT_DIRECTORIES))
    assert set(ARTIFACT_DIRECTORIES) == {spec.directory for spec in ARTIFACT_TYPE_SPECS.values()}


def test_skill_is_a_directory_with_skill_md_inside() -> None:
    spec = spec_for(ArtifactType.SKILL)
    assert spec.kind is ArtifactKind.DIRECTORY
    assert spec.root_path("delivery-lead") == "skills/delivery-lead"
    assert spec.entry_path("delivery-lead") == "SKILL.md"


def test_agent_is_a_single_markdown_file() -> None:
    spec = spec_for(ArtifactType.AGENT)
    assert spec.kind is ArtifactKind.FILE
    assert spec.root_path("backend-developer") == "agents/backend-developer.md"
    assert spec.entry_path("backend-developer") == "backend-developer.md"


def test_lookup_by_directory_covers_every_type_and_declines_others() -> None:
    for spec in ARTIFACT_TYPE_SPECS.values():
        assert spec_for_directory(spec.directory) is spec
    assert spec_for_directory("node_modules") is None


def test_required_frontmatter_keys_are_declared_for_every_type() -> None:
    """V5's key list lives here, not in the rule that fires it."""
    for spec in ARTIFACT_TYPE_SPECS.values():
        assert "name" in spec.required_frontmatter_keys
        assert "description" in spec.required_frontmatter_keys


def test_a_spec_whose_kind_and_entry_filename_disagree_is_rejected() -> None:
    with pytest.raises(ValueError):
        TypeSpec(
            type=ArtifactType.SKILL,
            kind=ArtifactKind.DIRECTORY,
            directory="skills",
            entry_filename=None,
            required_frontmatter_keys=(),
        )
    with pytest.raises(ValueError):
        TypeSpec(
            type=ArtifactType.AGENT,
            kind=ArtifactKind.FILE,
            directory="agents",
            entry_filename="AGENT.md",
            required_frontmatter_keys=(),
        )


def test_the_registry_cannot_be_mutated() -> None:
    with pytest.raises(TypeError):
        ARTIFACT_TYPE_SPECS[ArtifactType.SKILL] = spec_for(ArtifactType.AGENT)  # type: ignore[index]
