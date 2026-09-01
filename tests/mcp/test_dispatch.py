"""The dispatcher on its own — the branches a wire test cannot reach cheaply.

`call_tool` is synchronous, so these need no event loop, no subprocess and no client. What they
prove is the shape of the two failures that belong to the *client* rather than to the library: a
tool name nobody offers, and arguments that do not match the tool's model. Neither has a code in
the taxonomy, and charter §9 forbids inventing one at a raise site — so both come back with a null
code, exactly as `LibraryRootError` did before ruling R29 put its condition in the contract.

The repository is real: `infrastructure/` is tested against real files (charter §10), and building
one over the committed fixture library keeps these tests honest about what a tool actually returns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent

from harness_library.infrastructure.repository import FilesystemArtifactRepository
from harness_library.mcp import TOOLS, TOOLS_BY_NAME, call_tool


def envelope_of(result: CallToolResult) -> dict[str, Any]:
    block = result.content[0]
    assert isinstance(block, TextContent)
    error: dict[str, Any] = json.loads(block.text)["error"]
    return error


def test_an_unknown_tool_name_is_an_error_result_naming_what_is_on_offer(
    fixture_library: Path,
) -> None:
    """A client mistake, answered rather than raised — and answered usefully.

    The message lists the real tools, read from the registry, so a client author sees the correct
    name instead of being told only that theirs was wrong."""
    repository = FilesystemArtifactRepository(fixture_library)

    result = call_tool(repository, "delete_everything", {})

    assert result.is_error is True
    envelope = envelope_of(result)
    assert envelope["code"] is None
    for tool in TOOLS:
        assert tool.name in envelope["message"]


def test_arguments_that_do_not_match_the_tools_model_are_reported(fixture_library: Path) -> None:
    """`extra="forbid"` reaching the wire: a misspelt argument is a reported mistake, not a filter
    that silently did nothing. The alternative is a client author who never learns their typo."""
    repository = FilesystemArtifactRepository(fixture_library)

    result = call_tool(repository, "list_artifacts", {"tpye": "agent"})

    assert result.is_error is True
    assert envelope_of(result)["code"] is None
    assert "tpye" in envelope_of(result)["message"]


def test_a_missing_required_argument_is_reported_rather_than_guessed(
    fixture_library: Path,
) -> None:
    """The positive control for the test above: a *different* argument mistake is also caught, so
    the model is validating rather than rejecting everything that is not the happy path."""
    repository = FilesystemArtifactRepository(fixture_library)

    result = call_tool(repository, "get_artifact", {})

    assert result.is_error is True
    assert "artifact_id" in envelope_of(result)["message"]


def test_the_dispatch_index_is_derived_from_the_registry(fixture_library: Path) -> None:
    """The index is `TOOLS` re-keyed and nothing else.

    Asserted as an identity between the two structures rather than against a written-out list: this
    is the one place a hand-maintained name tuple could hide, and there is nothing here to
    maintain."""
    assert {tool.name: tool for tool in TOOLS} == TOOLS_BY_NAME
    assert len(TOOLS_BY_NAME) == len(TOOLS), "two tools share a name; one is unreachable"
