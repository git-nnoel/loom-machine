"""`PlanInstall` — the write-side use case. T-15.

What is asserted *here* rather than in `test_drift.py` is what belongs to the write side: that the
plan is decided without touching the target, and that a caller cannot reach it without saying what
the manifest is. The composition itself is proven once, next to the join.

Where the function is **defined** is asserted in `tests/test_architecture.py`, which is the only
thing in this project that can see it: `mypy`, `ruff` and `lint-imports` all stay green when a
write use case is moved into `application/read/`.
"""

from __future__ import annotations

import inspect

import pytest

from harness_library.application.read.drift import diff_against_target
from harness_library.application.write import plan_install
from harness_library.domain.install_plan import Verdict
from tests.application.fakes import (
    FakeArtifactRepository,
    FakeTargetRepository,
    make_artifact,
    make_file,
    manifest_artifact,
    manifest_of,
    target_file,
)

SKILL_NAME = "delivery-lead"
SKILL_ID = "skill/delivery-lead"
ENTRY = "SKILL.md"
INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"

LIBRARY_BYTES = b"# the library has moved on\n"
INSTALLED_BYTES = b"# what this tool installed\n"


@pytest.mark.parametrize("use_case", [plan_install, diff_against_target], ids=lambda f: f.__name__)
def test_the_manifest_must_be_passed_and_has_no_default(use_case: object) -> None:
    """A caller that omitted the manifest would judge every path `CREATE` and overwrite the whole
    target — the one catastrophe the manifest exists to prevent. A default would make that a typo
    rather than a decision, so `manifest` is keyword-only and required.

    `None` remains a value it accepts: a first install into a target nothing was installed into.
    """
    parameter = inspect.signature(use_case).parameters["manifest"]  # type: ignore[arg-type]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_planning_an_install_writes_nothing_to_the_target() -> None:
    """Deciding and acting are separate steps (DEC-11, R57): the plan is complete before a byte
    moves, which is what lets apply refuse the whole run and what makes `--dry-run` this same
    code path with the last step left off.

    The positive control is in the same test: the fake does record a write when one is made.
    """
    target = FakeTargetRepository((target_file(INSTALLED_ENTRY, INSTALLED_BYTES),))
    library = FakeArtifactRepository(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))]
    )

    plan = plan_install(library, target, manifest=None)

    assert plan.entries != ()
    assert target.writes == []
    assert target.deletes == []

    target.write("proof.md", b"the recorder works\n")
    assert target.writes == [("proof.md", b"the recorder works\n")]


def test_a_plan_over_three_agreeing_sources_proposes_nothing_and_is_complete() -> None:
    """F-8: `hl diff` on an untouched target reports `UNCHANGED` for every path and exits 0. The
    exit status is T-22's; what this layer owes it is a complete plan of unchanged entries."""
    files = (make_file(ENTRY, INSTALLED_BYTES), make_file("references/a.md", b"a\n"))
    plan = plan_install(
        FakeArtifactRepository([make_artifact(SKILL_NAME, files=files)]),
        FakeTargetRepository(
            (
                target_file(INSTALLED_ENTRY, INSTALLED_BYTES),
                target_file("skills/delivery-lead/references/a.md", b"a\n"),
            )
        ),
        manifest=manifest_of(manifest_artifact(SKILL_ID, files)),
    )

    assert [entry.verdict for entry in plan.entries] == [Verdict.UNCHANGED, Verdict.UNCHANGED]
    assert plan.is_complete
    assert plan.counts[Verdict.UNCHANGED] == 2
