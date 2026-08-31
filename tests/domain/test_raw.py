"""`RawArtifact` — the scanner's output value, and the invariants it refuses to carry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from harness_library.domain.artifact import ArtifactKind
from harness_library.domain.identity import ArtifactType
from harness_library.domain.raw import RawArtifact, RawEntry, SkippedPath, SkipReason

SCANNED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def test_a_skill_derives_its_layout_from_the_registry() -> None:
    """`kind`, the root path and the entry path are never carried on the raw value.

    A scanner that supplied them would be a second source of truth for the disk layout, and the
    copy nobody edits is the one that drifts.
    """
    raw = RawArtifact(type=ArtifactType.SKILL, name="delivery-lead", updated_at=SCANNED_AT)

    assert raw.id == "skill/delivery-lead"
    assert raw.kind is ArtifactKind.DIRECTORY
    assert raw.root_path == "skills/delivery-lead"
    assert raw.entry_path == "SKILL.md"


def test_an_agent_is_its_own_entry_document() -> None:
    raw = RawArtifact(type=ArtifactType.AGENT, name="reviewer", updated_at=SCANNED_AT)

    assert raw.kind is ArtifactKind.FILE
    assert raw.root_path == "agents/reviewer.md"
    assert raw.entry_path == "reviewer.md"


def test_a_naive_timestamp_is_refused_at_the_seam() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RawArtifact(
            type=ArtifactType.SKILL, name="delivery-lead", updated_at=datetime(2026, 8, 31, 12, 0)
        )


@pytest.mark.parametrize("name", ["", "skills/nested"])
def test_a_name_that_cannot_form_an_id_is_refused_at_the_seam(name: str) -> None:
    """Rejected where the scanner can still say which directory it came from, rather than much
    later when something first asks for the id."""
    with pytest.raises(ValueError):
        RawArtifact(type=ArtifactType.SKILL, name=name, updated_at=SCANNED_AT)


def test_an_entry_with_no_frontmatter_is_an_empty_mapping_not_none() -> None:
    entry = RawEntry(body="prose only")

    assert entry.frontmatter == {}


def test_entry_frontmatter_is_read_only() -> None:
    entry = RawEntry(frontmatter={"name": "delivery-lead"})

    with pytest.raises(TypeError):
        entry.frontmatter["name"] = "something-else"  # type: ignore[index]


def test_a_skipped_path_must_name_a_path() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SkippedPath(path="", reason=SkipReason.SYMLINK)
