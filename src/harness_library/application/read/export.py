"""`ExportCollection` — a curated group of artifacts as a plain zip. Feature F-16, ruling **R45**.

**A plain zip, and nothing more.** R45 deferred the plugin format out of this initiative entirely,
so there is no manifest inside the archive, no `library.yaml`, no metadata sidecar and no
directory this tool invented: the entries are exactly the collection's artifacts' files. That is
not minimalism for its own sake — the criterion F-16 is stated as is a **path list**, and every
extra entry is a claim about a format nobody has designed yet.

## This is a read use case, and the placement is the whole guarantee

Spec §5 fixes which side each use case lands on. `mcp-is-read-only` forbids `mcp/` from reaching
`application.write`, and it cannot tell whether a *given* function belongs where it sits: an
export defined in `application/write/` would keep `mypy`, `ruff` and `lint-imports` all green
while being unreachable from the one adapter that should have it, and an export defined here that
had any business writing would be reachable from a read-only session. T-15's mutation proved the
contract is blind to exactly this, so `tests/test_architecture.py` is the only guard and it names
this function.

**No lock** (R82's converse, R85). Reads take none: this holds the library's snapshot, writes
nothing and cannot interleave with anything. A lock here would serialise the one operation in the
project that is always safe.

## The entry names are target-relative paths

`registry.target_path_of`, the same forward join install writes through (R73): a skill's files
land under `skills/<name>/` and an agent is `agents/<name>.md`, because a `FILE`-kind artifact
*is* its entry document and joining onto its root would give `agents/scribe.md/scribe.md`. So the
archive unzips over a harness and lands where the same artifacts would have been installed, which
is the only layout that makes an export worth having. Never an inverse of that join, and never a
literal.

## Determinism

Two exports of one library produce **byte-identical** archives. Members come back in declaration
order, exactly as `get_collection` returns them — a collection is a curated sequence and
re-sorting it would discard the intent — the files of each artifact in the artifact's own order,
and each entry's timestamp is the artifact's `updated_at` rather than the clock. Without that last
one the archive would differ on every run and no caller could compare two of them, which is the
same argument the scanner's sorted walk already makes about reports.

## What is in, and what is merely reported

* an **invalid** artifact is exported like any other. Charter §10 and feature F-2's posture: an
  artifact that is invisible because it is broken is the failure this product exists to close, and
  an export that silently dropped one would reproduce it;
* a **binary** file is exported like any other, byte for byte. Charter §7 says binary content is
  stored, hashed, exported and installed — never searched — and `read_bytes` is on C-4 precisely
  so that this function does not have to round-trip content through `str`;
* a **member that resolves to nothing** contributes no entry and is reported in
  `unresolved_member_ids`, exactly as `get_collection` reports it. It is also a V7 ERROR in the
  validation report; naming it here too spares a caller having to validate the whole library to
  discover that a third of its archive is missing. A symlinked artifact root (V11) arrives here
  the same way, because the scan produced no artifact for it.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import datetime

from harness_library.application.read._access import read_file_bytes
from harness_library.domain.errors import CollectionNotFoundError
from harness_library.domain.metadata import Collection
from harness_library.domain.registry import target_path_of
from harness_library.domain.repository import ArtifactRepository

_EARLIEST_ZIP_YEAR = 1980
"""The first year the zip format can record. Below it `ZipInfo` raises inside the archive writer.

Named rather than inlined because the clamp below is the only place this function tells anything
less than the truth, and an unexplained `1980` in a date expression reads like a typo.
"""


@dataclass(frozen=True, slots=True)
class ExportedCollection:
    """One collection as an archive, plus what the collection asked for and did not get.

    Attributes:
        key: the collection that was exported.
        data: the zip itself. Bytes and not a path: `application/` writes no files, and the
            adapter that asked for this is the one that decides where it goes — the same division
            that keeps every other use case in this package free of a filesystem.
        entries: the archive's entry names in write order, which is exactly what
            `zipfile.ZipFile(...).namelist()` returns. Carried beside the bytes so a caller can
            report what it exported without opening what it just received.
        unresolved_member_ids: the collection's members that resolve to no artifact, in
            declaration order. Each is also a V7 ERROR in the validation report.
    """

    key: str
    data: bytes
    entries: tuple[str, ...] = ()
    unresolved_member_ids: tuple[str, ...] = ()


def export_collection(repository: ArtifactRepository, key: str) -> ExportedCollection:
    """Every file of every artifact this collection resolves, as a plain zip. Feature F-16.

    Args:
        repository: contract C-4, the library being exported from. Read only — `list_collections`,
            `list_all` and `read_bytes`, and nothing else.
        key: the collection to export, as `library.yaml` declares it.

    Returns:
        `ExportedCollection`. A collection whose every member resolves to nothing still produces
        an archive — an empty one — and names them all: that is a true answer about a declared
        collection, and it is a different fact from the collection not existing.

    Raises:
        CollectionNotFoundError: the library declares no collection with this key. Charter §13's
            posture, exactly as `get_collection` keeps it: a key is declared, so an unrecognised
            one is a mistake and never a query that happens to match nothing.
        ArtifactFileNotFoundError: a file the snapshot names is no longer in the library — a torn
            read (charter §7), which this tool states rather than locks against.
        InvalidFilePathError: the snapshot names a path that is not addressable inside its
            artifact root.
    """
    collection = _require_collection(repository, key)
    by_id = {artifact.id: artifact for artifact in repository.list_all()}

    buffer = io.BytesIO()
    entries: list[str] = []
    unresolved: list[str] = []
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member_id in collection.members:
            artifact = by_id.get(member_id)
            if artifact is None:
                unresolved.append(member_id)
                continue
            for file in artifact.files:
                path = target_path_of(artifact.type, artifact.name, file.path)
                archive.writestr(
                    _entry_for(path, artifact.updated_at),
                    read_file_bytes(repository, artifact.id, file.path),
                )
                entries.append(path)

    return ExportedCollection(
        key=collection.key,
        data=buffer.getvalue(),
        entries=tuple(entries),
        unresolved_member_ids=tuple(unresolved),
    )


def _entry_for(path: str, updated_at: datetime) -> zipfile.ZipInfo:
    """One archive entry, timestamped from the artifact rather than from the clock.

    `ZipInfo` defaults its `date_time` to *now*, which would make two exports of one unchanged
    library differ in every entry and leave a caller no way to compare them. `updated_at` is the
    only instant this tool knows about a file (ruling R5: the last commit touching it, or the
    mtime fallback), it is deterministic for a given library state, and it is the honest answer to
    "when was this last changed".

    Clamped at 1980 because the format cannot record an earlier year and raises rather than
    rounding. A library old enough to hit it does not exist; the clamp is here so that if one ever
    does, the export loses a timestamp instead of failing.
    """
    stamp = updated_at.timetuple()
    year = max(stamp.tm_year, _EARLIEST_ZIP_YEAR)
    info = zipfile.ZipInfo(
        filename=path,
        date_time=(year, stamp.tm_mon, stamp.tm_mday, stamp.tm_hour, stamp.tm_min, stamp.tm_sec),
    )
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _require_collection(repository: ArtifactRepository, key: str) -> Collection:
    """The declared collection, or a loud failure. `get_collection`'s rule, and its reason.

    Returning an empty archive for an unrecognised key would read as "this collection is empty",
    which is a different and confidently wrong answer — and the one charter §13 exists to forbid.
    """
    for collection in repository.list_collections():
        if collection.key == key:
            return collection
    raise CollectionNotFoundError(key)


__all__ = ["ExportedCollection", "export_collection"]
