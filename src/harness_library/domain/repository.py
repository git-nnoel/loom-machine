"""Contract C-4 — the repository interface the read path is written against.

Declared with the vocabulary rather than with its implementation so that T-5 implements a frozen
signature instead of inventing one, and so that the application layer's fakes and the real adapter
are substitutable by construction.

`read_bytes` alongside `read_text` is not redundancy. Initiative 02 installs binary files and
initiative 03 exports zips; a text-only surface forecloses both, and the 184 KB HTML asset in the
fixture library is exactly the case that finds it out.

**Snapshot semantics.** One `list_all()` is a point-in-time snapshot (charter §7). A file changing
mid-scan yields a torn read, which is accepted for a read-only single-user tool; initiative 02
revisits it because it writes. Implementations must be safe to hold concurrently — the read path
takes no locks (charter §12).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness_library.domain.artifact import Artifact
from harness_library.domain.metadata import Collection
from harness_library.domain.validation import ValidationFinding


@runtime_checkable
class ArtifactRepository(Protocol):
    """Read access to a harness library."""

    def list_all(self) -> list[Artifact]:
        """Every artifact in the library, valid or not.

        An invalid artifact is returned carrying its findings, never omitted and never raised on:
        an artifact that is invisible because it is broken is the failure this product exists to
        close.
        """
        ...

    def get(self, artifact_id: str) -> Artifact | None:
        """One artifact by `<type>/<name>`, or `None` when the library has no such artifact."""
        ...

    def read_bytes(self, artifact_id: str, path: str) -> bytes:
        """The raw bytes of one file, by path relative to the artifact root."""
        ...

    def read_text(self, artifact_id: str, path: str) -> str:
        """The decoded text of one file. Only meaningful for a file whose `is_text` is true."""
        ...

    def list_collections(self) -> list[Collection]:
        """Every collection the library declares, in declaration order."""
        ...

    def library_findings(self) -> list[ValidationFinding]:
        """The findings that belong to no single artifact — V7, V9 and, since R46, **V11**.

        V7 and V9 are faults of the `library.yaml` *document*, so the assembler puts them on the
        library rather than on an artifact and there is by definition no artifact to hang them
        on. V11 arrives at the same place from the other direction: its subject is an artifact
        root that R6 never followed, so no artifact was produced for it at all. Declared here
        because ruling R23 made this method part of contract C-4: without it the validate use
        case cannot reach any of the three, and three rows of charter §8's register are
        decorative — a rule that cannot reach a report can never be acted on.
        """
        ...
