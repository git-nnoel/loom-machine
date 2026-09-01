"""Feature F-6's second half — each tool returns its documented payload, over a real client.

These calls go through the MCP SDK's own client, which **revalidates every successful result
against the `outputSchema` the server declared**. That is not incidental: the declared schema is
generated from the contract C-7 model, so a payload this adapter rebuilt by hand, or grew a field
on, fails inside `call_tool` before any assertion here runs. Contract C-7 is enforced by the
protocol rather than by our reading of it.

Nothing here re-asserts a rule, an order or a skip reason. Those were decided in
`application/read` and are proven there; a second suite asserting them at this layer would fail for
reasons that have nothing to do with the MCP server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.types import CallToolResult, TextContent

from tests.mcp.conftest import with_client

ENTRY_SENTENCE = "The dispatch checklist lives in references/checklist.md"
"""A sentence that appears **only** in `skill/delivery-lead`'s entry document, never in its
reference. It is the needle both halves of the `get_reference` isolation pair look for."""

REFERENCE_SENTENCE = "Name the mutation before the run."
"""A sentence that appears only in that skill's `references/checklist.md`."""


def call(library: Path, name: str, arguments: dict[str, Any]) -> CallToolResult:
    """One `tools/call` over a real session."""

    async def work(session: ClientSession) -> CallToolResult:
        result = await session.call_tool(name, arguments)
        assert isinstance(result, CallToolResult)
        return result

    return with_client(library, work)


def text_of(result: CallToolResult) -> str:
    """The result's text block, which is what a client without structured support reads."""
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


def payload_of(result: CallToolResult) -> dict[str, Any]:
    """The result's payload, asserting it did not come back as an error.

    Both renderings are checked against each other: the text block and the structured content are
    the *same* payload, so a client reading either gets the same answer."""
    assert result.is_error is False, f"the tool answered with an error: {text_of(result)}"
    structured: dict[str, Any] = result.structured_content or {}
    assert json.loads(text_of(result)) == structured, (
        "the text block and the structured content disagree; they are one payload rendered twice"
    )
    return structured


def error_of(result: CallToolResult) -> dict[str, Any]:
    """The error envelope from an errored result. The same shape the CLI writes to stderr."""
    assert result.is_error is True, f"expected an error result, got: {text_of(result)}"
    envelope: dict[str, Any] = json.loads(text_of(result))["error"]
    return envelope


def test_list_artifacts_returns_the_whole_library(fixture_library: Path) -> None:
    """The listing a client starts from, including the invalid artifacts (feature F-1)."""
    payload = payload_of(call(fixture_library, "list_artifacts", {}))

    assert payload["total"] == len(payload["artifacts"]) > 0
    assert "skill/no-entry" in {artifact["id"] for artifact in payload["artifacts"]}


def test_list_artifacts_narrows_on_the_arguments_it_advertises(fixture_library: Path) -> None:
    """The filter reaches the use case. Not a test of *which* artifacts match — that is decided
    and proven below — but that the argument is carried rather than dropped."""
    everything = payload_of(call(fixture_library, "list_artifacts", {}))
    agents = payload_of(call(fixture_library, "list_artifacts", {"type": "agent"}))

    assert {artifact["type"] for artifact in agents["artifacts"]} == {"agent"}
    assert 0 < agents["total"] < everything["total"]


def test_search_artifacts_finds_a_phrase_and_reports_what_it_skipped(fixture_library: Path) -> None:
    """Feature F-3 as a client meets it: matches with a path and a line number, and the files that
    were passed over reported rather than silently omitted (ruling R4)."""
    payload = payload_of(call(fixture_library, "search_artifacts", {"query": "checklist"}))

    assert payload["matches"], "the fixture library contains this phrase"
    first = payload["matches"][0]
    assert first["line_number"] >= 1
    assert isinstance(first["path"], str)
    assert payload["truncated"] is False
    assert all(skipped["reason"] != "binary" for skipped in payload["skipped"])


def test_get_artifact_returns_one_artifact_in_full(fixture_library: Path) -> None:
    """Feature F-2, and the **positive control** for the isolation test below: the parent's entry
    sentence is reachable through `get_artifact`, so a test asserting its absence elsewhere is
    asserting something that can actually be there."""
    payload = payload_of(
        call(fixture_library, "get_artifact", {"artifact_id": "skill/delivery-lead"})
    )

    assert payload["id"] == "skill/delivery-lead"
    assert payload["entry_text"] is not None
    assert ENTRY_SENTENCE in payload["entry_text"]


def test_get_artifact_shows_a_broken_artifact_with_its_findings(fixture_library: Path) -> None:
    """A skill with no `SKILL.md` is *shown*, not refused (feature F-2). The whole point of this
    product is that a fault is visible; a tool that raised on one would hide it."""
    payload = payload_of(call(fixture_library, "get_artifact", {"artifact_id": "skill/no-entry"}))

    assert payload["entry_text"] is None
    assert [finding["code"] for finding in payload["findings"]] == ["V1"]


def test_get_reference_returns_one_reference(fixture_library: Path) -> None:
    """The tool's reason for existing: one file, fetched on its own."""
    payload = payload_of(
        call(
            fixture_library,
            "get_reference",
            {"artifact_id": "skill/delivery-lead", "path": "references/checklist.md"},
        )
    )

    assert payload["path"] == "references/checklist.md"
    assert payload["is_text"] is True
    assert REFERENCE_SENTENCE in payload["text"]


def test_get_reference_cannot_carry_its_parents_entry_text(fixture_library: Path) -> None:
    """Feature F-6, the assertion of absence — with the positive control above.

    Two things are asserted, and the second is the stronger one. The parent's entry sentence is not
    in the answer *anywhere* (it is reachable through `get_artifact`, so the assertion can fail),
    and the payload has **no field it could ever occupy**: contract C-7's `FileContent` declares
    six fields and the advertised output schema forbids a seventh. The isolation is structural, not
    a matter of this handler remembering to leave something out."""
    result = call(
        fixture_library,
        "get_reference",
        {"artifact_id": "skill/delivery-lead", "path": "references/checklist.md"},
    )
    payload = payload_of(result)

    assert ENTRY_SENTENCE not in text_of(result)
    assert set(payload) == {"artifact_id", "path", "sha256", "size", "is_text", "text"}


def test_an_unknown_artifact_id_comes_back_as_an_error_result(fixture_library: Path) -> None:
    """Ruling R24: the taxonomy crosses the pipe as a **result**, not as an exception.

    An exception here would reach the client as a transport-level fault with nothing in it to
    branch on. The code is the branchable value; the message is prose."""
    result = call(fixture_library, "get_artifact", {"artifact_id": "skill/does-not-exist"})

    assert error_of(result)["code"] == "ARTIFACT_NOT_FOUND"


def test_an_unknown_reference_path_is_distinguished_from_an_unknown_artifact(
    fixture_library: Path,
) -> None:
    """The **positive control** for the code above: a different mistake gets a different code, so
    `ARTIFACT_NOT_FOUND` is a diagnosis rather than the one answer everything gets."""
    result = call(
        fixture_library,
        "get_reference",
        {"artifact_id": "skill/delivery-lead", "path": "references/nowhere.md"},
    )

    assert error_of(result)["code"] == "FILE_NOT_FOUND"


def test_a_blank_search_query_is_an_error_result_not_an_arbitrary_answer(
    fixture_library: Path,
) -> None:
    """An empty needle matches every line, so answering it would fill the cap from an arbitrary
    corner of the library and call the result truncated — confidently wrong."""
    result = call(fixture_library, "search_artifacts", {"query": "   "})

    assert error_of(result)["code"] == "INVALID_QUERY"
