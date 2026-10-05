"""Contracts C-9 and C-10 — the install verdict and the plan that carries it.

Every verdict is asserted **as a verdict value**, never as a count or a boolean: a criterion that
names a thing rather than a value is one no test can fail, and initiatives 03 and 04 branch on
these values.
"""

from __future__ import annotations

import itertools

import pytest

from loom.domain.install_plan import (
    BLOCKING_VERDICTS,
    EXPLAINED_VERDICTS,
    RESOLVABLE_VERDICTS,
    VERDICT_BY_EQUALITY,
    InstallPlan,
    PlanEntry,
    Verdict,
    decide_verdict,
    plan_entry_for,
    verdict_for_equalities,
)

SHA_A = "a1" * 32
SHA_B = "b2" * 32
SHA_C = "c3" * 32
"""Three distinct digests. Only their inequality matters; they are 64 hex characters because that
is what the rule will really be handed and a test reading `"x"` invites a caller to pass one."""

PATH = "skills/example/SKILL.md"


CONTRACT_C9 = (
    ("UNCHANGED", "unchanged"),
    ("UPDATE", "update"),
    ("LOCAL_EDIT", "local_edit"),
    ("CONFLICT", "conflict"),
    ("CREATE", "create"),
    ("PRUNE", "prune"),
    ("FOREIGN", "foreign"),
    ("MANIFEST_REPAIR", "manifest_repair"),
    ("SKIPPED", "skipped"),
)
"""Contract C-9's nine members, in the order the contract lists them, with the canonical
underscored spelling of each.

A golden literal rather than a comparison between two computed values: `[v.value for v in Verdict]`
compared against itself agrees under any rename, and the value is the wire token initiative 04
branches on. A tenth verdict **extends** this tuple; it never replaces the assertion with a weaker
one.
"""

PRODUCIBLE_VERDICTS = frozenset(
    {
        Verdict.UNCHANGED,
        Verdict.UPDATE,
        Verdict.LOCAL_EDIT,
        Verdict.CONFLICT,
        Verdict.CREATE,
        Verdict.PRUNE,
        Verdict.FOREIGN,
        Verdict.MANIFEST_REPAIR,
    }
)
"""The eight verdicts the rule in this module can reach. `SKIPPED` is the ninth and T-20 emits it;
nothing here does."""

IMPOSSIBLE_EQUALITIES = (
    (True, True, False),
    (True, False, True),
    (False, True, True),
)
"""The three `(library == manifest, manifest == target, library == target)` combinations that
assert two digests both equal a third and differ from each other."""


def _entry(verdict: Verdict, path: str = PATH) -> PlanEntry:
    """Build an entry carrying `verdict`. Collects evidence only — it asserts nothing (L29)."""
    reason = "built for this test" if verdict in EXPLAINED_VERDICTS else None
    return PlanEntry(artifact_id="skill/example", path=path, verdict=verdict, reason=reason)


# ---------------------------------------------------------------------------------------------
# C-9 — the verdict vocabulary
# ---------------------------------------------------------------------------------------------


def test_the_verdict_set_is_exactly_contract_c9() -> None:
    """Closed, nine members, declared in the contract's order and spelled its way.

    Order is asserted alongside membership because `counts` is rendered in declaration order, so a
    member appended in the wrong place is a change to a report nobody reviewed.
    """
    assert [(member.name, member.value) for member in Verdict] == list(CONTRACT_C9)


def test_the_blocking_register_is_exactly_the_three_c10_names() -> None:
    """C-10's `is_complete` predicate, as a set. `MANIFEST_REPAIR` is deliberately not in it: the
    files are already correct, so nothing is awaiting a decision."""
    assert {Verdict.LOCAL_EDIT, Verdict.CONFLICT, Verdict.SKIPPED} == BLOCKING_VERDICTS
    assert Verdict.MANIFEST_REPAIR not in BLOCKING_VERDICTS
    assert Verdict.UNCHANGED not in BLOCKING_VERDICTS


def test_the_verdicts_that_must_explain_themselves_are_conflict_and_skipped() -> None:
    assert {Verdict.CONFLICT, Verdict.SKIPPED} == EXPLAINED_VERDICTS


def test_the_resolvable_register_is_the_blocking_one_without_skipped() -> None:
    """**Ruling R99, as a relationship between two registers rather than as a second list.**

    `--resolve` can act on a refused path when two versions of it exist and the user can prefer
    one. That is true of a `LOCAL_EDIT` and of every `CONFLICT` shape, and false of a `SKIPPED`
    artifact: its root is a symlink the scan never followed, so the library holds no bytes for it
    and there is nothing to choose between. `--resolve` therefore does not lift V11, exactly as
    `--force` does not.

    Asserted as the *difference* between the two sets and not merely as a literal, so that a
    tenth verdict joining `BLOCKING_VERDICTS` fails here and is judged rather than inherited —
    whether a newly refused path has two versions is a decision, not a subtraction.
    """
    assert {Verdict.LOCAL_EDIT, Verdict.CONFLICT} == RESOLVABLE_VERDICTS
    assert Verdict.SKIPPED not in RESOLVABLE_VERDICTS
    assert RESOLVABLE_VERDICTS | {Verdict.SKIPPED} == BLOCKING_VERDICTS


def test_nothing_that_install_applies_is_resolvable() -> None:
    """The positive control for the assertion above: the register really does exclude things, so
    "`SKIPPED` is not in it" cannot mean "nothing is in it" or "everything is".

    A verdict apply acts on needs no resolution — there is nothing the user has been asked to
    decide — so a `--resolve` that reached one would be overwriting a file on its own initiative.
    """
    assert set(Verdict) > RESOLVABLE_VERDICTS
    for applied in (Verdict.UNCHANGED, Verdict.UPDATE, Verdict.CREATE, Verdict.PRUNE):
        assert applied not in RESOLVABLE_VERDICTS
    assert Verdict.FOREIGN not in RESOLVABLE_VERDICTS
    assert Verdict.MANIFEST_REPAIR not in RESOLVABLE_VERDICTS


# ---------------------------------------------------------------------------------------------
# R55 — presence is resolved before equality
# ---------------------------------------------------------------------------------------------


PRESENCE_CASES = (
    pytest.param(None, None, None, None, id="absent-from-all-three-is-not-an-entry"),
    pytest.param(None, None, SHA_A, Verdict.FOREIGN, id="target-only"),
    pytest.param(SHA_A, None, None, Verdict.CREATE, id="library-only"),
    pytest.param(None, SHA_A, SHA_A, Verdict.PRUNE, id="manifest-and-target-agree"),
    pytest.param(None, SHA_A, SHA_B, Verdict.CONFLICT, id="manifest-and-target-differ"),
    pytest.param(SHA_A, SHA_A, None, Verdict.CREATE, id="library-and-manifest-agree"),
    pytest.param(SHA_A, SHA_B, None, Verdict.CONFLICT, id="library-and-manifest-differ"),
    pytest.param(SHA_A, None, SHA_A, Verdict.MANIFEST_REPAIR, id="library-and-target-agree"),
    pytest.param(SHA_A, None, SHA_B, Verdict.CONFLICT, id="library-and-target-differ"),
)


@pytest.mark.parametrize(("library", "manifest", "target", "expected"), PRESENCE_CASES)
def test_presence_is_resolved_before_equality(
    library: str | None,
    manifest: str | None,
    target: str | None,
    expected: Verdict | None,
) -> None:
    """The six presence cases of R55, with both branches of the three that compare digests.

    The row that matters most is `manifest-and-target-agree`: a library artifact dropped while the
    manifest and the target still agree is a **prune**. Encoding the missing library digest as an
    inequality would make it an update, which writes back a file the library no longer holds.
    """
    assert decide_verdict(library_sha=library, manifest_sha=manifest, target_sha=target) is expected


# ---------------------------------------------------------------------------------------------
# The equality table, once all three sides hold the path
# ---------------------------------------------------------------------------------------------


EQUALITY_CASES = (
    pytest.param(SHA_A, SHA_A, SHA_A, Verdict.UNCHANGED, id="all-three-agree"),
    pytest.param(SHA_B, SHA_A, SHA_A, Verdict.UPDATE, id="library-moved-on"),
    pytest.param(SHA_A, SHA_A, SHA_B, Verdict.LOCAL_EDIT, id="target-edited-out-of-band"),
    pytest.param(SHA_A, SHA_B, SHA_A, Verdict.MANIFEST_REPAIR, id="only-the-manifest-is-stale"),
    pytest.param(SHA_A, SHA_B, SHA_C, Verdict.CONFLICT, id="all-three-differ"),
)


@pytest.mark.parametrize(("library", "manifest", "target", "expected"), EQUALITY_CASES)
def test_the_equality_table_when_every_side_holds_the_path(
    library: str, manifest: str, target: str, expected: Verdict
) -> None:
    """Five reachable rows, each asserted as a verdict value.

    `only-the-manifest-is-stale` is the row R52 exists for: library and target already agree, so no
    file is written, and folding it into `UNCHANGED` would leave a consumer unable to count the
    manifest rewrites it performed.
    """
    assert decide_verdict(library_sha=library, manifest_sha=manifest, target_sha=target) is expected


@pytest.mark.parametrize(("equal_lm", "equal_mt", "equal_lt"), IMPOSSIBLE_EQUALITIES)
def test_a_combination_that_violates_transitivity_raises(
    equal_lm: bool, equal_mt: bool, equal_lt: bool
) -> None:
    """Unreachable states raise rather than defaulting to a verdict that would act on a file.

    The first assertion is the positive control: without it a `verdict_for_equalities` that raised
    on *every* input would pass this test three times over. A bare `ValueError` is deliberate —
    these take no `ErrorCode`, because no user can cause one and no exit status describes one.
    """
    assert (
        verdict_for_equalities(
            library_equals_manifest=True,
            manifest_equals_target=True,
            library_equals_target=True,
        )
        is Verdict.UNCHANGED
    )
    with pytest.raises(ValueError, match="transitive"):
        verdict_for_equalities(
            library_equals_manifest=equal_lm,
            manifest_equals_target=equal_mt,
            library_equals_target=equal_lt,
        )


def test_exactly_three_of_the_eight_combinations_are_absent_from_the_table() -> None:
    """The table is exhaustive over the reachable inputs and the raise covers the rest.

    Keys only: a row whose *verdict* is wrong is caught by the table tests above, and restating the
    mapping here would make this a transcription of the source rather than a check on it.
    """
    every_combination = set(itertools.product((True, False), repeat=3))
    assert set(VERDICT_BY_EQUALITY).isdisjoint(IMPOSSIBLE_EQUALITIES)
    assert set(VERDICT_BY_EQUALITY) | set(IMPOSSIBLE_EQUALITIES) == every_combination
    assert len(VERDICT_BY_EQUALITY) == 5


def test_the_rule_reaches_all_eight_producible_verdicts_and_never_skipped() -> None:
    """A sweep over every presence and equality shape the rule can be handed.

    Three things at once, and they are one claim: over 64 inputs the rule produces exactly the
    eight producible verdicts plus `None`, never `SKIPPED`, and never raises — the transitivity
    violations really are unreachable through this entry point. The equality between the produced
    set and `PRODUCIBLE_VERDICTS` is the positive control for the `SKIPPED` absence: it proves the
    sweep produced verdicts at all.
    """
    digests = (None, SHA_A, SHA_B, SHA_C)
    produced = {
        decide_verdict(library_sha=library, manifest_sha=manifest, target_sha=target)
        for library, manifest, target in itertools.product(digests, repeat=3)
    }
    assert produced == {None} | set(PRODUCIBLE_VERDICTS)
    assert Verdict.SKIPPED not in produced


# ---------------------------------------------------------------------------------------------
# C-10 — PlanEntry
# ---------------------------------------------------------------------------------------------


def test_an_entry_is_frozen() -> None:
    entry = _entry(Verdict.UPDATE)
    with pytest.raises(AttributeError):
        entry.verdict = Verdict.UNCHANGED  # type: ignore[misc]


def test_an_entry_path_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="path"):
        PlanEntry(artifact_id="skill/example", path="", verdict=Verdict.CREATE)


@pytest.mark.parametrize("verdict", sorted(EXPLAINED_VERDICTS))
def test_a_verdict_that_must_explain_itself_refuses_to_be_built_without_a_reason(
    verdict: Verdict,
) -> None:
    """C-10 makes the reason part of the shape, so it is enforced rather than remembered.

    The second half is the positive control: the same entry is constructible the moment a reason
    is supplied, so the raise is about the reason and not about the rest of the arguments.
    """
    with pytest.raises(ValueError, match="reason"):
        PlanEntry(artifact_id="skill/example", path=PATH, verdict=verdict)
    explained = PlanEntry(
        artifact_id="skill/example", path=PATH, verdict=verdict, reason="the target was edited"
    )
    assert explained.reason == "the target was edited"


def test_an_empty_reason_does_not_count_as_an_explanation() -> None:
    with pytest.raises(ValueError, match="reason"):
        PlanEntry(artifact_id="skill/example", path=PATH, verdict=Verdict.CONFLICT, reason="")


def test_every_other_verdict_needs_no_reason_but_may_carry_one() -> None:
    """The implication runs one way. A `CONFLICT` must explain itself; an `UPDATE` may."""
    assert _entry(Verdict.UPDATE).reason is None
    annotated = PlanEntry(
        artifact_id="skill/example", path=PATH, verdict=Verdict.UPDATE, reason="three files"
    )
    assert annotated.reason == "three files"


def test_a_skipped_entry_may_hold_no_digest_at_all() -> None:
    """V11's symlinked root: present in the library, never scanned, so there is nothing to hash,
    and neither the manifest nor the target need hold it either."""
    entry = PlanEntry(
        artifact_id="skill/linked",
        path="skills/linked",
        verdict=Verdict.SKIPPED,
        reason="the artifact root is a symlink and was not scanned",
    )
    assert (entry.library_sha, entry.manifest_sha, entry.target_sha) == (None, None, None)
    assert entry.verdict is Verdict.SKIPPED


def test_a_foreign_path_may_belong_to_no_artifact() -> None:
    """**Ruling R60.** A foreign file outside every artifact root belongs to no artifact, and
    `None` is the answer to "which artifact is this" for it. T-12 left the empty string
    constructible and flagged the question; R60 closed it, because `""` type-checks and means
    nothing, and an id nobody filled in must not reach a consumer looking like one somebody did.
    Refusing to represent the path at all would push install into inventing an id for something it
    must never touch."""
    entry = PlanEntry(artifact_id=None, path="settings.json", verdict=Verdict.FOREIGN)
    assert entry.verdict is Verdict.FOREIGN
    assert entry.artifact_id is None


def test_an_artifact_id_may_not_be_the_empty_string() -> None:
    """**Ruling R69**, the half R60 left open. R60 gave `None` a meaning; `""` is the value it
    retired and T-14 was authorised to widen the annotation and nothing else, so the empty string
    stayed constructible and type-checking. One spelling of "no id", not two — an empty id renders
    as nothing and reaches a consumer looking like one somebody filled in."""
    with pytest.raises(ValueError, match="never the empty string"):
        PlanEntry(artifact_id="", path="settings.json", verdict=Verdict.FOREIGN)


def test_a_foreign_path_inside_an_artifact_root_still_names_its_artifact() -> None:
    """R60 says `None` only for a path under **no** artifact root, so a foreign path that *is*
    under one keeps the id. An editor swap file beside an installed `SKILL.md` is never written
    and never removed by install, and a report that could not say whose directory it is in would
    be less useful than the `ls` it replaces."""
    entry = PlanEntry(
        artifact_id="skill/example",
        path="skills/example/SKILL.md.swp",
        verdict=Verdict.FOREIGN,
    )

    assert entry.artifact_id == "skill/example"


# ---------------------------------------------------------------------------------------------
# plan_entry_for — the rule and the entry, built together
# ---------------------------------------------------------------------------------------------


def test_no_entry_is_built_for_a_path_no_side_holds() -> None:
    assert (
        plan_entry_for(
            artifact_id="skill/example",
            path=PATH,
            library_sha=None,
            manifest_sha=None,
            target_sha=None,
        )
        is None
    )


def test_an_entry_carries_the_three_digests_it_was_judged_on() -> None:
    entry = plan_entry_for(
        artifact_id="skill/example",
        path=PATH,
        library_sha=SHA_B,
        manifest_sha=SHA_A,
        target_sha=SHA_A,
    )
    assert entry is not None
    assert entry.verdict is Verdict.UPDATE
    assert (entry.library_sha, entry.manifest_sha, entry.target_sha) == (SHA_B, SHA_A, SHA_A)
    assert (entry.artifact_id, entry.path) == ("skill/example", PATH)
    assert entry.reason is None


CONFLICT_SHAPES: tuple[tuple[str | None, str | None, str | None], ...] = (
    (None, SHA_A, SHA_B),
    (SHA_A, SHA_B, None),
    (SHA_A, None, SHA_B),
    (SHA_A, SHA_B, SHA_C),
)
"""The four presence shapes that reach `CONFLICT`, one per cause."""

CONFLICT_IDS = (
    "the-library-dropped-a-path-the-target-edited",
    "the-target-deleted-a-path-the-library-changed",
    "the-target-holds-an-unmanaged-copy",
    "all-three-differ",
)


@pytest.mark.parametrize(("library", "manifest", "target"), CONFLICT_SHAPES, ids=CONFLICT_IDS)
def test_every_conflict_explains_itself(
    library: str | None, manifest: str | None, target: str | None
) -> None:
    entry = plan_entry_for(
        artifact_id="skill/example",
        path=PATH,
        library_sha=library,
        manifest_sha=manifest,
        target_sha=target,
    )
    assert entry is not None
    assert entry.verdict is Verdict.CONFLICT
    assert entry.reason


def test_the_four_conflicts_give_four_different_reasons() -> None:
    """Four causes, four resolutions. One sentence covering all of them would send the user to
    read the three digests themselves, which is the second lookup C-10 exists to remove."""
    reasons: set[str | None] = set()
    for library, manifest, target in CONFLICT_SHAPES:
        entry = plan_entry_for(
            artifact_id="skill/example",
            path=PATH,
            library_sha=library,
            manifest_sha=manifest,
            target_sha=target,
        )
        assert entry is not None
        reasons.add(entry.reason)
    assert len(reasons) == len(CONFLICT_SHAPES)


# ---------------------------------------------------------------------------------------------
# C-10 — InstallPlan
# ---------------------------------------------------------------------------------------------


def test_an_empty_plan_is_complete_and_counts_nine_zeros() -> None:
    """The default, constructed with no arguments: a plan over a target that needs nothing done is
    the ordinary outcome of `loom diff`, and every criterion about it runs through this object."""
    plan = InstallPlan()
    assert plan.entries == ()
    assert plan.is_complete is True
    assert set(plan.counts.values()) == {0}
    assert len(plan.counts) == len(Verdict)


def test_counts_covers_every_verdict_in_declaration_order() -> None:
    """Dense, zeros included: a consumer counting `MANIFEST_REPAIR` (R52) must not have to guard
    the lookup, and one that does guard it will forget a verdict."""
    plan = InstallPlan(entries=(_entry(Verdict.UPDATE), _entry(Verdict.UPDATE, "b/c.md")))
    assert list(plan.counts) == list(Verdict)
    assert plan.counts[Verdict.UPDATE] == 2
    assert plan.counts[Verdict.SKIPPED] == 0
    assert sum(plan.counts.values()) == len(plan.entries)


def test_counts_cannot_be_edited_by_a_consumer() -> None:
    plan = InstallPlan(entries=(_entry(Verdict.CREATE),))
    with pytest.raises(TypeError):
        plan.counts[Verdict.CREATE] = 99  # type: ignore[index]


def test_counts_tallies_a_mixed_plan_by_verdict() -> None:
    plan = InstallPlan(
        entries=(
            _entry(Verdict.UNCHANGED, "a.md"),
            _entry(Verdict.CREATE, "b.md"),
            _entry(Verdict.CREATE, "c.md"),
            _entry(Verdict.CONFLICT, "d.md"),
        )
    )
    assert plan.counts[Verdict.UNCHANGED] == 1
    assert plan.counts[Verdict.CREATE] == 2
    assert plan.counts[Verdict.CONFLICT] == 1
    assert plan.counts[Verdict.PRUNE] == 0


@pytest.mark.parametrize("blocking", sorted(BLOCKING_VERDICTS))
def test_one_blocking_entry_makes_the_whole_plan_incomplete(blocking: Verdict) -> None:
    """Each of the three, with its own positive control: the same plan without the blocking entry
    is complete, so the incompleteness is attributable to that entry and not to the plan."""
    safe = (_entry(Verdict.UNCHANGED, "a.md"), _entry(Verdict.UPDATE, "b.md"))
    assert InstallPlan(entries=safe).is_complete is True
    assert InstallPlan(entries=(*safe, _entry(blocking, "c.md"))).is_complete is False


def test_a_plan_of_every_safe_verdict_is_complete() -> None:
    """The six verdicts install can act on unaided — `MANIFEST_REPAIR` among them, because the
    files already agree and only the manifest is rewritten."""
    safe = sorted(PRODUCIBLE_VERDICTS - BLOCKING_VERDICTS)
    plan = InstallPlan(
        entries=tuple(_entry(verdict, f"{index}.md") for index, verdict in enumerate(safe))
    )
    assert len(plan.entries) == 6
    assert plan.is_complete is True


def test_a_plan_is_frozen() -> None:
    plan = InstallPlan()
    with pytest.raises(AttributeError):
        plan.entries = (_entry(Verdict.CREATE),)  # type: ignore[misc]
