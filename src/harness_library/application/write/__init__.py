"""Write use cases — everything that decides to change a user's harness.

**This package exists to be forbidden.** The `mcp-is-read-only` import contract names it, and
`mcp/` may not reach it directly or through anything it does import. That is the mechanism behind
"an MCP session cannot mutate the user's harness"; it is not a promise made in prose.

The contract cannot, however, tell whether a *given* use case belongs here. Moving one of these
functions into `application/read/` leaves `mypy`, `ruff` and `lint-imports` all green and erodes
the guarantee silently, so `tests/test_architecture.py` asserts the module each name is defined in.

Initiative 01 left this package empty by design. T-15 fills it with the first entry.
"""

from harness_library.application.write.install import plan_install

__all__ = ["plan_install"]
