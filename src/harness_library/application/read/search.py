"""Searching a library — feature F-3, ruling R4 and ruling R25.

Two rules shape everything here.

**Ruling R4 — what is searched.** The entry document and every `.md` file under `references/`.
Nothing else. Every other file inside a searched artifact is *reported* as skipped, with a reason,
so the omission is visible rather than silent: a search that quietly declines to look inside half a
library and says nothing is the exact failure this product exists to eliminate.

**Ruling R25 — why a file is not searched.** The reason is *not a markdown reference*, never
"binary". The fixture library's 184 KB HTML asset is valid UTF-8 and is still not searched. The
order of the two tests below is what makes that structural rather than a promise: the path test
runs first and returns before anything is read, so no non-markdown file can ever be reported as
undecodable, whatever its bytes turn out to be.

**The cap.** Matching stops at `limit` and `truncated` says so. A caller that ignores `truncated`
reports a partial answer as a complete one, which is why it is a field and not an inference from
`len(matches) == limit` — a search finding exactly `limit` matches and no more is not truncated.
"""

from __future__ import annotations

from harness_library.application.read._access import entry_path_of, read_file_text
from harness_library.application.read.artifacts import select_artifacts, sort_artifacts
from harness_library.application.read.dtos import (
    SearchMatch,
    SearchResults,
    SearchSkipReason,
    SkippedFile,
)
from harness_library.application.read.queries import NO_FILTER, ArtifactFilter, SortKey
from harness_library.domain.artifact import Artifact, ArtifactFile
from harness_library.domain.errors import FileNotTextError, InvalidQueryError
from harness_library.domain.repository import ArtifactRepository

SEARCH_RESULT_LIMIT = 200
"""Contract C-5's cap on matches. The whole library is scanned; the answer is bounded."""

REFERENCE_DIRECTORY = "references"
"""Charter §8 names it, and ruling R4 confines the search to `.md` files inside it."""

MARKDOWN_SUFFIX = ".md"

_NOT_A_REFERENCE_MESSAGE = (
    "not a markdown reference: only the entry document and `.md` files under "
    f"`{REFERENCE_DIRECTORY}/` are searched (ruling R4)"
)


def search_artifacts(
    repository: ArtifactRepository,
    query: str,
    *,
    artifact_filter: ArtifactFilter = NO_FILTER,
    limit: int = SEARCH_RESULT_LIMIT,
) -> SearchResults:
    """Every line matching `query`, case-insensitively, across the searchable files.

    Artifacts are visited in the default listing order — ruling R8 applied, then by name — so two
    runs over one snapshot return the same matches in the same order and a truncated result set is
    reproducible rather than arbitrary.

    Raises:
        InvalidQueryError: `query` is empty or blank. Not an empty result: an empty needle is a
            substring of every line, so answering it would fill the cap from an arbitrary corner
            of the library and call the search truncated.
        CollectionNotFoundError: the filter names a collection the library does not declare.
    """
    needle = query.strip()
    if not needle:
        raise InvalidQueryError("a search query must contain at least one non-blank character")

    artifacts = sort_artifacts(
        select_artifacts(repository, repository.list_all(), artifact_filter), SortKey.NAME
    )

    matches: list[SearchMatch] = []
    skipped: list[SkippedFile] = []
    truncated = False
    lowered = needle.lower()

    for artifact in artifacts:
        entry_path = entry_path_of(artifact)
        for file in artifact.files:
            if not is_searchable(file, entry_path=entry_path):
                skipped.append(
                    SkippedFile(
                        artifact_id=artifact.id,
                        path=file.path,
                        reason=SearchSkipReason.NOT_A_MARKDOWN_REFERENCE,
                        message=_NOT_A_REFERENCE_MESSAGE,
                    )
                )
                continue
            text = _text_or_skip(repository, artifact, file, skipped)
            if text is None:
                continue
            for match in _matches_in(artifact, file, text, lowered):
                if len(matches) >= limit:
                    truncated = True
                    break
                matches.append(match)
            if truncated:
                break
        if truncated:
            break

    return SearchResults(
        query=needle,
        matches=tuple(matches),
        truncated=truncated,
        limit=limit,
        skipped=tuple(skipped),
    )


def is_searchable(file: ArtifactFile, *, entry_path: str) -> bool:
    """Ruling R4, decided from the path alone.

    From the path and not from `is_text`, which is the distinction ruling R25 turns on: the HTML
    asset is text and is still not searched, and deciding on `is_text` would have made "binary" the
    reason — the wording R25 rejects, and a diagnosis that is wrong about a UTF-8 file.
    """
    if file.path == entry_path:
        return True
    return file.path.startswith(f"{REFERENCE_DIRECTORY}/") and file.path.endswith(MARKDOWN_SUFFIX)


def _text_or_skip(
    repository: ArtifactRepository,
    artifact: Artifact,
    file: ArtifactFile,
    skipped: list[SkippedFile],
) -> str | None:
    """The file's text, or `None` after recording why it could not be read.

    Only reachable once `is_searchable` has passed, which is what confines
    `UNREADABLE_AS_TEXT` to a `.md` reference whose bytes contradict the scan.
    """
    try:
        return read_file_text(repository, artifact.id, file.path)
    except FileNotTextError:
        skipped.append(
            SkippedFile(
                artifact_id=artifact.id,
                path=file.path,
                reason=SearchSkipReason.UNREADABLE_AS_TEXT,
                message=(
                    "a markdown reference that does not decode as UTF-8, so it was not searched"
                ),
            )
        )
        return None


def _matches_in(
    artifact: Artifact, file: ArtifactFile, text: str, lowered_query: str
) -> list[SearchMatch]:
    """One match per matching line. A line matching twice is reported once."""
    return [
        SearchMatch(
            artifact_id=artifact.id,
            path=file.path,
            line_number=number,
            line_text=line.rstrip(),
        )
        for number, line in enumerate(text.splitlines(), start=1)
        if lowered_query in line.lower()
    ]


__all__ = ["SEARCH_RESULT_LIMIT", "is_searchable", "search_artifacts"]
