"""Contracts C-1 and C-2 — the records, and what `is_valid` means."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from loom.domain.artifact import Artifact, ArtifactFile, ArtifactKind
from loom.domain.hashing import content_hash
from loom.domain.identity import ArtifactType
from loom.domain.validation import ValidationCode, ValidationFinding

SCANNED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

V1_ERROR = ValidationFinding.for_code(ValidationCode.V1, "no SKILL.md under the artifact root")
V6_WARNING = ValidationFinding.for_code(ValidationCode.V6, "stray swap file", "SKILL.md.swp")


def make_artifact(
    *,
    findings: tuple[ValidationFinding, ...] = (),
    files: tuple[ArtifactFile, ...] = (),
    **overrides: object,
) -> Artifact:
    defaults: dict[str, object] = {
        "type": ArtifactType.SKILL,
        "name": "delivery-lead",
        "kind": ArtifactKind.DIRECTORY,
        "path": "skills/delivery-lead",
        "content_hash": content_hash([("SKILL.md", b"body")]),
        "updated_at": SCANNED_AT,
    }
    defaults.update(overrides)
    return Artifact(findings=findings, files=files, **defaults)  # type: ignore[arg-type]


def test_id_is_derived_from_type_and_name() -> None:
    assert make_artifact().id == "skill/delivery-lead"


def test_a_clean_artifact_is_valid() -> None:
    assert make_artifact().is_valid is True


def test_warning_finding_does_not_make_an_artifact_invalid() -> None:
    """Charter §8: `is_valid` means **no ERROR finding**, not 'no findings'.

    A stray editor swap file must be reported without making the artifact refuse to install — that
    is the entire reason `Severity` exists. The ERROR case in the same test is the positive
    control: it proves this assertion is capable of failing, so a green result here is evidence
    rather than an artifact of a finding list that never arrived.
    """
    warned = make_artifact(findings=(V6_WARNING,))
    assert warned.findings, "positive control: the finding list must actually be populated"
    assert warned.is_valid is True

    errored = make_artifact(findings=(V1_ERROR,))
    assert errored.is_valid is False


def test_a_warning_alongside_an_error_is_still_invalid() -> None:
    assert make_artifact(findings=(V6_WARNING, V1_ERROR)).is_valid is False


def test_errors_and_warnings_partition_the_findings() -> None:
    artifact = make_artifact(findings=(V6_WARNING, V1_ERROR))
    assert artifact.errors == (V1_ERROR,)
    assert artifact.warnings == (V6_WARNING,)
    assert len(artifact.errors) + len(artifact.warnings) == len(artifact.findings)


def test_an_invalid_artifact_is_still_representable() -> None:
    """A skill directory with no `SKILL.md` is an artifact carrying V1, not an exception. Making
    it unrepresentable here is how the superseded plan crashed on `loom show`."""
    broken = make_artifact(files=(), findings=(V1_ERROR,))
    assert broken.id == "skill/delivery-lead"
    assert broken.is_valid is False
    assert broken.frontmatter == {}
    assert broken.description is None


def test_frontmatter_defaults_to_an_empty_read_only_mapping() -> None:
    artifact = make_artifact()
    assert artifact.frontmatter == {}
    with pytest.raises(TypeError):
        artifact.frontmatter["name"] = "x"  # type: ignore[index]


def test_frontmatter_is_frozen_against_the_caller_s_dict() -> None:
    """A frozen dataclass freezes the reference, not the mapping behind it."""
    supplied = {"name": "delivery-lead"}
    artifact = make_artifact(frontmatter=supplied)
    supplied["name"] = "mutated"
    assert artifact.frontmatter["name"] == "delivery-lead"
    with pytest.raises(TypeError):
        artifact.frontmatter["name"] = "x"  # type: ignore[index]


def test_the_artifact_itself_is_frozen() -> None:
    with pytest.raises(AttributeError):
        make_artifact().name = "other"  # type: ignore[misc]


def test_updated_at_must_be_timezone_aware() -> None:
    """R5 derives it from git for a clean artifact and from mtime for a dirty one; a naive value
    from one path would raise inside T-6's sort, far from the cause."""
    with pytest.raises(ValueError, match="timezone-aware"):
        make_artifact(updated_at=datetime(2026, 8, 31, 12, 0))


def test_is_dirty_and_updated_at_express_both_r5_derivations() -> None:
    from_git = make_artifact(updated_at=SCANNED_AT, is_dirty=False)
    from_mtime = make_artifact(updated_at=SCANNED_AT, is_dirty=True)
    assert from_git.is_dirty is False
    assert from_mtime.is_dirty is True
    assert from_git.updated_at == from_mtime.updated_at


def test_artifact_file_carries_a_per_path_digest() -> None:
    """C-1. Initiative 02 judges install per path; without this it rebuilds the scanner."""
    file = ArtifactFile(path="assets/diagram.png", sha256="0" * 64, size=188416, is_text=False)
    assert file.path == "assets/diagram.png"
    assert file.is_text is False
    with pytest.raises(AttributeError):
        file.size = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("path", "size"), [("", 1), ("SKILL.md", -1)], ids=["empty-path", "negative-size"]
)
def test_unrepresentable_files_are_rejected(path: str, size: int) -> None:
    with pytest.raises(ValueError):
        ArtifactFile(path=path, sha256="0" * 64, size=size, is_text=True)
