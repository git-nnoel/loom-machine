"""Contract C-4 over a real library root — the scanner, the reader and the assembler, composed.

This is the last piece of DEC-1. The superseded plan built the repository *first* and retrofitted
validation into it across two later tasks; here every part it composes was proven before it existed,
so it holds no rule, no parsing and no judgement of its own:

```
scan_library      →  a LibraryScan: RawArtifact values and the symlinked roots, from the disk
read_library_metadata  →  LibraryMetadata, from library.yaml
assemble_library  →  the finished Artifacts and their findings
```

**Snapshot semantics** (contract C-4, charter §7 and §12). The scan is taken **once, on first use,
and held**. C-4 calls `list_all()` a point-in-time snapshot and charter §12 says concurrent
processes each hold their own; re-scanning per call would let `get()` disagree with `list_all()`
inside a single CLI run, and would re-run git for every question asked. A new repository is a new
snapshot, which is the whole of the ceremony. A file changing mid-scan yields a torn read, accepted
here because this path only reads; initiative 02 revisits it because it writes.

**Errors are plain Python exceptions, deliberately.** Charter §9 says a code is added to the
taxonomy before it is emitted, and `domain/errors.py` was out of bounds for the task that wrote this
module — so an unknown id raises `KeyError`, an unknown path `FileNotFoundError`, and a traversal
attempt `ValueError`, rather than a code invented at the raise site. `LibraryYamlError` still
propagates from the reader unchanged, because that code *is* in the contract. Flagged to the
delivery lead: T-7 maps errors to exit codes and will want a ruling.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from harness_library.domain.artifact import Artifact, ArtifactKind
from harness_library.domain.assembly import AssembledLibrary, assemble_library
from harness_library.domain.metadata import Collection, LibraryMetadata
from harness_library.domain.raw import SymlinkedRoot
from harness_library.domain.registry import spec_for
from harness_library.domain.validation import ValidationFinding
from harness_library.infrastructure.library_yaml import read_library_metadata
from harness_library.infrastructure.scanner import scan_library
from harness_library.infrastructure.timestamps import ArtifactTimestamps


class FilesystemArtifactRepository:
    """Read access to a harness library on disk. Implements contract C-4.

    The protocol itself stays in `domain/repository.py` (ruling R14) and is satisfied structurally;
    this class does not inherit it, so `domain/` keeps knowing nothing about who implements it.
    """

    def __init__(self, library_root: Path, *, timestamps: ArtifactTimestamps | None = None) -> None:
        """Open a library.

        Args:
            library_root: the directory holding `skills/`, `agents/` and optionally `library.yaml`.
            timestamps: how ruling R5 is answered; defaults to git with the mtime fallback.

        Raises:
            FileNotFoundError: `library_root` is not a directory. Charter §13 requires the read path
                to fail loudly on a directory that is not a library rather than silently return an
                empty list — the composition root (C-8) does the richer diagnosis, and this is the
                floor beneath it.
        """
        if not library_root.is_dir():
            raise FileNotFoundError(f"{library_root} is not a directory, so it is not a library")
        self._library_root = library_root
        self._timestamps = timestamps
        self._assembled: AssembledLibrary | None = None
        self._metadata: LibraryMetadata | None = None
        self._symlinked_roots: tuple[SymlinkedRoot, ...] = ()

    # -- Contract C-4 ----------------------------------------------------------------------------

    def list_all(self) -> list[Artifact]:
        """Every artifact in the library, valid or not.

        An invalid artifact is returned carrying its findings, never omitted and never raised on.
        Superseded artifacts are here too (ruling R8) — nothing is dropped, only ranked later.
        """
        return list(self._snapshot().artifacts)

    def get(self, artifact_id: str) -> Artifact | None:
        """One artifact by `<type>/<name>`, or `None` when the library has no such artifact."""
        return self._snapshot().by_id.get(artifact_id)

    def read_bytes(self, artifact_id: str, path: str) -> bytes:
        """The raw bytes of one file, by path relative to the artifact root.

        Bytes and not text: initiative 02 installs binary files and initiative 03 exports zips, and
        the fixture library's PNG is exactly the case a text-only surface would foreclose.

        Raises:
            KeyError: no artifact has this id.
            ValueError: `path` is absolute or climbs out of the artifact root.
            FileNotFoundError: the artifact does not contain this path.
        """
        return self._resolve(artifact_id, path).read_bytes()

    def read_text(self, artifact_id: str, path: str) -> str:
        """The decoded text of one file. Only meaningful where `ArtifactFile.is_text` is true.

        Raises:
            UnicodeDecodeError: the file is binary. Left to surface rather than papered over with
                replacement characters: silently returning mojibake for the fixture's PNG would
                make a binary file look searchable, which is the one thing charter §7 says it is
                not.
            KeyError, ValueError, FileNotFoundError: as `read_bytes`.
        """
        return self.read_bytes(artifact_id, path).decode("utf-8")

    def list_collections(self) -> list[Collection]:
        """Every collection the library declares, in declaration order.

        A collection is returned whole even when a member resolves to nothing — that is a V7
        finding, not a reason to hide the collection or edit its member list.
        """
        self._snapshot()
        assert self._metadata is not None
        return list(self._metadata.collections)

    # -- Additive, and not part of C-4 -----------------------------------------------------------

    def library_findings(self) -> list[ValidationFinding]:
        """The findings that belong to no single artifact — V7, V9 and, since R46, **V11**.

        Part of contract C-4 since ruling R23. V7 and V9 are faults of the `library.yaml`
        *document* and V11 is a fault about an artifact root that was never scanned, so the
        assembler puts all three on `AssembledLibrary` rather than on an artifact; without a way
        to reach them, feature F-4 could report none of them and three rows of charter §8's
        register would be decorative.
        """
        return list(self._snapshot().findings)

    def symlinked_roots(self) -> tuple[SymlinkedRoot, ...]:
        """Every artifact root the scan found to be a symlink and therefore never walked. **V11.**

        Beyond contract C-4, which is untouched — the shape `library_findings()` had before
        ruling R23 put it in the contract, and flagged here for the same decision. `plan_install`
        needs these values to refuse the artifact (R46, R53), and it must not reach them through
        a `ValidationFinding`: the warning and the refusal are two facts, and a refusal that read
        the report would vanish the moment the report did. **Flagged to the delivery lead: C-4
        wants a seventh member, which is a plan-level decision.**

        The snapshot is taken on first use, exactly as `list_all()` takes it, so a listing and
        this answer always describe one walk of one library.
        """
        self._snapshot()
        return self._symlinked_roots

    # -- The snapshot ----------------------------------------------------------------------------

    def _snapshot(self) -> AssembledLibrary:
        """The held snapshot, taken on first use. See the module docstring.

        `library.yaml` is read **once** and held alongside it, not re-read by `list_collections`: a
        collection that described a newer revision of the document than the V7 findings reported
        about it would be a snapshot that disagrees with itself.
        """
        if self._assembled is None:
            self._metadata = read_library_metadata(self._library_root)
            scanned = scan_library(self._library_root, timestamps=self._timestamps)
            self._symlinked_roots = scanned.symlinked_roots
            self._assembled = assemble_library(
                scanned.artifacts,
                self._metadata,
                symlinked_roots=scanned.symlinked_roots,
            )
        return self._assembled

    # -- Path resolution -------------------------------------------------------------------------

    def _resolve(self, artifact_id: str, path: str) -> Path:
        """The absolute path of one file inside an artifact, or a refusal.

        Three stages, and the order is load-bearing.

        1. **Shape**, before anything touches the disk: an absolute path or any `..` component is a
           `ValueError`. First so the guarantee is a property of the string, testable without a
           filesystem that happens to lack the escaped-to file.
        2. **Membership** in the snapshot: only a path the scan actually took is readable. This is
           what makes a skipped symlink unreadable through the repository as well as unhashed —
           ruling R6 says never followed, and a `read_bytes` that followed it would be the same
           escape by another door.
        3. **Containment**, re-checked against the resolved path, plus a symlink refusal. Redundant
           given the first two, and kept anyway: it is the stage that still holds if a future change
           loosens either of them.
        """
        artifact = self.get(artifact_id)
        if artifact is None:
            raise KeyError(f"no artifact {artifact_id!r} in this library")

        pure = PurePosixPath(path)
        if not path or pure.is_absolute() or any(part == ".." for part in pure.parts):
            raise ValueError(
                f"{path!r} is not a path inside {artifact_id}: a file is addressed relative to the "
                "artifact root, and may not climb out of it"
            )

        relative = pure.as_posix()
        if not any(file.path == relative for file in artifact.files):
            raise FileNotFoundError(f"{artifact_id} contains no file at {relative!r}")

        root = self._library_root / artifact.path
        if spec_for(artifact.type).kind is ArtifactKind.FILE:
            # The root *is* the document; its single `ArtifactFile.path` is its own basename, so
            # joining would address a file inside a file.
            return root

        target = root.joinpath(*pure.parts)
        if target.is_symlink():
            raise ValueError(f"{relative!r} is a symlink, which is never followed (ruling R6)")
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"{relative!r} resolves outside {artifact_id}")
        return target


__all__ = ["FilesystemArtifactRepository"]
