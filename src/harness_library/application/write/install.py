"""`PlanInstall` — everything one install would do, decided before anything is written.

**This module is in `application/write/` and that placement is the whole guarantee.** The
`mcp-is-read-only` import contract forbids `mcp/` from reaching `application.write`, and the MCP
server imports `application.read` alone. A write use case sitting in `read/` keeps `mypy`, `ruff`
and `lint-imports` all green while quietly making a read-only session able to reach the write
path — nothing in the toolchain can see the mistake, so
`tests/test_architecture.py::test_every_write_use_case_is_defined_in_the_write_package` is the one
thing that does.

**Why it is a separate symbol from `diff_against_target` rather than an alias.** Today the two
answer the same question and share one implementation — the composition lives on the read side
because `read/` may not import `write/` (see that module). What differs is what they are *for*: a
drift report describes, and this is the value `ApplyInstall` executes. Every narrowing that belongs
to acting rather than to describing lands here and must not reach the report — T-20's refusal to
apply a V11 artifact, T-21's `--resolve` per artifact. An alias would have no place to put them.

Nothing here writes either. Deciding and acting are separate steps by design (DEC-11, R57): the
plan is complete before a byte moves, so apply can refuse the whole run, and `--dry-run` is the
same code path with the last step left off.
"""

from __future__ import annotations

from harness_library.application.read.drift import diff_against_target
from harness_library.domain.install_plan import InstallPlan
from harness_library.domain.manifest import Manifest
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.target import TargetRepository


def plan_install(
    library: ArtifactRepository,
    target: TargetRepository,
    *,
    manifest: Manifest | None,
) -> InstallPlan:
    """The plan an apply would execute. Contract C-10.

    Args:
        library: contract C-4, the library being installed from.
        target: contract C-12, the directory being installed into. Only `scan()` is called;
            planning writes nothing.
        manifest: contract C-11, what was last installed into this target, or `None` when nothing
            was. **Required, with no default.** A caller that omitted it would judge every path
            `CREATE` and overwrite the whole target, which is the failure the manifest exists to
            prevent, and a default would let that be a typo rather than a decision.

    Returns:
        One `PlanEntry` per path the library, the manifest or the target holds, in path order.
        `InstallPlan.is_complete` is false when any of them awaits a human decision, and
        `counts` is dense over every verdict.

    Raises:
        ValueError: the manifest records an `artifact_id` that is not a `<type>/<name>` identity,
            so the files it names cannot be located inside the target.
    """
    return diff_against_target(library, target, manifest=manifest)


__all__ = ["plan_install"]
