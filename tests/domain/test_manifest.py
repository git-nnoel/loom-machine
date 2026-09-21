"""Contract C-11's entity — what a manifest may and may not record.

Charter §10: `domain/` is tested with zero I/O. What this layer is blind to is stated once, here:
it knows nothing about where a manifest lives, how it is serialised, or whether an absent one
differs from an empty one. All three are `infrastructure/manifest_store.py`'s, and a test at this
level could not observe any of them because no file is ever opened.

What it *can* observe is the set of manifests that must not exist: one keyed to no target, one
timestamped without an offset, one recording an artifact twice, one recording a file twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from harness_library.domain.artifact import ArtifactFile
from harness_library.domain.manifest import Manifest, ManifestArtifact, ManifestStore

INSTALLED_AT = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)

SKILL_MD = ArtifactFile(path="SKILL.md", sha256="a" * 64, size=120, is_text=True)
DIAGRAM_PNG = ArtifactFile(path="references/diagram.png", sha256="b" * 64, size=4096, is_text=False)


def a_manifest(**overrides: object) -> Manifest:
    """A valid manifest, with one field replaced. Keeps each test's subject on one line."""
    fields: dict[str, object] = {
        "target_path": "/home/someone/.claude",
        "installed_at": INSTALLED_AT,
        "library_git_sha": "c" * 40,
        "backup_id": "2026-09-21T14-29-00Z",
        "artifacts": (
            ManifestArtifact(
                artifact_id="skill/delivery-lead",
                content_hash="d" * 64,
                files=(SKILL_MD, DIAGRAM_PNG),
            ),
        ),
    }
    fields.update(overrides)
    return Manifest(**fields)  # type: ignore[arg-type]


# Behaviour 1 — a manifest holds what it was given, unchanged.


def test_a_manifest_holds_every_field_it_was_given() -> None:
    manifest = a_manifest()

    assert manifest.target_path == "/home/someone/.claude"
    assert manifest.installed_at == INSTALLED_AT
    assert manifest.library_git_sha == "c" * 40
    assert manifest.backup_id == "2026-09-21T14-29-00Z"
    assert manifest.artifacts[0].artifact_id == "skill/delivery-lead"
    assert manifest.artifacts[0].content_hash == "d" * 64
    assert manifest.artifacts[0].files == (SKILL_MD, DIAGRAM_PNG)


def test_the_per_file_digests_are_c1s_artifact_file() -> None:
    """C-11 reuses C-1 rather than restating it. A parallel type would drift on the first field
    either one gained, and a binary file is the case that would find it out first."""
    binary = a_manifest().artifacts[0].files[1]

    assert isinstance(binary, ArtifactFile)
    assert binary.is_text is False
    assert binary.size == 4096


def test_no_artifacts_is_a_value_and_not_a_fault() -> None:
    """A target installed into and then uninstalled has a manifest recording nothing. That is a
    different fact from having no manifest, which this layer cannot even represent."""
    assert a_manifest(artifacts=()).artifacts == ()


def test_both_nullable_fields_accept_none() -> None:
    """`None` is an honest answer to "which commit" for a library that is not a git work tree, and
    to "which backup" for a first install that overwrote nothing."""
    manifest = a_manifest(library_git_sha=None, backup_id=None)

    assert manifest.library_git_sha is None
    assert manifest.backup_id is None


def test_a_manifest_is_frozen() -> None:
    """The record of what was installed is not edited in place by whoever happens to hold it."""
    with pytest.raises(AttributeError):
        a_manifest().target_path = "/somewhere/else"  # type: ignore[misc]


# Behaviour 2 — the manifests that must not exist.


def test_an_empty_target_path_is_refused() -> None:
    """The store keys the file by this path; an empty one keys every target to the same file."""
    with pytest.raises(ValueError, match="target_path"):
        a_manifest(target_path="")


def test_a_naive_installed_at_is_refused() -> None:
    """The same rule `Artifact.updated_at` carries, for the same reason: this value is written to
    disk and read back later, and a naive instant raises inside a comparison far from its cause."""
    with pytest.raises(ValueError, match="timezone-aware"):
        a_manifest(installed_at=datetime(2026, 9, 21, 14, 30))


def test_an_aware_installed_at_in_a_non_utc_zone_is_accepted() -> None:
    """Positive control for the assertion above: "aware" is the rule, not "UTC"."""
    installed_at = datetime(2026, 9, 21, 11, 30, tzinfo=timezone(timedelta(hours=-3)))

    assert a_manifest(installed_at=installed_at).installed_at == installed_at


def test_one_artifact_recorded_twice_is_refused() -> None:
    """Uninstall and rollback both act on "the files this manifest names for this artifact", and
    two records give that question two answers."""
    twice = (
        ManifestArtifact(artifact_id="skill/x", content_hash="1" * 64, files=(SKILL_MD,)),
        ManifestArtifact(artifact_id="skill/x", content_hash="2" * 64, files=()),
    )

    with pytest.raises(ValueError, match="skill/x"):
        a_manifest(artifacts=twice)


def test_two_different_artifacts_are_not_a_duplicate() -> None:
    """Positive control for the assertion above: the guard is about the id, not about the count."""
    two = (
        ManifestArtifact(artifact_id="skill/x", content_hash="1" * 64, files=(SKILL_MD,)),
        ManifestArtifact(artifact_id="agent/x", content_hash="2" * 64, files=(SKILL_MD,)),
    )

    assert len(a_manifest(artifacts=two).artifacts) == 2


def test_one_file_recorded_twice_in_an_artifact_is_refused() -> None:
    """Two digests for one path give the verdict rule two answers for that path."""
    other = ArtifactFile(path="SKILL.md", sha256="e" * 64, size=1, is_text=True)

    with pytest.raises(ValueError, match=r"SKILL\.md"):
        ManifestArtifact(artifact_id="skill/x", content_hash="f" * 64, files=(SKILL_MD, other))


def test_an_empty_artifact_id_is_refused() -> None:
    with pytest.raises(ValueError, match="artifact_id"):
        ManifestArtifact(artifact_id="", content_hash="f" * 64)


def test_an_empty_content_hash_is_refused() -> None:
    """An empty digest compares unequal to every real one, so it would report an untouched
    artifact as changed on the very next run."""
    with pytest.raises(ValueError, match="content_hash"):
        ManifestArtifact(artifact_id="skill/x", content_hash="")


# -- Ruling R74, amending C-11: the id must be a <type>/<name> identity ---------------------------
#
# Added by T-16. The three tests above are untouched; an empty id is still refused by its own
# rule, and these are about an id that is present and unusable.


@pytest.mark.parametrize(
    "artifact_id",
    ["nonsense", "skill", "skill/", "/delivery-lead", "widget/thing", "skill/a/b"],
)
def test_an_artifact_id_that_is_not_an_identity_is_refused(artifact_id: str) -> None:
    """**Ruling R74.** A manifest is machine-written but lives as plain JSON in a user's state
    directory, and a hand-edited one can carry anything.

    An id that does not parse has no artifact root, so the files it names cannot be located inside
    the target: nothing prunes them, nothing uninstalls them, and the next scan reports every one
    of them `FOREIGN` — orphaned by the record whose whole job is to make them removable.
    """
    with pytest.raises(ValueError, match="not a <type>/<name> identity"):
        ManifestArtifact(artifact_id=artifact_id, content_hash="f" * 64)


def test_a_well_formed_identity_is_accepted_for_every_type() -> None:
    """The positive control. Without it, "rejects a bad id" and "rejects every id" look alike."""
    for artifact_id in ("skill/delivery-lead", "agent/phase-reviewer"):
        assert ManifestArtifact(artifact_id=artifact_id, content_hash="f" * 64).artifact_id == (
            artifact_id
        )


def test_the_store_protocol_is_satisfied_structurally() -> None:
    """`ManifestStore` is implemented, never inherited — the shape ruling R14 settled for C-4."""

    class Store:
        def write(self, manifest: Manifest) -> None:
            return None

    assert isinstance(Store(), ManifestStore)


def test_an_object_that_cannot_write_is_not_a_manifest_store() -> None:
    """The positive control for the check above."""

    class NotAStore:
        def read(self) -> None:
            return None

    assert not isinstance(NotAStore(), ManifestStore)
