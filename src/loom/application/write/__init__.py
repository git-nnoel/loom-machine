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
files nothing in this project has any other record of. T-21 adds the two that settle a refusal —
`resolve_conflict`, which takes one side of one artifact's conflict, and `compare_versions`, which
shows both and decides nothing.

Two things every one of them shares: the lock (C-16, R82), and the rule that decides which end of
the run the record goes at (charter §13b, R86). Apply's goes first because apply makes files
appear, and so does `resolve library`'s; the four that make files disappear record last;
`resolve target` moves no file at all, so the record is its whole run and there is no end to
choose — see `resolve.py`, which argues it.

**`compare_versions` mutates nothing and is here anyway.** This package is the mechanism behind
"an MCP session cannot mutate the user's harness", and that contract is a statement about a
*package*: launching a subprocess editor on the user's machine is not something a read-only
session should be able to reach, whatever it does afterwards.
"""

from loom.application.write.clean import CleanResult, clean_foreign, foreign_entries
from loom.application.write.install import ApplyResult, apply_install, plan_install
from loom.application.write.prune import PruneResult, prune_target, pruned_entries
from loom.application.write.resolve import (
    ComparisonResult,
    ResolveResult,
    compare_versions,
    resolve_conflict,
)
from loom.application.write.rollback import RollbackResult, rollback_install
from loom.application.write.uninstall import UninstallResult, uninstall_artifact

__all__ = [
    "ApplyResult",
    "CleanResult",
    "ComparisonResult",
    "PruneResult",
    "ResolveResult",
    "RollbackResult",
    "UninstallResult",
    "apply_install",
    "clean_foreign",
    "compare_versions",
    "foreign_entries",
    "plan_install",
    "prune_target",
    "pruned_entries",
    "resolve_conflict",
    "rollback_install",
    "uninstall_artifact",
]
