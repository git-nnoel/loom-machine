"""The type registry — the single place a new artifact type is added."""

from __future__ import annotations

import pytest

from loom.domain.artifact import ArtifactKind
from loom.domain.identity import ArtifactType
from loom.domain.registry import (
    ARTIFACT_DIRECTORIES,
    ARTIFACT_TYPE_SPECS,
    TypeSpec,
    spec_for,
    spec_for_directory,
    target_path_of,
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


# -- Ruling R73: the target join, beside `root_path` and `entry_path` -----------------------------
#
# Moved here from `application/read/drift.py` by T-16, with the three tests that exercised it.
# All three answer "where does this live", all three read one `TypeSpec`, and a second
# implementation of any of them would have install writing where uninstall does not look.


def test_a_directory_artifacts_file_joins_onto_its_artifact_root() -> None:
    """`SKILL.md` belongs to the artifact root; the target holds it under that root."""
    assert (
        target_path_of(ArtifactType.SKILL, "delivery-lead", "SKILL.md")
        == "skills/delivery-lead/SKILL.md"
    )
    assert (
        target_path_of(ArtifactType.SKILL, "delivery-lead", "references/diagram.png")
        == "skills/delivery-lead/references/diagram.png"
    )


def test_a_file_artifact_is_its_own_root_and_is_not_joined_onto_itself() -> None:
    """The case the directory formula gets wrong. An agent's root path *is* its entry document,
    so joining the file onto the root would give `agents/scribe.md/scribe.md`."""
    assert target_path_of(ArtifactType.AGENT, "scribe", "scribe.md") == "agents/scribe.md"


@pytest.mark.parametrize("artifact_type", list(ARTIFACT_TYPE_SPECS), ids=lambda t: t.value)
def test_the_join_of_an_entry_document_agrees_with_the_type_registry(
    artifact_type: ArtifactType,
) -> None:
    """Over **every** registered type, so a third type cannot be added without meeting this.

    The registry already answers "where is this artifact" (`root_path`) and "where is its entry
    document inside it" (`entry_path`). The join must land exactly where composing those two
    lands, or install writes to one place and uninstall looks in another.
    """
    spec = spec_for(artifact_type)
    joined = target_path_of(artifact_type, "example", spec.entry_path("example"))

    if spec.kind is ArtifactKind.DIRECTORY:
        assert joined == f"{spec.root_path('example')}/{spec.entry_path('example')}"
    else:
        assert joined == spec.root_path("example")
