"""Listing one library and showing one artifact — features F-1 and F-2.

Use-case **functions**, not classes (charter §3): each is one pure call over contract C-4, and a
class would be a constructor and a `__call__` wrapped around a function.

**Ordering is decided here and nowhere above.** T-7 renders a table and T-8 renders JSON; neither
sorts. Ruling R8's ranking in particular is a property of the read path, not of a presentation
layer — a CLI that ranked superseded artifacts itself and an MCP server that did not would give two
answers to one question.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from harness_library.application.read._access import (
    entry_path_of,
    read_file_text,
    require_artifact,
)
from harness_library.application.read.dtos import (
    ArtifactDetail,
    ArtifactListPayload,
    ArtifactSummary,
    FileContent,
)
from harness_library.application.read.queries import NO_FILTER, ArtifactFilter, SortKey
from harness_library.domain.artifact import Artifact
from harness_library.domain.errors import (
    ArtifactFileNotFoundError,
    CollectionNotFoundError,
    FileNotTextError,
)
from harness_library.domain.repository import ArtifactRepository

_SortValue = tuple[str, str] | tuple[float, str] | tuple[int, str]


def list_artifacts(
    repository: ArtifactRepository,
    *,
    artifact_filter: ArtifactFilter = NO_FILTER,
    sort_key: SortKey = SortKey.NAME,
) -> ArtifactListPayload:
    """Every artifact matching the filter, ordered by the sort key. Feature F-1.

    Invalid artifacts are included unless `invalid_only` excludes the valid ones — never the other
    way round. Superseded artifacts are included by default and ranked below the rest (ruling R8).

    Raises:
        CollectionNotFoundError: `artifact_filter.collection` names no declared collection.
    """
    matching = select_artifacts(repository, repository.list_all(), artifact_filter)
    ordered = sort_artifacts(matching, sort_key)
    return ArtifactListPayload(
        artifacts=tuple(ArtifactSummary.of(artifact) for artifact in ordered),
        total=len(ordered),
        sort=sort_key.value,
    )


def get_artifact(repository: ArtifactRepository, artifact_id: str) -> ArtifactDetail:
    """One artifact in full, entry text included. Feature F-2.

    **An invalid artifact is shown, not raised on.** A skill directory with no `SKILL.md` comes
    back with `entry_text` null and its V1 finding attached — that case is the reason feature F-2
    exists, and the superseded plan crashed on it. An entry document that exists but does not
    decode is treated the same way: the artifact is shown, and its text is null, because the
    finding a user needs is already on the artifact.

    Raises:
        ArtifactNotFoundError: no artifact with this id.
    """
    artifact = require_artifact(repository, artifact_id)
    entry_path = entry_path_of(artifact)
    entry_text: str | None
    try:
        entry_text = read_file_text(repository, artifact_id, entry_path)
    except (ArtifactFileNotFoundError, FileNotTextError):
        entry_text = None
    return ArtifactDetail.of_artifact(artifact, entry_path=entry_path, entry_text=entry_text)


def get_artifact_file(repository: ArtifactRepository, artifact_id: str, path: str) -> FileContent:
    """One file inside an artifact, by path relative to the artifact root.

    A file the scan recorded as binary comes back with `text` null rather than as an error: the
    caller asked for a file that exists, and charter §7 says binary content is stored and readable,
    just never decoded. `FileNotTextError` is reserved for a file the scan called text that then
    fails to decode — a torn read (charter §7), where the metadata and the bytes disagree and the
    caller must be told rather than handed mojibake.

    Raises:
        ArtifactNotFoundError: no artifact with this id.
        ArtifactFileNotFoundError: the artifact contains no file at this path.
        InvalidFilePathError: the path is not addressable inside the artifact root.
        FileNotTextError: the scan called the file text and it does not decode.
    """
    artifact = require_artifact(repository, artifact_id)
    file = next((candidate for candidate in artifact.files if candidate.path == path), None)
    if file is None:
        # Not in the snapshot. Ask the repository anyway and let *it* classify the path: a
        # traversal attempt is `INVALID_FILE_PATH` and a plain typo is `FILE_NOT_FOUND`, and the
        # rule telling them apart is the repository's (T-5 decision 2 checks shape before
        # membership, deliberately). Restating it here would be a second opinion that drifts.
        read_file_text(repository, artifact_id, path)
        raise ArtifactFileNotFoundError(artifact_id, path)
    text = read_file_text(repository, artifact_id, path) if file.is_text else None
    return FileContent(
        artifact_id=artifact_id,
        path=file.path,
        sha256=file.sha256,
        size=file.size,
        is_text=file.is_text,
        text=text,
    )


def select_artifacts(
    repository: ArtifactRepository,
    artifacts: Iterable[Artifact],
    artifact_filter: ArtifactFilter,
) -> list[Artifact]:
    """The artifacts a filter admits, in the order they arrived.

    Shared with the search use case, so `hl search --tag x` and `hl list --tag x` cannot disagree
    about what the tag means.

    Raises:
        CollectionNotFoundError: the filter names a collection the library does not declare.
    """
    members = _collection_members(repository, artifact_filter.collection)
    return [artifact for artifact in artifacts if _admits(artifact, artifact_filter, members)]


def sort_artifacts(artifacts: Iterable[Artifact], sort_key: SortKey) -> list[Artifact]:
    """Order a listing. Ruling R8 outranks the sort key.

    The primary key is **not** the requested one: a superseded artifact ranks below every live
    artifact whatever the caller asked to sort by, because R8 says it appears "below its
    successors" and nothing may hide it. Sorting only by the requested key would interleave a
    retired artifact with current ones under `--sort size`, which is the presentation R8 rejects.

    Every key ends in the artifact id, so the order is **total**: two artifacts with the same name,
    the same timestamp or the same size still have one defined position, and two runs over one
    snapshot produce the same list.
    """
    value = _SORT_VALUES[sort_key]

    def ranked(artifact: Artifact) -> tuple[bool, str | float | int, str]:
        return (artifact.superseded_by is not None, *value(artifact))

    return sorted(artifacts, key=ranked)


def _admits(
    artifact: Artifact, artifact_filter: ArtifactFilter, members: frozenset[str] | None
) -> bool:
    """Whether one artifact passes every clause of the filter."""
    if artifact_filter.type is not None and artifact.type is not artifact_filter.type:
        return False
    if artifact_filter.tag is not None and artifact_filter.tag not in artifact.tags:
        return False
    if members is not None and artifact.id not in members:
        return False
    if artifact_filter.invalid_only and artifact.is_valid:
        return False
    return artifact_filter.include_superseded or artifact.superseded_by is None


def _collection_members(repository: ArtifactRepository, key: str | None) -> frozenset[str] | None:
    """The member ids of one collection, or `None` when the filter names no collection.

    `None` rather than "every id": an empty collection must narrow a listing to nothing, and a
    sentinel that means "do not narrow" cannot be confused with one that means "narrow to nothing".

    Raises:
        CollectionNotFoundError: charter §13's posture. A collection key is declared in
            `library.yaml`, so an unrecognised one is a mistake, not a query matching nothing.
    """
    if key is None:
        return None
    for collection in repository.list_collections():
        if collection.key == key:
            return frozenset(collection.members)
    raise CollectionNotFoundError(key)


def _by_name(artifact: Artifact) -> tuple[str, str]:
    return (artifact.name, artifact.id)


def _by_updated(artifact: Artifact) -> tuple[float, str]:
    # Negated rather than `reverse=True`: the reverse flag would also invert the id tie-break and
    # ruling R8's leading key, turning a total order into a differently-broken one.
    return (-artifact.updated_at.timestamp(), artifact.id)


def _by_size(artifact: Artifact) -> tuple[int, str]:
    return (-sum(file.size for file in artifact.files), artifact.id)


_SORT_VALUES: dict[SortKey, Callable[[Artifact], _SortValue]] = {
    SortKey.NAME: _by_name,
    SortKey.UPDATED: _by_updated,
    SortKey.SIZE: _by_size,
}
"""One entry per `SortKey`. A member without one fails `tests/application/test_artifacts.py`."""


__all__ = [
    "get_artifact",
    "get_artifact_file",
    "list_artifacts",
    "select_artifacts",
    "sort_artifacts",
]
