"""What `loom list` pays before it reads a byte of the library.

Every other module in this suite goes through Typer's runner, which is charter §10's rule for an
adapter. This one cannot: `sys.modules` is process-global and pytest has already imported half the
project, so the question "did importing the CLI pull the MCP SDK in" is unanswerable inside the test
process. Each probe therefore runs in a **fresh interpreter** and reports what it loaded.

**Asserted on the module set, never on elapsed time.** T-9 measured the cost — 1.81 s to import
`cli.main`, of which 1.3 s was an MCP SDK only `loom mcp` touches, against a 16 ms scan — but a
timing assertion is flaky by construction and gets deleted by whoever meets it on a slow machine.
The module set is the same guarantee, decided rather than sampled.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

PROBE = """
import sys
{statement}
loaded = sorted(
    name
    for name in sys.modules
    if name == "mcp" or name.startswith("mcp.") or name.startswith("mcp_types")
)
print(len(loaded))
"""
"""Import one thing in a clean interpreter, then count the MCP modules it dragged along."""


def mcp_modules_after(statement: str) -> int:
    """How many MCP modules a fresh interpreter holds after running `statement`."""
    completed = subprocess.run(
        [sys.executable, "-c", PROBE.format(statement=statement)],
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ),
    )
    if completed.returncode != 0:  # pragma: no cover - a broken probe, not a finding
        pytest.fail(f"the import probe failed:\n{completed.stdout}\n{completed.stderr}")
    return int(completed.stdout.strip())


def test_importing_the_cli_does_not_import_the_mcp_sdk() -> None:
    """Named in advance as the assertion that MUST FAIL when the module-scope import is restored.

    `loom list`, `loom show`, `loom search`, `loom validate` and `loom collections` all reach the
    interpreter through this one module. None of them speaks MCP, and the import they used to pay
    for was 59 % of what a user waited for.
    """
    assert mcp_modules_after("import loom.cli.main") == 0


def test_the_probe_can_see_the_sdk_when_it_is_imported() -> None:
    """The positive control. Without it, a typo in the module-name filter would make every import
    look clean and the assertion above would be unfalsifiable."""
    assert mcp_modules_after("import loom.mcp") > 0


def test_the_mcp_command_still_reaches_serve_stdio() -> None:
    """The deferral must not have turned the import into a dead reference.

    This resolves the same name `mcp_command` resolves, from a clean interpreter, and proves the
    module path in the function body still exists. That `loom mcp` then *works* is proven where it
    should be — `tests/mcp/`, over real JSON-RPC frames against a spawned process.
    """
    assert mcp_modules_after("from loom.mcp import serve_stdio") > 0
