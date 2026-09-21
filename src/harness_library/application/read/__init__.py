"""Read use cases and the presentation DTOs every adapter renders from.

This is the surface T-7's CLI and T-8's MCP server are written against, and the last layer where a
behaviour is decided: filtering, ordering, ruling R8's ranking, the search cap and ruling R24's
error translation all happen *here*, so an adapter renders and does nothing else. Two adapters that
each computed an ordering would be two answers to one question.

Everything a caller needs is re-exported, so an adapter imports from `harness_library.application.
read` and never has to know which module a name lives in — the module split is this package's
business, not its callers'.

**`mcp/` imports this package and no other use-case package.** That is what the `mcp-is-read-only`
contract enforces, and it is why `drift.py` — which composes a library, a manifest and a target
into an install plan — lives here rather than beside the use case that acts on the result: the
contract follows indirect imports, so a `read → write` edge would break it through this file.
Composing a plan writes nothing; `application/write/` owns the decision to act on one.
"""

from harness_library.application.read.artifacts import (
    get_artifact,
    get_artifact_file,
    list_artifacts,
    select_artifacts,
    sort_artifacts,
)
from harness_library.application.read.collections import get_collection, list_collections
from harness_library.application.read.drift import (
    UNHASHED_TARGET_SHA,
    diff_against_target,
    target_sha_of,
)
from harness_library.application.read.dtos import (
    ArtifactDetail,
    ArtifactListPayload,
    ArtifactSummary,
    ArtifactValidation,
    CollectionDetail,
    CollectionListPayload,
    CollectionSummary,
    FileContent,
    FilePayload,
    FindingPayload,
    Payload,
    SearchMatch,
    SearchResults,
    SearchSkipReason,
    SkippedFile,
    ValidationReport,
)
from harness_library.application.read.queries import NO_FILTER, ArtifactFilter, SortKey
from harness_library.application.read.search import SEARCH_RESULT_LIMIT, search_artifacts
from harness_library.application.read.validation import validate_library

__all__ = [
    "NO_FILTER",
    "SEARCH_RESULT_LIMIT",
    "UNHASHED_TARGET_SHA",
    "ArtifactDetail",
    "ArtifactFilter",
    "ArtifactListPayload",
    "ArtifactSummary",
    "ArtifactValidation",
    "CollectionDetail",
    "CollectionListPayload",
    "CollectionSummary",
    "FileContent",
    "FilePayload",
    "FindingPayload",
    "Payload",
    "SearchMatch",
    "SearchResults",
    "SearchSkipReason",
    "SkippedFile",
    "SortKey",
    "ValidationReport",
    "diff_against_target",
    "get_artifact",
    "get_artifact_file",
    "get_collection",
    "list_artifacts",
    "list_collections",
    "search_artifacts",
    "select_artifacts",
    "sort_artifacts",
    "target_sha_of",
    "validate_library",
]
