"""Hand-written contract C-4 and C-12 repositories, in memory. Charter §10.

The application layer is tested against this and never against a disk. That is not merely faster:
`application/` may not import `infrastructure/`, so a test that reached for the real repository
would be testing an import the architecture contract forbids.

**What this fake cannot prove, stated once so no later task mistakes a green run for proof of it.**
It cannot prove that a real scan records a symlink, that `updated_at` came from git, that a real
`library.yaml` parses, or that a real binary file fails to decode. Every one of those is proven at
the infrastructure level against real files (T-5). What it *can* prove is the only thing this layer
decides: which artifacts a filter admits, what order they come back in, what is searched and what
is skipped, which findings reach a report, and which builtin becomes which error code.

The failures are injected as *builtins* — `KeyError`, `FileNotFoundError`, `ValueError`,
`UnicodeDecodeError` — because that is exactly what the real repository raises (ruling R24). A fake
that raised the project's own errors would make the translation untestable by pre-supplying its
result.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from harness_library.domain.artifact import Artifact, ArtifactFile, ArtifactKind
from harness_library.domain.backup import BackupRecord
from harness_library.domain.hashing import content_hash_of_files, hash_bytes
from harness_library.domain.identity import ArtifactType
from harness_library.domain.manifest import Manifest, ManifestArtifact
from harness_library.domain.metadata import Collection
from harness_library.domain.registry import spec_for
from harness_library.domain.target import TargetFile
from harness_library.domain.validation import ValidationCode, ValidationFinding

UPDATED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
"""The instant every artifact is pinned to unless a test is about ordering by time."""

TARGET_PATH = "/home/example/.claude"
"""The install target every fake in this module names. Never a real `~/.claude` (F-9, L37)."""


class FakeArtifactRepository:
    """Contract C-4 over dictionaries.

    Attributes:
        contents: `(artifact_id, path)` to the file's bytes. A path an artifact declares in
            `files` but that is missing here raises `FileNotFoundError`, which is how the real
            repository answers a path outside its snapshot.
    """

    def __init__(
        self,
        artifacts: list[Artifact] | None = None,
        *,
        contents: dict[tuple[str, str], bytes] | None = None,
        collections: list[Collection] | None = None,
        library_findings: list[ValidationFinding] | None = None,
    ) -> None:
        self._artifacts = list(artifacts or [])
        self.contents = dict(contents or {})
        self._collections = list(collections or [])
        self._library_findings = list(library_findings or [])
        self.read_calls: list[tuple[str, str]] = []

    def list_all(self) -> list[Artifact]:
        return list(self._artifacts)

    def get(self, artifact_id: str) -> Artifact | None:
        return next((a for a in self._artifacts if a.id == artifact_id), None)

    def read_bytes(self, artifact_id: str, path: str) -> bytes:
        self.read_calls.append((artifact_id, path))
        if self.get(artifact_id) is None:
            raise KeyError(f"no artifact {artifact_id!r} in this library")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"{path!r} may not climb out of the artifact root")
        try:
            return self.contents[(artifact_id, path)]
        except KeyError as error:
            raise FileNotFoundError(f"{artifact_id} contains no file at {path!r}") from error

    def read_text(self, artifact_id: str, path: str) -> str:
        return self.read_bytes(artifact_id, path).decode("utf-8")

    def list_collections(self) -> list[Collection]:
        return list(self._collections)

    def library_findings(self) -> list[ValidationFinding]:
        return list(self._library_findings)


def make_file(path: str, content: bytes = b"body\n", *, is_text: bool = True) -> ArtifactFile:
    """One `ArtifactFile` whose digest and size really describe `content`."""
    return ArtifactFile(path=path, sha256=hash_bytes(content), size=len(content), is_text=is_text)


def make_artifact(
    name: str,
    *,
    artifact_type: ArtifactType = ArtifactType.SKILL,
    files: tuple[ArtifactFile, ...] = (),
    tags: tuple[str, ...] = (),
    superseded_by: str | None = None,
    findings: tuple[ValidationFinding, ...] = (),
    updated_at: datetime = UPDATED_AT,
    description: str | None = "a description",
    frontmatter: dict[str, object] | None = None,
) -> Artifact:
    """An artifact whose `path` and `kind` come from the type registry, not from a literal."""
    spec = spec_for(artifact_type)
    return Artifact(
        type=artifact_type,
        name=name,
        kind=spec.kind,
        path=spec.root_path(name),
        content_hash=content_hash_of_files(files),
        updated_at=updated_at,
        description=description,
        frontmatter=frontmatter or {},
        superseded_by=superseded_by,
        tags=tags,
        files=files,
        findings=findings,
    )


def finding(
    code: ValidationCode, message: str = "something", path: str | None = None
) -> ValidationFinding:
    """A finding whose severity comes from the register (ruling R13), never from the test."""
    return ValidationFinding.for_code(code, message, path)


def skill_with_entry(
    name: str,
    entry_body: str = "# entry\n",
    *,
    references: dict[str, str] | None = None,
    extra_files: tuple[ArtifactFile, ...] = (),
    **kwargs: object,
) -> tuple[Artifact, dict[tuple[str, str], bytes]]:
    """A skill plus the bytes of its files, ready to hand to the fake.

    Returns the artifact and a `contents` fragment so a test can write one literal instead of
    keeping a file list and a byte map in step by hand.
    """
    spec = spec_for(ArtifactType.SKILL)
    entry_path = spec.entry_path(name)
    files = [make_file(entry_path, entry_body.encode("utf-8"))]
    for reference_path, body in (references or {}).items():
        files.append(make_file(reference_path, body.encode("utf-8")))
    files.extend(extra_files)

    artifact = make_artifact(name, files=tuple(files), **kwargs)  # type: ignore[arg-type]
    contents: dict[tuple[str, str], bytes] = {
        (artifact.id, entry_path): entry_body.encode("utf-8"),
    }
    for reference_path, body in (references or {}).items():
        contents[(artifact.id, reference_path)] = body.encode("utf-8")
    return artifact, contents


ARTIFACT_KINDS = (ArtifactKind.DIRECTORY, ArtifactKind.FILE)


class FakeTargetRepository:
    """Contract C-12 over dictionaries. The whole filesystem, as far as this layer can see.

    **What this fake cannot prove.** It cannot prove that a real walk records a symlink, that
    nothing is filtered out of a real scan, that a write lands at `0644`, or that a path climbing
    out of the target is refused. Every one of those is proven against real files in
    `tests/infrastructure/test_target.py`. What it *can* prove is the only thing this layer
    decides: which target-relative path each of the three sources lines up on, which verdict comes
    back for it, and whether anything was written.

    It collects evidence and renders no verdict (L29): `writes` and `deletes` are recordings, and
    every assertion about them lives in a test.

    **It holds real bytes**, so "byte-identical after apply" is an assertion about content and
    not about the recorder. The two are different claims and only one of them is the criterion:
    a recorder can be empty because nothing was written *or* because nothing recorded it, and
    F-9 and F-10 are about the file.

    Attributes:
        writes: `(path, data)` in call order — what an apply actually changed.
        deletes: the paths `delete` was called on, in call order.
        fail_write_after: how many writes to allow before the next one raises `OSError`. `None`
            allows every write. This is how a mid-write failure is injected: the real repository
            raises `OSError` from `write_bytes`, and a fake raising the project's own error would
            make the translation untestable by pre-supplying its result (ruling R24).
    """

    def __init__(
        self,
        files: Iterable[TargetFile] = (),
        *,
        contents: Mapping[str, bytes] | None = None,
        fail_write_after: int | None = None,
    ) -> None:
        self._files = tuple(files)
        self._contents = {file.path: b"" for file in self._files}
        self._contents.update(contents or {})
        self.writes: list[tuple[str, bytes]] = []
        self.deletes: list[str] = []
        self.scan_calls = 0
        self.fail_write_after = fail_write_after

    def scan(self) -> tuple[TargetFile, ...]:
        self.scan_calls += 1
        return self._files

    def read_bytes(self, path: str) -> bytes:
        try:
            return self._contents[path]
        except KeyError as error:
            raise FileNotFoundError(f"this target holds nothing at {path!r}") from error

    def write(self, path: str, data: bytes) -> None:
        if self.fail_write_after is not None and len(self.writes) >= self.fail_write_after:
            raise OSError(f"the injected failure refuses to write {path!r}")
        self.writes.append((path, data))
        self._contents[path] = data

    def delete(self, path: str) -> None:
        self.deletes.append(path)
        self._contents.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self._contents

    def snapshot(self) -> dict[str, bytes]:
        """Every path this target holds and its bytes. Evidence for a byte-identical assertion."""
        return dict(self._contents)


def target_holding(*entries: tuple[str, bytes]) -> FakeTargetRepository:
    """A target holding exactly these paths, with digests that really describe the bytes.

    Built here rather than in each test so the scan a plan is decided from and the content an
    assertion reads can never disagree — two literals for one file is how a "byte-identical" test
    ends up comparing a byte string to itself.
    """
    return FakeTargetRepository(
        tuple(target_file(path, data) for path, data in entries), contents=dict(entries)
    )


class FakeBackupStore:
    """Contract C-13 in memory. Records what it was asked to keep; keeps nothing.

    **What this fake cannot prove.** It cannot prove that a backup survives a `git clean`, that it
    lands outside the target, or that a restore puts real bytes back. Those are proven against
    real files in `tests/infrastructure/test_backup.py`. What it *can* prove is the only thing
    apply decides: that a backup is taken, that it covers every path the run will touch, and that
    a failure to take one stops the run before anything is written.

    Attributes:
        created: the path tuples `create` was called with, in call order.
        restored: the ids `restore` was called with, in call order.
        fail: raise `OSError` from `create` instead of taking a backup. A builtin, because that is
            what the real store raises (ruling R24).
    """

    def __init__(self, *, fail: bool = False, backup_id: str = "2026-09-21T14-29-00Z") -> None:
        self.created: list[tuple[str, ...]] = []
        self.restored: list[str] = []
        self.fail = fail
        self._backup_id = backup_id
        self._records: list[BackupRecord] = []

    def create(self, paths: tuple[str, ...]) -> str:
        if self.fail:
            raise OSError("the injected failure refuses to take a backup")
        self.created.append(paths)
        self._records.append(
            BackupRecord(
                backup_id=self._backup_id,
                created_at=UPDATED_AT,
                target_path=TARGET_PATH,
                paths=paths,
            )
        )
        return self._backup_id

    def restore(self, backup_id: str) -> None:
        self.restored.append(backup_id)

    def list(self) -> tuple[BackupRecord, ...]:
        return tuple(self._records)


class FakeManifestStore:
    """The `ManifestStore` seam in memory. Holds the last manifest written, and the count.

    Attributes:
        written: every manifest handed to `write`, in call order. **The evidence for ruling
            R63**: a test that injects a failure into the first file write and then finds a
            manifest here has proven the order, and one that finds none has proven it broken.
        fail: raise `OSError` from `write`. A builtin, for the reason `FakeBackupStore.fail` is.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.written: list[Manifest] = []
        self.fail = fail

    def write(self, manifest: Manifest) -> None:
        if self.fail:
            raise OSError("the injected failure refuses to write the manifest")
        self.written.append(manifest)

    @property
    def latest(self) -> Manifest | None:
        """The manifest on disk, or `None` when none was ever written."""
        return self.written[-1] if self.written else None


def target_file(path: str, content: bytes = b"body\n") -> TargetFile:
    """One ordinary target entry whose digest and size really describe `content`."""
    return TargetFile(path=path, sha256=hash_bytes(content), size=len(content), is_symlink=False)


def target_symlink(path: str, *, destination: str = "../../../outside/escape.md") -> TargetFile:
    """One symlink entry. R6: never followed, never hashed, so it carries no content digest.

    `sha256` is `None` and cannot be anything else: ruling R68 made that the spelling of "no
    digest", and `TargetFile` refuses a link carrying one. That the *rule* reading it survives a
    change of sentinel is proven one level down, against `target_sha_of` over both spellings —
    see `tests/application/test_drift.py`.

    `size` is the link's own, the length of the path it names, never the destination's.
    """
    return TargetFile(path=path, sha256=None, size=len(destination), is_symlink=True)


def manifest_artifact(artifact_id: str, files: tuple[ArtifactFile, ...]) -> ManifestArtifact:
    """One manifest record, with a content hash that really describes `files`."""
    return ManifestArtifact(
        artifact_id=artifact_id,
        content_hash=content_hash_of_files(files),
        files=files,
    )


def manifest_of(
    *artifacts: ManifestArtifact,
    target_path: str = TARGET_PATH,
) -> Manifest:
    """A manifest recording exactly these artifacts. `installed_at` is pinned, never `now()`."""
    return Manifest(
        target_path=target_path,
        installed_at=UPDATED_AT,
        library_git_sha=None,
        backup_id=None,
        artifacts=artifacts,
    )
