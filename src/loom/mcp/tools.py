"""The tool registry — **the single source** for what this server offers.

Contract C-7 says tool names and schemas are derived from one registry, and this module is that
registry. `TOOLS` is the only enumeration of the tools that exists: `tools/list` maps over it,
`tools/call` dispatches through a mapping built from it, and both JSON schemas are *generated* from
the two Pydantic models each entry names. There is no tuple of names beside a list of schemas,
because a test comparing one constant to its neighbour passes through exactly the change it exists
to catch — and for the same reason the tests enumerate the tools by asking the running server over
the wire rather than by importing anything from here.

**`outputSchema` comes from the contract C-7 payload model, and that is load-bearing.** An MCP
client revalidates every successful result against the schema the server declared, so "the MCP
server renders the same payload `loom --json` does" stops being a promise and becomes something the
client itself enforces. `Payload` is `extra="forbid"`, so the generated schema forbids a field
nobody declared: `get_reference` returns a `FileContent`, which has no field for its parent's entry
text and whose schema would reject one.

**This layer decides nothing.** Filtering, ordering, ruling R8's ranking and the search cap were all
decided in `application/read` and proven there; a handler here converts arguments into that
vocabulary and returns what comes back.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from loom.application.read import (
    ArtifactDetail,
    ArtifactFilter,
    ArtifactListPayload,
    FileContent,
    Payload,
    SearchResults,
    SortKey,
    get_artifact,
    get_artifact_file,
    list_artifacts,
    search_artifacts,
)
from loom.domain.identity import ArtifactType
from loom.domain.repository import ArtifactRepository


class ToolArguments(BaseModel):
    """Base of every tool's argument model — what a *client* sends.

    Kept apart from contract C-7, which is what a client gets back: the two travel in opposite
    directions and are frozen for different reasons. `extra="forbid"` means a misspelt argument is
    a reported error rather than a silently ignored one, which is the difference between a client
    author finding a typo now and wondering later why a filter did nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class FilterArguments(ToolArguments):
    """The narrowing every artifact-shaped tool accepts, spelled once.

    One model, so `list_artifacts` and `search_artifacts` cannot drift into offering different
    filters over the same library. It mirrors `application.read.ArtifactFilter` field for field and
    converts to it rather than re-deciding anything.

    Attributes:
        type: only artifacts of this type.
        tag: only artifacts carrying this tag in `library.yaml`.
        collection: only members of this collection, by key. A key the library does not declare is
            an error, not an empty answer (charter §13).
    """

    type: ArtifactType | None = Field(default=None, description="Only artifacts of this type.")
    tag: str | None = Field(default=None, description="Only artifacts carrying this tag.")
    collection: str | None = Field(
        default=None, description="Only members of this collection, by key."
    )

    def to_filter(self, **overrides: Any) -> ArtifactFilter:
        """The application-layer filter this narrowing means."""
        return ArtifactFilter(type=self.type, tag=self.tag, collection=self.collection, **overrides)


class ListArtifactsArguments(FilterArguments):
    """Arguments of `list_artifacts`.

    Attributes:
        invalid_only: only artifacts carrying an ERROR finding.
        include_superseded: ruling R8 — superseded artifacts are listed **by default** and ranked
            below their successors. The argument exists so a client can narrow deliberately, not so
            the default can drift.
        sort: the ordering. Ruling R8 sits above it whatever it is.
    """

    invalid_only: bool = Field(
        default=False, description="Only artifacts with at least one ERROR finding."
    )
    include_superseded: bool = Field(
        default=True,
        description="Include superseded artifacts, ranked below their successors (default true).",
    )
    sort: SortKey = Field(default=SortKey.NAME, description="Ordering of the listing.")


class SearchArtifactsArguments(FilterArguments):
    """Arguments of `search_artifacts`.

    Attributes:
        query: the text to look for, matched case-insensitively. Blank is an error rather than a
            match against everything.
    """

    query: str = Field(description="Text to look for, matched case-insensitively.")


class GetArtifactArguments(ToolArguments):
    """Arguments of `get_artifact`.

    Attributes:
        artifact_id: the canonical `<type>/<name>` identity, as `list_artifacts` reports it.
    """

    artifact_id: str = Field(description="The artifact's `<type>/<name>` id.")


class GetReferenceArguments(ToolArguments):
    """Arguments of `get_reference`.

    Attributes:
        artifact_id: the artifact holding the reference.
        path: the file, relative to the artifact root — for example `references/checklist.md`.
    """

    artifact_id: str = Field(description="The artifact's `<type>/<name>` id.")
    path: str = Field(
        description="The file to fetch, relative to the artifact root, e.g. `references/note.md`."
    )


@dataclass(frozen=True, slots=True)
class ToolSpec[ArgumentsT: ToolArguments, PayloadT: Payload]:
    """One tool: its name, its prose, its two schemas and the handler that joins them.

    Both schemas are *generated* — `input_schema` from `arguments`, `output_schema` from the
    contract C-7 `payload` model — so a tool cannot advertise a shape it does not produce.

    Attributes:
        name: the wire name a client calls.
        title: a short human label.
        description: what the tool is for, as a model reads it before choosing.
        arguments: the model a client's arguments are validated against.
        payload: the contract C-7 model the handler returns. Its schema is what the client
            revalidates the result against.
        handler: the call itself, over a ready repository. Synchronous, because every read use case
            is.
    """

    name: str
    title: str
    description: str
    arguments: type[ArgumentsT]
    payload: type[PayloadT]
    handler: Callable[[ArtifactRepository, ArgumentsT], PayloadT]

    @property
    def input_schema(self) -> dict[str, Any]:
        """The JSON schema of this tool's arguments, generated from the model."""
        return self.arguments.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        """The JSON schema of this tool's result, generated from the contract C-7 model."""
        return self.payload.model_json_schema()

    def invoke(self, repository: ArtifactRepository, arguments: dict[str, Any]) -> Payload:
        """Validate raw arguments and run the tool.

        Raises:
            pydantic.ValidationError: the arguments do not match `arguments`.
            HarnessLibraryError: whatever the use case raises — ruling R24's taxonomy, which
                `mcp.dispatch` turns into an MCP error result rather than an exception across the
                pipe.
        """
        return self.handler(repository, self.arguments.model_validate(arguments))


def _list_artifacts(
    repository: ArtifactRepository, arguments: ListArtifactsArguments
) -> ArtifactListPayload:
    return list_artifacts(
        repository,
        artifact_filter=arguments.to_filter(
            invalid_only=arguments.invalid_only,
            include_superseded=arguments.include_superseded,
        ),
        sort_key=arguments.sort,
    )


def _search_artifacts(
    repository: ArtifactRepository, arguments: SearchArtifactsArguments
) -> SearchResults:
    return search_artifacts(repository, arguments.query, artifact_filter=arguments.to_filter())


def _get_artifact(
    repository: ArtifactRepository, arguments: GetArtifactArguments
) -> ArtifactDetail:
    return get_artifact(repository, arguments.artifact_id)


def _get_reference(repository: ArtifactRepository, arguments: GetReferenceArguments) -> FileContent:
    return get_artifact_file(repository, arguments.artifact_id, arguments.path)


TOOLS: tuple[ToolSpec[Any, Any], ...] = (
    ToolSpec(
        name="list_artifacts",
        title="List artifacts",
        description=(
            "List the skills and agents in the library, with their tags, validation findings and "
            "metadata. Superseded artifacts are included by default and ranked below their "
            "successors; invalid ones are included too, carrying the findings that explain why. "
            "Start here to discover what exists before fetching anything."
        ),
        arguments=ListArtifactsArguments,
        payload=ArtifactListPayload,
        handler=_list_artifacts,
    ),
    ToolSpec(
        name="search_artifacts",
        title="Search artifacts",
        description=(
            "Find a phrase across the library's entry documents and their markdown references, "
            "returning the artifact, the file, the line number, the matching line and the one "
            "line either side of it — each null when the match sits at the start or the end of "
            "the file, never an empty string. Files that were not searched are reported with the "
            "reason, so an omission is visible rather than silent, and a result set that reached "
            "the cap is marked truncated."
        ),
        arguments=SearchArtifactsArguments,
        payload=SearchResults,
        handler=_search_artifacts,
    ),
    ToolSpec(
        name="get_artifact",
        title="Get one artifact",
        description=(
            "Fetch one artifact in full: its entry document, its frontmatter, its file list and "
            "its validation findings. An artifact with faults is returned with them attached "
            "rather than refused. Prefer `get_reference` when you need a single reference file — "
            "the entry document of a reference-heavy skill can run to hundreds of lines."
        ),
        arguments=GetArtifactArguments,
        payload=ArtifactDetail,
        handler=_get_artifact,
    ),
    ToolSpec(
        name="get_reference",
        title="Get one reference file",
        description=(
            "Fetch a single file from inside an artifact — typically one document under "
            "`references/` — **without** its parent's entry text. These skills are "
            "reference-heavy: one runs to 718 lines before its seven references, so a session "
            "that needs a single reference must not have to read the whole artifact to get it."
        ),
        arguments=GetReferenceArguments,
        payload=FileContent,
        handler=_get_reference,
    ),
)
"""Every tool this server offers, and the only place any of them is named.

Four, deliberately. A fifth is a plan-level decision, and a fifth that reached for
`application.write` would break the `mcp-is-read-only` import contract and fail the suite — which
is what makes the read-only guarantee structural rather than a promise.
"""

TOOLS_BY_NAME: dict[str, ToolSpec[Any, Any]] = {tool.name: tool for tool in TOOLS}
"""Dispatch index, built from `TOOLS`. Derived, never maintained."""


__all__ = [
    "TOOLS",
    "TOOLS_BY_NAME",
    "FilterArguments",
    "GetArtifactArguments",
    "GetReferenceArguments",
    "ListArtifactsArguments",
    "SearchArtifactsArguments",
    "ToolArguments",
    "ToolSpec",
]
