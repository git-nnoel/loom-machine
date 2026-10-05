"""Artifact identity — charter §7's `<type>/<name>`."""

from __future__ import annotations

import pytest

from loom.domain.identity import ArtifactType, make_artifact_id, parse_artifact_id


def test_id_is_type_slash_name() -> None:
    assert make_artifact_id(ArtifactType.SKILL, "delivery-lead") == "skill/delivery-lead"
    assert make_artifact_id(ArtifactType.AGENT, "backend-developer") == "agent/backend-developer"


@pytest.mark.parametrize("name", ["", "has/slash"])
def test_unbuildable_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        make_artifact_id(ArtifactType.SKILL, name)


def test_parse_round_trips_every_type() -> None:
    for artifact_type in ArtifactType:
        parsed = parse_artifact_id(make_artifact_id(artifact_type, "some-name"))
        assert parsed == (artifact_type, "some-name")


@pytest.mark.parametrize(
    "value",
    ["", "skill", "skill/", "/name", "widget/name", "skill/a/b"],
    ids=["empty", "no-separator", "no-name", "no-type", "unknown-type", "extra-separator"],
)
def test_unparseable_ids_return_none_rather_than_raising(value: str) -> None:
    """`library.yaml` is user-authored: a bad id is a V7 finding to report, not a crash."""
    assert parse_artifact_id(value) is None


def test_names_are_case_sensitive() -> None:
    """Charter §7 — two names differing only by case are two artifacts, not one."""
    assert make_artifact_id(ArtifactType.SKILL, "Deploy") != make_artifact_id(
        ArtifactType.SKILL, "deploy"
    )
    assert parse_artifact_id("skill/Deploy") == (ArtifactType.SKILL, "Deploy")
