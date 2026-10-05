"""Where a target's manifest lives, how it is written, and the reader that refuses to guess.

Decision DEC-14 puts the manifest **outside every tree it describes** —
`~/.local/state/loom/manifests/<sha256 of the target path>.json`. Inside the target it
would be a file the harness must then learn to ignore, in the plan, in the drift report, in
uninstall and in `clean --foreign`, four places that would each have to remember. Inside the
library it would be committed, and it would differ on every machine that installed from it.

**This reader is loud, for a sharper reason than `library.yaml`'s.** A damaged `library.yaml`
read as empty metadata costs a user their tags. A damaged manifest read as an empty manifest costs
them their files: with no record of what was installed, the verdict rule sees no manifest digest
for any path, judges each one `CREATE`, and the next install overwrites every file in the target.
So a manifest that exists and cannot be used is `ManifestError` with a location, always, and the
one case that answers quietly is the one that is genuinely not a fault.

**Absent, empty and damaged are three different things**, and the first two are values:

* **Absent** — no file. `None`. Nothing has been installed into this target yet, and a first
  install must work.
* **Empty** — a manifest recording no artifacts. A `Manifest` with `artifacts == ()`. This target
  *was* installed into and then uninstalled, which is not the same fact as never having been
  touched, and T-18 and T-19 need to tell them apart.
* **Damaged** — unparseable, wrongly shaped, unknown key, unknown schema version, not UTF-8.
  `ManifestError`, carrying where.

**The state root is a parameter, never the environment.** Charter §13 keeps `os.environ` inside
`cli/settings.py` and nowhere else, so nothing here reads `$XDG_STATE_HOME`. `default_state_root()`
computes DEC-14's path and creates nothing; the composition root passes it down, and every test
passes `tmp_path` instead, which is what keeps the suite out of a developer's real state directory.

**The write is atomic** — a sibling temporary file and `os.replace`. A process killed halfway
through a straight `write_text` is exactly how a half-written manifest gets made, and a
half-written manifest is the damaged case this module exists to keep out of the verdict rule.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from loom.domain.artifact import ArtifactFile
from loom.domain.errors import ManifestError
from loom.domain.hashing import hash_bytes
from loom.domain.manifest import Manifest, ManifestArtifact

STATE_DIRECTORY_NAME = "loom-machine"
"""This tool's directory under the user's state root. DEC-14."""

MANIFESTS_DIRECTORY_NAME = "manifests"
"""The directory holding one JSON document per target. DEC-14."""

SCHEMA_VERSION = 1
"""The version of the on-disk document, written into every manifest and checked on every read.

**A document field, not a `Manifest` field** — contract C-11's entity is untouched by it. It earns
its place on the diagnosis rather than on the data: this reader rejects an unknown key, so without
a version a manifest written by a later `loom` would be reported as corruption, which is both wrong
and unactionable. With one, it is reported as what it is. The manifest lives outside version
control and a reinstall regenerates it, so a version this build does not read is a cheap failure —
but it has to be a *legible* one.
"""

_ENCODING = "utf-8"

_MANIFEST_KEYS = (
    "schema_version",
    "target_path",
    "installed_at",
    "library_git_sha",
    "backup_id",
    "artifacts",
)
_ARTIFACT_KEYS = ("artifact_id", "content_hash", "files")
_FILE_KEYS = ("path", "sha256", "size", "is_text")


def default_state_root() -> Path:
    """DEC-14's state root, `~/.local/state/loom`. Computes; never creates.

    Called by the composition root, not by anything in this module — every function here takes the
    root as an argument so that a test can point it at `tmp_path` and a second target can point it
    somewhere else entirely.
    """
    return Path.home() / ".local" / "state" / STATE_DIRECTORY_NAME


def canonical_target_path(target: Path) -> str:
    """The one spelling of a target directory that this store keys and records.

    `--target` accepts any directory (R43), and a user will spell one directory several ways: with
    and without a trailing slash, relatively, or through a symlink. All of those are the same
    directory and must reach the same manifest, or a second install would see no record of the
    first and judge the user's own files `CREATE`.

    `resolve()` collapses every one of them, including the symlink — which is correct rather than
    merely convenient: two names for one directory share its contents, so they must share its
    record. It does not require the directory to exist, so a manifest can be keyed for a target
    the install is about to create.
    """
    return str(target.resolve())


def manifest_path_for(target: Path, *, state_root: Path) -> Path:
    """Where this target's manifest lives. DEC-14, R43.

    The file name is `hash_bytes` of the canonical target path — `domain.hashing`'s single
    implementation, not a second `hashlib` call, for the reason charter §7 gives: two hashing
    routines over one rule agree until they do not.

    A digest rather than the path itself because a path contains separators and characters a file
    name may not, and because the result is a fixed length whatever the target's depth. Nothing
    reads the target back out of the name — the document records `target_path` in full.
    """
    key = hash_bytes(canonical_target_path(target).encode(_ENCODING))
    return state_root / MANIFESTS_DIRECTORY_NAME / f"{key}.json"


def read_manifest(target: Path, *, state_root: Path) -> Manifest | None:
    """What was last installed into `target`, or `None` when nothing was.

    Args:
        target: the install target. Any spelling of it; see `canonical_target_path`.
        state_root: the directory manifests live under. `default_state_root()` in production,
            `tmp_path` in a test.

    Returns:
        The manifest, or `None` when this target has no manifest at all — "nothing installed here
        yet", which is a value and not a fault. A manifest recording **no artifacts** comes back as
        a `Manifest`, not as `None`; those are different facts.

    Raises:
        ManifestError: the manifest exists and cannot be used. Carries a line and column when the
            document does not parse, and the field path inside the document when it parses into
            the wrong shape.
    """
    path = manifest_path_for(target, state_root=state_root)
    if not path.exists():
        return None

    # `UnicodeDecodeError` is a subclass of `ValueError` and so is `json.JSONDecodeError` (L23).
    # Decoding and parsing are two separate blocks catching two exact types, so a manifest that is
    # not text at all is reported as that, and never as a syntax error at line 1.
    try:
        text = path.read_text(encoding=_ENCODING)
    except UnicodeDecodeError as error:
        raise ManifestError(
            "the manifest is not valid UTF-8 text, so it is not a document this tool wrote",
            path=str(path),
        ) from error
    except OSError as error:
        raise ManifestError(
            f"the manifest exists but could not be read: {error.strerror or error}",
            path=str(path),
        ) from error

    return _read_document(text, path=path)


def write_manifest(manifest: Manifest, *, state_root: Path) -> Path:
    """Record `manifest` as this target's manifest, atomically. Returns the file it wrote.

    The file is keyed by the canonical form of `manifest.target_path`, so a manifest built with a
    non-canonical spelling still lands where `read_manifest` will look for it.

    A failure to write is **not** translated into a `ManifestError`: that code says a manifest
    could not be *read*. T-13 flagged the gap and **ruling R64 closed it** —
    `MANIFEST_UNWRITABLE`, exit status 11 — but the translation still does not happen here. The
    `OSError` surfaces, exactly as the read path's builtins do, and `application/write/install.py`
    turns it into `ManifestWriteError`. Ruling R24's posture, kept: a store that raised the
    project's own error would make that translation untestable by pre-supplying its result.

    Raises:
        OSError: the state directory could not be created, or the document could not be written.
    """
    path = manifest_path_for(Path(manifest.target_path), state_root=state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_as_document(manifest), indent=2, ensure_ascii=False) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=_ENCODING) as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


# ------------------------------------------------------------------------------------------------
# Serialisation. One shape, written and read in one module, so a key cannot be added to one side.
# ------------------------------------------------------------------------------------------------


def _as_document(manifest: Manifest) -> dict[str, Any]:
    """The manifest as the mapping that is written. Every key present, nulls included."""
    return {
        "schema_version": SCHEMA_VERSION,
        "target_path": manifest.target_path,
        "installed_at": manifest.installed_at.isoformat(),
        "library_git_sha": manifest.library_git_sha,
        "backup_id": manifest.backup_id,
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "content_hash": artifact.content_hash,
                "files": [
                    {
                        "path": file.path,
                        "sha256": file.sha256,
                        "size": file.size,
                        "is_text": file.is_text,
                    }
                    for file in artifact.files
                ],
            }
            for artifact in manifest.artifacts
        ],
    }


def _read_document(text: str, *, path: Path) -> Manifest:
    """Parse and interpret. Two failures, two shapes of location — see `ManifestError`."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ManifestError(
            f"the manifest is not valid JSON: {error.msg}",
            path=str(path),
            line=error.lineno,
            column=error.colno,
        ) from error

    root = _mapping(document, location=None, path=path)
    _reject_unknown_keys(root, allowed=_MANIFEST_KEYS, within=None, path=path)
    _check_schema_version(root, path=path)

    # Read in document order, so the first fault a user is told about is the first one they would
    # find themselves. Every field is read before anything is constructed.
    target_path = _string(root, "target_path", within=None, path=path)
    installed_at = _read_installed_at(root, path=path)
    library_git_sha = _optional_string(root, "library_git_sha", within=None, path=path)
    backup_id = _optional_string(root, "backup_id", within=None, path=path)
    artifacts = tuple(
        _read_artifact(item, location=_indexed("artifacts", index), path=path)
        for index, item in enumerate(_sequence(root, "artifacts", within=None, path=path))
    )

    return _build(
        lambda: Manifest(
            target_path=target_path,
            installed_at=installed_at,
            library_git_sha=library_git_sha,
            backup_id=backup_id,
            artifacts=artifacts,
        ),
        location=None,
        path=path,
    )


def _check_schema_version(root: dict[str, Any], *, path: Path) -> None:
    """Refuse a document this build does not read, saying so rather than calling it corrupt."""
    version = _integer(root, "schema_version", within=None, path=path)
    if version != SCHEMA_VERSION:
        raise ManifestError(
            f"this manifest declares schema version {version}; this build of loom-machine "
            f"reads version {SCHEMA_VERSION}. The manifest is not damaged — it was written by a "
            "different version. Reinstalling into this target rewrites it",
            path=str(path),
            location="schema_version",
        )


def _read_installed_at(root: dict[str, Any], *, path: Path) -> datetime:
    """An ISO-8601 instant that carries an offset. Naive is refused here, with its location."""
    raw = _string(root, "installed_at", within=None, path=path)
    try:
        installed_at = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ManifestError(
            f"must be an ISO-8601 timestamp, but is {raw!r}",
            path=str(path),
            location="installed_at",
        ) from error
    if installed_at.tzinfo is None:
        raise ManifestError(
            f"must carry a UTC offset, but {raw!r} does not. An instant read back without one "
            "cannot be compared with an aware one, and the comparison raises far from here",
            path=str(path),
            location="installed_at",
        )
    return installed_at


def _read_artifact(value: Any, *, location: str, path: Path) -> ManifestArtifact:
    """One entry of `artifacts`."""
    node = _mapping(value, location=location, path=path)
    _reject_unknown_keys(node, allowed=_ARTIFACT_KEYS, within=location, path=path)
    artifact_id = _string(node, "artifact_id", within=location, path=path)
    content_hash = _string(node, "content_hash", within=location, path=path)
    files = tuple(
        _read_file(item, location=_indexed(_field(location, "files"), index), path=path)
        for index, item in enumerate(_sequence(node, "files", within=location, path=path))
    )
    return _build(
        lambda: ManifestArtifact(
            artifact_id=artifact_id,
            content_hash=content_hash,
            files=files,
        ),
        location=location,
        path=path,
    )


def _read_file(value: Any, *, location: str, path: Path) -> ArtifactFile:
    """One entry of an artifact's `files` — contract C-1's `ArtifactFile`, read back."""
    node = _mapping(value, location=location, path=path)
    _reject_unknown_keys(node, allowed=_FILE_KEYS, within=location, path=path)
    relative_path = _string(node, "path", within=location, path=path)
    sha256 = _string(node, "sha256", within=location, path=path)
    size = _integer(node, "size", within=location, path=path)
    is_text = _boolean(node, "is_text", within=location, path=path)
    return _build(
        lambda: ArtifactFile(path=relative_path, sha256=sha256, size=size, is_text=is_text),
        location=location,
        path=path,
    )


# ------------------------------------------------------------------------------------------------
# Shape helpers. Each returns the value or raises with the field path; none of them coerce.
# ------------------------------------------------------------------------------------------------


def _field(within: str | None, key: str) -> str:
    """`artifacts[0]` and `content_hash` make `artifacts[0].content_hash`."""
    return key if within is None else f"{within}.{key}"


def _indexed(within: str, index: int) -> str:
    """`artifacts` and `0` make `artifacts[0]`."""
    return f"{within}[{index}]"


def _build[T](make: Callable[[], T], *, location: str | None, path: Path) -> T:
    """Construct a domain value, turning its own invariant failures into a located error.

    The invariants live on the dataclasses, not here: a negative `size` or a duplicate
    `artifact_id` is wrong wherever it came from, and restating the rules in this reader would
    give the project two of each. What this does is stop a bare `ValueError` escaping a reader
    whose whole contract is that a damaged manifest arrives as `ManifestError` with a location.
    """
    try:
        return make()
    except ValueError as error:
        raise ManifestError(
            f"the manifest records something this tool cannot have written: {error}",
            path=str(path),
            location=location,
        ) from error


def _mapping(value: Any, *, location: str | None, path: Path) -> dict[str, Any]:
    """A JSON object. A list, a string or a null in its place is a shape failure."""
    if isinstance(value, dict):
        typed: dict[str, Any] = value
        return typed
    raise ManifestError(
        f"must be a JSON object, but is {_describe(value)}",
        path=str(path),
        location=location if location is not None else "the document",
    )


def _reject_unknown_keys(
    node: dict[str, Any], *, allowed: tuple[str, ...], within: str | None, path: Path
) -> None:
    """An unrecognised key is a failure, never something skipped.

    A manifest is machine-written, so an unknown key means one of three things: a newer version
    wrote it, something else wrote it, or it was edited by hand. None of those is a document whose
    remaining keys can be trusted to mean what this reader thinks they mean.
    """
    unknown = sorted(key for key in node if key not in allowed)
    if unknown:
        raise ManifestError(
            f"{unknown} is not a key of a manifest here; expected one of {', '.join(allowed)}",
            path=str(path),
            location=_field(within, unknown[0]),
        )


def _required(node: dict[str, Any], key: str, *, within: str | None, path: Path) -> Any:
    """The value at `key`. Every key is required and written explicitly, nulls included."""
    if key not in node:
        raise ManifestError(
            "is missing; every key of a manifest is written explicitly, a null one included, so "
            "an absent key means the document was not written by this tool",
            path=str(path),
            location=_field(within, key),
        )
    return node[key]


def _string(node: dict[str, Any], key: str, *, within: str | None, path: Path) -> str:
    """A required, non-null string."""
    value = _required(node, key, within=within, path=path)
    if isinstance(value, str):
        return value
    raise ManifestError(
        f"must be a string, but is {_describe(value)}",
        path=str(path),
        location=_field(within, key),
    )


def _optional_string(
    node: dict[str, Any], key: str, *, within: str | None, path: Path
) -> str | None:
    """A string, or `null` for a field whose answer is honestly "there is none"."""
    value = _required(node, key, within=within, path=path)
    if value is None:
        return None
    return _string(node, key, within=within, path=path)


def _integer(node: dict[str, Any], key: str, *, within: str | None, path: Path) -> int:
    """A required integer. `true` is not one, whatever `isinstance(True, int)` says."""
    value = _required(node, key, within=within, path=path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(
            f"must be an integer, but is {_describe(value)}",
            path=str(path),
            location=_field(within, key),
        )
    return value


def _boolean(node: dict[str, Any], key: str, *, within: str | None, path: Path) -> bool:
    """A required boolean. `1` and `"true"` are not booleans — they are a different document."""
    value = _required(node, key, within=within, path=path)
    if not isinstance(value, bool):
        raise ManifestError(
            f"must be true or false, but is {_describe(value)}",
            path=str(path),
            location=_field(within, key),
        )
    return value


def _sequence(node: dict[str, Any], key: str, *, within: str | None, path: Path) -> list[Any]:
    """A required JSON array. A null is **not** an empty list here: a manifest is machine-written,
    so `null` where a list belongs means the writer was not this one."""
    value = _required(node, key, within=within, path=path)
    if isinstance(value, list):
        typed: list[Any] = value
        return typed
    raise ManifestError(
        f"must be a list, but is {_describe(value)}",
        path=str(path),
        location=_field(within, key),
    )


def _describe(value: Any) -> str:
    """How to name a JSON value in a complaint aimed at whoever has to fix the file."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    return f"{value!r}"


class FilesystemManifestStore:
    """`ManifestStore` over the functions above, for one state root. Contract's seam, not C-11.

    The protocol lives in `domain/manifest.py` and is satisfied structurally — this class does not
    inherit it, the shape ruling R14 settled for C-4 and C-12 keeps.

    It exists because `application/` may not import `infrastructure/` and ruling R63 makes writing
    the manifest a step of apply rather than something the composition root does afterwards. The
    functions stay the implementation; this is the object that carries the state root so that the
    caller does not have to pass it through a use case that has no other use for it.

    **Not a cache and not a reader.** `read_manifest` is called once by the composition root and
    its result is handed to `plan_install` and `apply_install` as a value, so that both judge one
    snapshot. An object that could read as well would invite a second read, and two reads of one
    manifest is two answers about what is installed.
    """

    def __init__(self, state_root: Path) -> None:
        """Bind the store to a state root. `default_state_root()` in production, `tmp_path`
        in every test — nothing here reads the environment (charter §13)."""
        self._state_root = state_root

    def write(self, manifest: Manifest) -> None:
        """Record `manifest`, atomically. See `write_manifest` for what atomically means here.

        Raises:
            OSError: the document could not be written. Left as a builtin on purpose; see
                `write_manifest`.
        """
        write_manifest(manifest, state_root=self._state_root)


__all__ = [
    "MANIFESTS_DIRECTORY_NAME",
    "SCHEMA_VERSION",
    "STATE_DIRECTORY_NAME",
    "FilesystemManifestStore",
    "canonical_target_path",
    "default_state_root",
    "manifest_path_for",
    "read_manifest",
    "write_manifest",
]
