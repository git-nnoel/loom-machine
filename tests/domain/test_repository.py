"""Contract C-4 — the repository protocol.

Declared in T-2 with the rest of the vocabulary so T-5 implements a frozen signature. This test is
structural on purpose: nothing implements the protocol yet, so what is checkable now is that a
hand-written fake of the documented surface satisfies it, and that a partial one does not.
"""

from __future__ import annotations

from datetime import UTC, datetime

from harness_library.domain.artifact import Artifact, ArtifactKind
from harness_library.domain.identity import ArtifactType
from harness_library.domain.metadata import Collection
from harness_library.domain.raw import SymlinkedRoot
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.validation import ValidationFinding


class FakeRepository:
    """The full surface, as the application layer's fakes will be written.

    **Seven members since ruling R97**, which put `symlinked_roots()` into C-4 — the journey
    `library_findings()` made under R23, for the same reason and with the same cost: a member
    added to a protocol is a member every hand-written implementation of it has to gain (L24).
    """

    def __init__(self, artifacts: list[Artifact], collections: list[Collection]) -> None:
        self._artifacts = artifacts
        self._collections = collections

    def list_all(self) -> list[Artifact]:
        return list(self._artifacts)

    def get(self, artifact_id: str) -> Artifact | None:
        return next((a for a in self._artifacts if a.id == artifact_id), None)

    def read_bytes(self, artifact_id: str, path: str) -> bytes:
        return b""

    def read_text(self, artifact_id: str, path: str) -> str:
        return ""

    def list_collections(self) -> list[Collection]:
        return list(self._collections)

    def library_findings(self) -> list[ValidationFinding]:
        return []

    def symlinked_roots(self) -> tuple[SymlinkedRoot, ...]:
        return ()


class ReadTextOnlyRepository:
    """The surface C-4 explicitly refuses: text without bytes forecloses binary install and zip
    export in initiatives 02 and 03."""

    def list_all(self) -> list[Artifact]:
        return []

    def get(self, artifact_id: str) -> Artifact | None:
        return None

    def read_text(self, artifact_id: str, path: str) -> str:
        return ""

    def list_collections(self) -> list[Collection]:
        return []


def _artifact() -> Artifact:
    return Artifact(
        type=ArtifactType.SKILL,
        name="delivery-lead",
        kind=ArtifactKind.DIRECTORY,
        path="skills/delivery-lead",
        content_hash="0" * 64,
        updated_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def test_a_full_fake_satisfies_the_protocol() -> None:
    repository: ArtifactRepository = FakeRepository([_artifact()], [Collection(key="delivery")])
    assert isinstance(repository, ArtifactRepository)
    assert repository.get("skill/delivery-lead") is not None
    assert repository.get("skill/absent") is None
    assert [c.key for c in repository.list_collections()] == ["delivery"]


def test_a_repository_without_read_bytes_does_not_satisfy_the_protocol() -> None:
    """Positive control for the assertion above — it is capable of failing."""
    assert not isinstance(ReadTextOnlyRepository(), ArtifactRepository)


def test_list_all_returns_invalid_artifacts_rather_than_omitting_them() -> None:
    """The snapshot includes what is broken; that is the point of the product."""
    repository: ArtifactRepository = FakeRepository([_artifact()], [])
    assert len(repository.list_all()) == 1
