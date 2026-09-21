"""Write use cases — everything that decides to change a user's harness.

**This package exists to be forbidden.** The `mcp-is-read-only` import contract names it, and
`mcp/` may not reach it directly or through anything it does import. That is the mechanism behind
"an MCP session cannot mutate the user's harness"; it is not a promise made in prose.

The contract cannot, however, tell whether a *given* use case belongs here. Moving one of these
functions into `application/read/` leaves `mypy`, `ruff` and `lint-imports` all green and erodes
the guarantee silently, so `tests/test_architecture.py` asserts the module each name is defined in.

Initiative 01 left this package empty by design. T-15 fills it with the first entry, T-16 adds the
one that actually writes, and T-18 adds the two that undo it — `rollback_install`, which puts a
target back from the backup apply refused to run without, and `uninstall_artifact`, which removes
exactly what the manifest records for one artifact. One module each rather than four functions in
`install.py`: apply reads a library and builds nothing else, rollback reads a backup and never a
library, and uninstall reads neither. The one thing all three share is the lock (C-16, R82).
"""

from harness_library.application.write.install import ApplyResult, apply_install, plan_install
from harness_library.application.write.rollback import RollbackResult, rollback_install
from harness_library.application.write.uninstall import UninstallResult, uninstall_artifact

__all__ = [
    "ApplyResult",
    "RollbackResult",
    "UninstallResult",
    "apply_install",
    "plan_install",
    "rollback_install",
    "uninstall_artifact",
]
