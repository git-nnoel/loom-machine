"""Write use cases — everything that decides to change a user's harness.

**This package exists to be forbidden.** The `mcp-is-read-only` import contract names it, and
`mcp/` may not reach it directly or through anything it does import. That is the mechanism behind
"an MCP session cannot mutate the user's harness"; it is not a promise made in prose.

The contract cannot, however, tell whether a *given* use case belongs here. Moving one of these
functions into `application/read/` leaves `mypy`, `ruff` and `lint-imports` all green and erodes
the guarantee silently, so `tests/test_architecture.py` asserts the module each name is defined in.

Initiative 01 left this package empty by design. T-15 fills it with the first entry, T-16 adds the
one that actually writes, T-18 adds the two that undo it — `rollback_install`, which puts a target
back from the backup apply refused to run without, and `uninstall_artifact`, which removes exactly
what the manifest records for one artifact — and T-19 adds the two that remove what no longer
belongs: `prune_target` for what the library dropped, and `clean_foreign` for what neither the
library nor the manifest ever claimed. One module each rather than six functions in `install.py`:
apply reads a library and builds nothing else, rollback reads a backup and never a library,
uninstall reads neither, prune reads a plan and no library, and clean reads a plan and removes
files nothing in this project has any other record of.

Two things every one of them shares: the lock (C-16, R82), and the rule that decides which end of
the run the record goes at (charter §13b, R86). Apply's goes first because apply makes files
appear; the other four make files disappear and record last.
"""

from harness_library.application.write.clean import CleanResult, clean_foreign, foreign_entries
from harness_library.application.write.install import ApplyResult, apply_install, plan_install
from harness_library.application.write.prune import PruneResult, prune_target, pruned_entries
from harness_library.application.write.rollback import RollbackResult, rollback_install
from harness_library.application.write.uninstall import UninstallResult, uninstall_artifact

__all__ = [
    "ApplyResult",
    "CleanResult",
    "PruneResult",
    "RollbackResult",
    "UninstallResult",
    "apply_install",
    "clean_foreign",
    "foreign_entries",
    "plan_install",
    "prune_target",
    "pruned_entries",
    "rollback_install",
    "uninstall_artifact",
]
