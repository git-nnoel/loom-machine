"""Feature F-6's first half — what a real client handshake finds, **read from the server**.

Every assertion here starts from a `tools/list` answer that came over the wire from a live
process. Nothing is compared against a constant imported from `loom.mcp`: a test that
checked one constant against its neighbour would pass through exactly the change it exists to
catch — rename a tool in the registry and the "expected" tuple next to it renames itself.

The four names below are the *specification's* four (plan §2, feature F-6), written out by hand
here on purpose. They are the one thing this file does not read from the code.
"""

from __future__ import annotations

from pathlib import Path

from mcp.client.session import ClientSession
from mcp.types import ListToolsResult

from tests.mcp.conftest import handshake_frames, speak, with_client

THE_FOUR_TOOLS = ("get_artifact", "get_reference", "list_artifacts", "search_artifacts")
"""Feature F-6, transcribed from the plan. Sorted, so the comparison does not depend on order."""


def _list_tools(library: Path) -> ListToolsResult:
    async def work(session: ClientSession) -> ListToolsResult:
        return await session.list_tools()

    return with_client(library, work)


def test_a_real_client_handshake_enumerates_exactly_the_four_tools(fixture_library: Path) -> None:
    """Feature F-6. A real handshake, a real `tools/list`, and exactly four tools come back.

    A fifth tool fails this test, which is the point: four is a plan-level decision, not something
    a task may quietly extend."""
    result = _list_tools(fixture_library)

    assert tuple(sorted(tool.name for tool in result.tools)) == THE_FOUR_TOOLS


def test_every_advertised_tool_carries_prose_and_both_schemas(fixture_library: Path) -> None:
    """Whatever the server advertises must be usable by a model that has only this listing.

    Written over the enumeration rather than over a list of names, so a tool added tomorrow is held
    to the same standard without anyone remembering to add it here."""
    result = _list_tools(fixture_library)

    for tool in result.tools:
        assert tool.description, f"{tool.name} advertises no description"
        assert tool.input_schema.get("type") == "object", f"{tool.name} has no object input schema"
        assert tool.output_schema is not None, (
            f"{tool.name} declares no output schema, so a client cannot revalidate its result "
            "against contract C-7"
        )
        assert tool.annotations is not None and tool.annotations.read_only_hint is True, (
            f"{tool.name} does not announce itself as read-only"
        )


def test_no_advertised_output_schema_admits_a_field_nobody_declared(fixture_library: Path) -> None:
    """Contract C-7's `extra="forbid"` reaches the wire.

    This is what makes `get_reference`'s isolation structural: the declared schema for its result
    has no place to put a parent's entry text, and would reject one if a payload grew a field."""
    result = _list_tools(fixture_library)

    for tool in result.tools:
        assert tool.output_schema is not None
        assert tool.output_schema.get("additionalProperties") is False, (
            f"{tool.name}'s output schema admits undeclared fields"
        )


def test_the_tools_the_server_lists_are_the_tools_the_server_answers(fixture_library: Path) -> None:
    """The listing and the dispatcher are one registry, proven by asking the server both ways.

    A name that lists but does not dispatch — the failure a hand-maintained name tuple beside a
    schema list produces — would show up here as an "unknown tool" error result."""
    listed = tuple(sorted(tool.name for tool in _list_tools(fixture_library).tools))

    frames = [
        *handshake_frames(),
        *(
            {
                "jsonrpc": "2.0",
                "id": index + 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            }
            for index, name in enumerate(listed)
        ),
    ]
    conversation = speak(frames, library=fixture_library)

    for index, name in enumerate(listed):
        text = conversation.result(index + 2)["content"][0]["text"]
        assert "no such tool" not in text, f"{name} is listed but does not dispatch"
