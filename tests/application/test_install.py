"""`PlanInstall` and `ApplyInstall` — the write-side use cases. T-15 and T-16.

What is asserted *here* rather than in `test_drift.py` is what belongs to the write side: that the
plan is decided without touching the target, that a caller cannot reach it without saying what the
manifest is, and — T-16 — **what apply writes, in what order, and what it refuses to touch**.

Fakes only, zero disk (charter §10). What this layer cannot see is that a write lands at `0644`,
that a backup survives a `git clean`, or that a manifest reaches a real state directory; those are
proven against real files in `tests/infrastructure/`. **No test anywhere writes to `~/.claude/`.**

**Every byte-identical assertion in this module reads the target's content**, through
`FakeTargetRepository.snapshot`, and never the write recorder. A recorder can be empty because
nothing was written or because nothing recorded it; the file cannot.

Where the two use cases are **defined** is asserted in `tests/test_architecture.py`, which is the
only thing in this project that can see it: `mypy`, `ruff` and `lint-imports` all stay green when a
write use case is moved into `application/read/`.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from harness_library.application.read.drift import diff_against_target
from harness_library.application.write import ApplyResult, apply_install, plan_install
from harness_library.domain.errors import (
    BackupFailedError,
    ErrorCode,
    LockHeldError,
    ManifestWriteError,
    RecordStaleError,
    TargetUnwritableError,
)
from harness_library.domain.identity import ArtifactType
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.manifest import Manifest
from harness_library.domain.raw import SymlinkedRoot
from harness_library.domain.validation import ValidationCode
from tests.application.fakes import (
    TARGET_PATH,
    FakeArtifactRepository,
    FakeBackupStore,
    FakeManifestStore,
    FakeTargetRepository,
    FakeWriteLock,
    finding,
    make_artifact,
    make_file,
    manifest_artifact,
    manifest_of,
    target_file,
    target_holding,
    target_symlink,
)

SKILL_NAME = "delivery-lead"
SKILL_ID = "skill/delivery-lead"
ENTRY = "SKILL.md"
INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"

OTHER_NAME = "phase-reviewer"
OTHER_ID = "skill/phase-reviewer"
INSTALLED_OTHER = "skills/phase-reviewer/SKILL.md"

REFERENCE = "references/notes.md"
INSTALLED_REFERENCE = "skills/delivery-lead/references/notes.md"

FOREIGN = "settings.json"
FOREIGN_BYTES = b'{"theme": "dark"}\n'

LIBRARY_BYTES = b"# the library has moved on\n"
INSTALLED_BYTES = b"# what this tool installed\n"
EDITED_BYTES = b"# and then the user edited it\n"

INSTALLED_AT = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)
"""When every apply in this module ran. A parameter, never a clock (see `apply_install`)."""


def apply(
    plan: InstallPlan,
    library: FakeArtifactRepository,
    target: FakeTargetRepository,
    *,
    backups: FakeBackupStore | None = None,
    manifests: FakeManifestStore | None = None,
    lock: FakeWriteLock | None = None,
    manifest: Manifest | None = None,
    prune: bool = False,
) -> ApplyResult:
    """`apply_install` with this module's fixed instant and target path.

    Plumbing only: it passes arguments and returns the result. It asserts nothing and decides
    nothing (L29) — every verdict about what happened is made in a test.

    A fresh `FakeWriteLock` unless one is given, so **every apply in this module runs under a
    lock** (R50) — which is the point, and which is why the helper supplies one rather than
    letting each test decide whether this run is the locked kind.
    """
    return apply_install(
        plan,
        library,
        target,
        backups if backups is not None else FakeBackupStore(),
        manifests if manifests is not None else FakeManifestStore(),
        lock=lock if lock is not None else FakeWriteLock(),
        manifest=manifest,
        target_path=TARGET_PATH,
        installed_at=INSTALLED_AT,
        prune=prune,
    )


def entry(
    path: str,
    verdict: Verdict,
    *,
    artifact_id: str | None = SKILL_ID,
    library_sha: str | None = None,
    manifest_sha: str | None = None,
    target_sha: str | None = None,
    reason: str | None = None,
) -> PlanEntry:
    """One plan entry, built by hand.

    Apply's tests build their plans directly rather than through the join, so a mutation to the
    verdict rule or to the join reddens `test_drift.py` and leaves this module alone — and so that
    a plan mixing four verdicts is one literal instead of four fixtures contriving to produce them.
    `CONFLICT` is the exception: ruling R61 says only `plan_entry_for` writes its reason, and the
    tests below that need one take it from a real plan.
    """
    return PlanEntry(
        artifact_id=artifact_id,
        path=path,
        verdict=verdict,
        library_sha=library_sha,
        manifest_sha=manifest_sha,
        target_sha=target_sha,
        reason=reason,
    )


def a_library(*names: str) -> FakeArtifactRepository:
    """A library holding one single-file skill per name, all with `LIBRARY_BYTES`."""
    artifacts = [make_artifact(name, files=(make_file(ENTRY, LIBRARY_BYTES),)) for name in names]
    contents = {(artifact.id, ENTRY): LIBRARY_BYTES for artifact in artifacts}
    return FakeArtifactRepository(artifacts, contents=contents)


# -------------------------------------------------------------------------------------------
# Planning (T-15)
# -------------------------------------------------------------------------------------------


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


def test_apply_also_requires_the_manifest_and_gives_it_no_default() -> None:
    """Sharper here than on the plan: this is what every path apply does *not* write keeps its
    digest from, so a caller that omitted it would drop every conflicted artifact's record and
    orphan the files it names."""
    parameter = inspect.signature(apply_install).parameters["manifest"]

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

    plan = plan_install(library, target, manifest=None, unscannable=())

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
        unscannable=(),
    )

    assert [entry.verdict for entry in plan.entries] == [Verdict.UNCHANGED, Verdict.UNCHANGED]
    assert plan.is_complete
    assert plan.counts[Verdict.UNCHANGED] == 2


# -------------------------------------------------------------------------------------------
# Ruling R46 — V11's symlinked artifact root, refused
# -------------------------------------------------------------------------------------------
#
# What this layer decides is the *narrowing*: which entry the plan grows, what it says, and that
# `force` cannot switch it off. That a real scan of a real link produces the value at all is
# proven in `tests/test_symlinked_root.py` against a committed one — a fake has no filesystem
# and so cannot hold a link, which is exactly the half plan §9 says went unwired last time.

LINKED_NAME = "linked-skill"
LINKED_ID = "skill/linked-skill"
LINKED_ROOT = "skills/linked-skill"


def a_symlinked_root(name: str = LINKED_NAME) -> SymlinkedRoot:
    """One root the scan refused to walk, as `scan_library` hands it across."""
    return SymlinkedRoot(
        type=ArtifactType.SKILL, name=name, destination="../../outside/linked-skill"
    )


def test_plan_install_requires_the_symlinked_roots_and_gives_them_no_default() -> None:
    """The argument C-16's lock carries (R82), applied to a value rather than to a seam.

    A plan that simply does not take the symlinked roots keeps `mypy`, `ruff`, `lint-imports`
    and the whole suite green while silently omitting an artifact — which is the exact failure
    V11 exists to close, reproduced by a forgotten parameter. T-22 writes the composition root,
    and a default is how it would forget.
    """
    parameter = inspect.signature(plan_install).parameters["unscannable"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_a_symlinked_root_is_one_skipped_entry_that_makes_the_run_incomplete() -> None:
    """The artifact is named in the plan, carries a reason naming the rule, and blocks
    completion so the caller exits `INCOMPLETE = 6` rather than reporting a clean install of a
    library one of whose skills it never read.

    The plan's other entry is the control: a valid artifact beside it still comes back `CREATE`.
    """
    library = a_library(SKILL_NAME)
    plan = plan_install(
        library, FakeTargetRepository(), manifest=None, unscannable=(a_symlinked_root(),)
    )

    verdicts = {entry.path: entry.verdict for entry in plan.entries}
    assert verdicts[LINKED_ROOT] is Verdict.SKIPPED
    assert verdicts[INSTALLED_ENTRY] is Verdict.CREATE
    assert not plan.is_complete
    assert plan.counts[Verdict.SKIPPED] == 1

    entry = next(one for one in plan.entries if one.path == LINKED_ROOT)
    assert entry.artifact_id == LINKED_ID
    assert entry.reason is not None
    assert "V11" in entry.reason


def test_a_skipped_root_is_not_written_and_makes_the_result_incomplete() -> None:
    """Asserted on the target's content, never on the report. The valid skill beside it is
    written in the same run, so this cannot pass by writing nothing (R53)."""
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository()
    plan = plan_install(library, target, manifest=None, unscannable=(a_symlinked_root(),))

    result = apply(plan, library, target)

    assert LINKED_ROOT not in target.snapshot()
    assert target.snapshot()[INSTALLED_ENTRY] == LIBRARY_BYTES
    assert result.written == (INSTALLED_ENTRY,)
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == [LINKED_ROOT]


def test_force_does_not_lift_the_symlinked_root_refusal() -> None:
    """**The one place `force` stops.** R75 refuses an artifact whose bytes are there and whose
    faults a user may accept; here there are no bytes, and forcing could only mean following the
    link or destroying it.

    The control is in the same test: `force=True` is really in effect, because the V1-carrying
    artifact R75 would otherwise refuse comes back `CREATE`.
    """
    library = _library_with_finding(ValidationCode.V1)
    plan = plan_install(
        library,
        FakeTargetRepository(),
        manifest=None,
        unscannable=(a_symlinked_root(),),
        force=True,
    )

    verdicts = {entry.path: entry.verdict for entry in plan.entries}
    assert verdicts[LINKED_ROOT] is Verdict.SKIPPED
    assert verdicts[INSTALLED_ENTRY] is Verdict.CREATE


def test_a_symlinked_root_replaces_a_foreign_entry_at_the_same_path() -> None:
    """One path, one entry. The collision is the realistic case, not a theoretical one: a
    developer who links `skills/<name>` in their library usually has the same link in their
    harness, where the target scan reports it `FOREIGN`.

    The skip wins, which also stops `clean --foreign` offering to delete the development link
    R22's exception exists to protect. The digests the entry carried are kept, because they are
    facts about that path.
    """
    library = a_library(SKILL_NAME)
    target = target_holding((LINKED_ROOT, b"someone else's file\n"))

    plan = plan_install(library, target, manifest=None, unscannable=(a_symlinked_root(),))

    at_root = [entry for entry in plan.entries if entry.path == LINKED_ROOT]
    assert len(at_root) == 1
    assert at_root[0].verdict is Verdict.SKIPPED
    assert at_root[0].target_sha is not None
    assert Verdict.FOREIGN not in plan.counts or plan.counts[Verdict.FOREIGN] == 0


def test_a_library_with_no_symlinked_root_grows_no_entry() -> None:
    """The positive control for every absence above: the same call with `()` and the plan is
    exactly the one the join produced."""
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository()

    plan = plan_install(library, target, manifest=None, unscannable=())

    assert [entry.path for entry in plan.entries] == [INSTALLED_ENTRY]
    assert plan.is_complete


# -------------------------------------------------------------------------------------------
# Ruling R75 — an artifact that does not validate is not installed
# -------------------------------------------------------------------------------------------


def _library_with_finding(code: ValidationCode) -> FakeArtifactRepository:
    """One skill carrying one finding of `code`, and nothing else."""
    artifact = make_artifact(
        SKILL_NAME,
        files=(make_file(ENTRY, LIBRARY_BYTES),),
        findings=(finding(code, "the rule fired"),),
    )
    return FakeArtifactRepository([artifact], contents={(artifact.id, ENTRY): LIBRARY_BYTES})


def test_an_artifact_with_an_error_finding_is_skipped_with_a_reason_naming_the_rule() -> None:
    """**F-9 (R75).** The artifact would otherwise be a `CREATE`. It comes back `SKIPPED`, the
    reason names the code that fired, and the plan is incomplete — so the run exits
    `INCOMPLETE = 6` rather than reporting a clean install of something that does not validate."""
    plan = plan_install(
        _library_with_finding(ValidationCode.V1),
        FakeTargetRepository(),
        manifest=None,
        unscannable=(),
    )
    refused = plan.entries[0]

    assert refused.verdict is not Verdict.CREATE
    assert refused.verdict is Verdict.SKIPPED
    assert refused.reason is not None
    assert "V1" in refused.reason
    assert not plan.is_complete
    assert plan.counts[Verdict.SKIPPED] == 1


def test_a_skipped_artifact_is_not_written_and_its_bytes_never_reach_the_target() -> None:
    """The refusal is about the file, not about the report. Asserted on the target's content."""
    target = FakeTargetRepository()
    plan = plan_install(
        _library_with_finding(ValidationCode.V1), target, manifest=None, unscannable=()
    )

    result = apply(plan, _library_with_finding(ValidationCode.V1), target)

    assert target.snapshot() == {}
    assert result.written == ()
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == [INSTALLED_ENTRY]


def test_force_installs_an_artifact_that_does_not_validate() -> None:
    """The override, asserted on the file. `--force` is not the narrowing applied differently —
    it is the narrowing not applied, so the entry comes back with its original verdict."""
    library = _library_with_finding(ValidationCode.V1)
    target = FakeTargetRepository()

    plan = plan_install(library, target, manifest=None, unscannable=(), force=True)
    result = apply(plan, library, target)

    assert plan.entries[0].verdict is Verdict.CREATE
    assert target.snapshot()[INSTALLED_ENTRY] == LIBRARY_BYTES
    assert result.is_complete


def test_a_warning_only_artifact_installs_normally() -> None:
    """**The control.** Ruling R22: a WARNING never refuses anything, and charter §8 made V6 a
    warning precisely so that reporting an editor swap file cannot stop an install. Without this
    row, "refuses on ERROR" and "refuses on any finding" are the same result."""
    library = _library_with_finding(ValidationCode.V6)
    target = FakeTargetRepository()

    plan = plan_install(library, target, manifest=None, unscannable=())
    result = apply(plan, library, target)

    assert plan.entries[0].verdict is Verdict.CREATE
    assert target.snapshot()[INSTALLED_ENTRY] == LIBRARY_BYTES
    assert result.is_complete


def test_a_foreign_path_under_an_invalid_artifacts_root_is_still_foreign() -> None:
    """The refusal is per *library-held path*, not per artifact root. A swap file beside a skill
    that does not validate is nobody's to install and nobody's decision to make; calling it
    `SKIPPED` would claim the user owes one."""
    swap = "skills/delivery-lead/SKILL.md.swp"
    plan = plan_install(
        _library_with_finding(ValidationCode.V1),
        target_holding((swap, b"vim was here\n")),
        manifest=None,
        unscannable=(),
    )

    verdicts = {plan_entry.path: plan_entry.verdict for plan_entry in plan.entries}
    assert verdicts[swap] is Verdict.FOREIGN
    assert verdicts[INSTALLED_ENTRY] is Verdict.SKIPPED


def test_one_invalid_artifact_does_not_refuse_the_other_one() -> None:
    """Refusal is per artifact (R53's posture, one ruling early). The valid skill still installs."""
    invalid = make_artifact(
        SKILL_NAME,
        files=(make_file(ENTRY, LIBRARY_BYTES),),
        findings=(finding(ValidationCode.V5, "no description"),),
    )
    valid = make_artifact(OTHER_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))
    library = FakeArtifactRepository(
        [invalid, valid],
        contents={(invalid.id, ENTRY): LIBRARY_BYTES, (valid.id, ENTRY): LIBRARY_BYTES},
    )
    target = FakeTargetRepository()

    result = apply(plan_install(library, target, manifest=None, unscannable=()), library, target)

    assert target.snapshot() == {INSTALLED_OTHER: LIBRARY_BYTES}
    assert result.written == (INSTALLED_OTHER,)
    assert not result.is_complete


# -------------------------------------------------------------------------------------------
# Applying — the happy path, and what the manifest ends up saying
# -------------------------------------------------------------------------------------------


def test_a_complete_plan_writes_every_file_and_records_them_all() -> None:
    """**The must-stay-green control of mutations (a) and (c).** A plan of safe verdicts writes
    every file, leaves the manifest correct, and comes back complete.

    Under mutation (a) — the manifest written after the files — this still passes, which is the
    point: the ordering is invisible to a run that does not fail. Under mutation (c) — the
    conflicted artifact written too — this still passes, because there is no conflict in it.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    target = FakeTargetRepository()
    manifests = FakeManifestStore()
    plan = InstallPlan(
        entries=(
            entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),
            entry(INSTALLED_OTHER, Verdict.CREATE, artifact_id=OTHER_ID, library_sha="b" * 64),
        )
    )

    result = apply(plan, library, target, manifests=manifests)

    assert target.snapshot() == {
        INSTALLED_ENTRY: LIBRARY_BYTES,
        INSTALLED_OTHER: LIBRARY_BYTES,
    }
    assert result.written == (INSTALLED_ENTRY, INSTALLED_OTHER)
    assert result.is_complete
    assert manifests.latest is not None
    assert sorted(record.artifact_id for record in manifests.latest.artifacts) == [
        SKILL_ID,
        OTHER_ID,
    ]


def test_the_manifest_records_the_target_the_instant_and_the_backup_it_was_given() -> None:
    """C-11's four scalars come from the caller, never from a clock or an environment read."""
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository()
    manifests = FakeManifestStore()
    backups = FakeBackupStore(backup_id="2026-09-21T14-29-00Z")

    apply(
        InstallPlan(entries=(entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),)),
        library,
        target,
        backups=backups,
        manifests=manifests,
    )

    written = manifests.latest
    assert written is not None
    assert written.target_path == TARGET_PATH
    assert written.installed_at == INSTALLED_AT
    assert written.backup_id == "2026-09-21T14-29-00Z"


def test_apply_never_writes_a_path_absent_from_the_plan() -> None:
    """**F-9, asserted by the write-recording fake.** The library holds two skills and the plan
    names one; the other's path must never appear.

    The positive control is the same assertion's other half: the path the plan *does* name is in
    the recording, so an empty recorder cannot pass this test by recording nothing.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    target = FakeTargetRepository()

    result = apply(
        InstallPlan(entries=(entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),)),
        library,
        target,
    )

    assert [path for path, _ in target.writes] == [INSTALLED_ENTRY]
    assert INSTALLED_OTHER not in target.snapshot()
    assert result.written == (INSTALLED_ENTRY,)


def test_a_foreign_path_is_byte_identical_after_apply() -> None:
    """**F-10, asserted on the file and not on the report.** Ruling R44 gives Claude Code's own
    `synced/` bucket no special case: it is foreign like anything else, and foreign means
    untouched — not written, not removed, and not recorded in the manifest either."""
    bucket = "skills/synced/.bucket-7c1f9a2e"
    library = a_library(SKILL_NAME)
    target = target_holding((FOREIGN, FOREIGN_BYTES), (bucket, b"not ours\n"))
    manifests = FakeManifestStore()

    result = apply(
        InstallPlan(
            entries=(
                entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),
                entry(FOREIGN, Verdict.FOREIGN, artifact_id=None, target_sha="c" * 64),
                entry(bucket, Verdict.FOREIGN, artifact_id=None, target_sha="d" * 64),
            )
        ),
        library,
        target,
        manifests=manifests,
    )

    assert target.snapshot()[FOREIGN] == FOREIGN_BYTES
    assert target.snapshot()[bucket] == b"not ours\n"
    assert target.deletes == []
    assert result.is_complete
    assert manifests.latest is not None
    recorded = {file.path for record in manifests.latest.artifacts for file in record.files}
    assert FOREIGN not in recorded


def test_manifest_repair_changes_the_manifest_and_touches_no_file() -> None:
    """**F-8 and F-9, asserted on both halves.** Library and target already agree; only the record
    is stale. The repair is a manifest rewrite, so the file must be byte-identical and the new
    manifest must nonetheless carry the path."""
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, LIBRARY_BYTES))
    manifests = FakeManifestStore()
    before = target.snapshot()

    result = apply(
        InstallPlan(
            entries=(
                entry(
                    INSTALLED_ENTRY,
                    Verdict.MANIFEST_REPAIR,
                    library_sha="a" * 64,
                    target_sha="a" * 64,
                ),
            )
        ),
        library,
        target,
        manifests=manifests,
    )

    assert target.snapshot() == before
    assert target.writes == []
    assert result.written == ()
    assert manifests.latest is not None
    assert [file.path for record in manifests.latest.artifacts for file in record.files] == [ENTRY]


def test_an_unchanged_path_is_not_rewritten_and_stays_in_the_manifest() -> None:
    """Nothing to do is not nothing to record: dropping an `UNCHANGED` path from the new manifest
    would make it `FOREIGN` on the next run — unprunable and ununinstallable."""
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, LIBRARY_BYTES))
    manifests = FakeManifestStore()

    apply(
        InstallPlan(
            entries=(
                entry(
                    INSTALLED_ENTRY,
                    Verdict.UNCHANGED,
                    library_sha="a" * 64,
                    manifest_sha="a" * 64,
                    target_sha="a" * 64,
                ),
            )
        ),
        library,
        target,
        manifests=manifests,
        manifest=manifest_of(manifest_artifact(SKILL_ID, (make_file(ENTRY, LIBRARY_BYTES),))),
    )

    assert target.writes == []
    assert manifests.latest is not None
    assert [record.artifact_id for record in manifests.latest.artifacts] == [SKILL_ID]


# -------------------------------------------------------------------------------------------
# Applying — what is left alone
# -------------------------------------------------------------------------------------------


def test_a_mixed_plan_writes_the_safe_entries_and_leaves_the_conflict_byte_identical() -> None:
    """**F-9, all three halves in one test — and the must-fail assertion of mutation (c).**

    The plan mixes a safe `CREATE` with a `CONFLICT` built by the rule itself (R61: nothing else
    writes a conflict's reason). Apply must write the first, leave the second's **bytes** exactly
    as they were, and come back incomplete so the caller exits `INCOMPLETE = 6`.

    Asserted on the conflicted file's content, never on the report: a report saying "I left it
    alone" is precisely what a wrong implementation would also say.
    """
    conflicted = make_artifact(SKILL_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))
    safe = make_artifact(OTHER_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))
    library = FakeArtifactRepository(
        [conflicted, safe],
        contents={(conflicted.id, ENTRY): LIBRARY_BYTES, (safe.id, ENTRY): LIBRARY_BYTES},
    )
    target = target_holding((INSTALLED_ENTRY, EDITED_BYTES))
    plan = plan_install(
        library,
        target,
        manifest=manifest_of(manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))),
        unscannable=(),
    )

    result = apply(
        plan,
        library,
        target,
        manifest=manifest_of(manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))),
    )

    assert plan.counts[Verdict.CONFLICT] == 1
    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert target.snapshot()[INSTALLED_OTHER] == LIBRARY_BYTES
    assert result.written == (INSTALLED_OTHER,)
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == [INSTALLED_ENTRY]
    assert result.left_alone[0].reason is not None


def test_a_conflicted_path_keeps_the_digest_the_previous_manifest_recorded() -> None:
    """Recording the library's digest for a path apply did not write would claim this tool
    installed something it did not — turning a three-way conflict into a two-way `LOCAL_EDIT` on
    the next run and losing the fact the user has to resolve."""
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, EDITED_BYTES))
    manifests = FakeManifestStore()
    installed = make_file(ENTRY, INSTALLED_BYTES)
    previous = manifest_of(manifest_artifact(SKILL_ID, (installed,)))

    apply(
        plan_install(library, target, manifest=previous, unscannable=()),
        library,
        target,
        manifests=manifests,
        manifest=previous,
    )

    written = manifests.latest
    assert written is not None
    assert written.artifacts[0].files == (installed,)


def test_a_local_edit_is_left_alone_and_makes_the_run_incomplete() -> None:
    """The library still holds what was installed and the user edited the target. Never
    overwritten without `--resolve` (F-15, T-21)."""
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, EDITED_BYTES))

    result = apply(
        InstallPlan(
            entries=(
                entry(
                    INSTALLED_ENTRY,
                    Verdict.LOCAL_EDIT,
                    library_sha="a" * 64,
                    manifest_sha="a" * 64,
                    target_sha="b" * 64,
                ),
            )
        ),
        library,
        target,
    )

    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert target.writes == []
    assert not result.is_complete


def test_a_symlink_planted_over_an_installed_path_is_never_written_through() -> None:
    """**Ruling R6 and ruling R72 together.** A link carries no digest, so the join reports it
    present-but-unreadable — `UNHASHED_TARGET_SHA`, a value no digest equals — and the ordinary
    table reaches `LOCAL_EDIT`. Apply must therefore leave it alone, because writing through it
    would put the library's bytes wherever it points, possibly outside the target entirely.

    The regular-file sibling is the control: the same run writes *it*, so this is not passing by
    writing nothing at all.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    installed = make_file(ENTRY, LIBRARY_BYTES)
    target = FakeTargetRepository((target_symlink(INSTALLED_ENTRY),))
    plan = plan_install(
        library,
        target,
        manifest=manifest_of(manifest_artifact(SKILL_ID, (installed,))),
        unscannable=(),
    )

    result = apply(
        plan,
        library,
        target,
        manifest=manifest_of(manifest_artifact(SKILL_ID, (installed,))),
    )

    assert [path for path, _ in target.writes] == [INSTALLED_OTHER]
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == [INSTALLED_ENTRY]


# -------------------------------------------------------------------------------------------
# Pruning
# -------------------------------------------------------------------------------------------


def _prune_plan() -> InstallPlan:
    """One path the manifest records and the library no longer holds."""
    return InstallPlan(
        entries=(
            entry(
                INSTALLED_REFERENCE,
                Verdict.PRUNE,
                manifest_sha="a" * 64,
                target_sha="a" * 64,
            ),
        )
    )


def test_a_prune_removes_nothing_unless_pruning_was_asked_for() -> None:
    """Install removing a file nobody asked it to remove is the behaviour this product replaces.
    The path stays, **and it stays in the manifest** — dropping the record would make the file
    `FOREIGN` on the next run and unremovable by uninstall."""
    target = target_holding((INSTALLED_REFERENCE, INSTALLED_BYTES))
    manifests = FakeManifestStore()
    previous = manifest_of(manifest_artifact(SKILL_ID, (make_file(REFERENCE, INSTALLED_BYTES),)))

    result = apply(
        _prune_plan(),
        a_library(SKILL_NAME),
        target,
        manifests=manifests,
        manifest=previous,
    )

    assert target.deletes == []
    assert target.snapshot()[INSTALLED_REFERENCE] == INSTALLED_BYTES
    assert result.deleted == ()
    assert manifests.latest is not None
    assert [file.path for record in manifests.latest.artifacts for file in record.files] == [
        REFERENCE
    ]


def test_pruning_removes_the_path_and_drops_it_from_the_manifest() -> None:
    """The other half of the control above. With `prune=True` the file goes and so does its
    record; leaving the record behind would have uninstall look for a file that is not there."""
    target = target_holding((INSTALLED_REFERENCE, INSTALLED_BYTES))
    manifests = FakeManifestStore()
    previous = manifest_of(manifest_artifact(SKILL_ID, (make_file(REFERENCE, INSTALLED_BYTES),)))

    result = apply(
        _prune_plan(),
        a_library(SKILL_NAME),
        target,
        manifests=manifests,
        manifest=previous,
        prune=True,
    )

    assert target.deletes == [INSTALLED_REFERENCE]
    assert INSTALLED_REFERENCE not in target.snapshot()
    assert result.deleted == (INSTALLED_REFERENCE,)
    assert manifests.latest is not None
    assert manifests.latest.artifacts == ()


# -------------------------------------------------------------------------------------------
# Ruling R93 — a pruning run records twice, and the pruned path stays claimed until it is gone
# -------------------------------------------------------------------------------------------


class _TargetRefusingToDelete(FakeTargetRepository):
    """A target whose `delete` raises, so a run fails **between** R93's two records.

    A builtin `OSError`, because that is what the real repository raises (R24) and a fake
    raising the project's own error would make the translation untestable by pre-supplying its
    result. It collects evidence and renders no verdict (L29).
    """

    def delete(self, path: str) -> None:
        raise OSError(f"the injected failure refuses to remove {path!r}")


class _ManifestStoreRefusingTheSecondWrite(FakeManifestStore):
    """A store that takes the union record and refuses the one that drops the pruned paths."""

    def write(self, manifest: Manifest) -> None:
        if self.written:
            raise OSError("the injected failure refuses to rewrite the manifest")
        super().write(manifest)


def _recorded_paths(manifest: Manifest) -> set[str]:
    """Every file path the manifest records, artifact-root-relative."""
    return {file.path for record in manifest.artifacts for file in record.files}


def _pruning_manifest() -> Manifest:
    """What was installed before the library dropped `references/notes.md`."""
    return manifest_of(manifest_artifact(SKILL_ID, (make_file(REFERENCE, INSTALLED_BYTES),)))


def test_a_pruning_apply_claims_the_pruned_path_until_it_is_gone() -> None:
    """**The must-fail assertion of mutation (c) — charter §13b, ruling R93, and L52.**

    A failure is injected into the delete, so the run stops between R93's two records. The one
    record already on disk must **still name the pruned path**: the file is still there, and a
    manifest that had already disowned it would leave it `FOREIGN` — untouchable by install,
    unremovable by uninstall, reachable only by `clean --foreign`. That is exactly what R63
    exists to prevent, and before this ruling `--prune` reached it.

    Fold the second record back into the first — the single write this module made until T-20,
    already dropping the pruned paths — and the second assertion fails. Nothing else notices:
    a run that does not fail produces the identical final record under both orders, which is
    why the failure has to be injected (L52).
    """
    target = _TargetRefusingToDelete(
        (target_file(INSTALLED_REFERENCE, INSTALLED_BYTES),),
        contents={INSTALLED_REFERENCE: INSTALLED_BYTES},
    )
    manifests = FakeManifestStore()

    with pytest.raises(TargetUnwritableError) as raised:
        apply(
            _prune_plan(),
            a_library(SKILL_NAME),
            target,
            manifests=manifests,
            manifest=_pruning_manifest(),
            prune=True,
        )

    assert len(manifests.written) == 1
    assert _recorded_paths(manifests.written[0]) == {REFERENCE}, (
        "the record on disk must still claim a path the run has not managed to delete "
        "(charter §13b, R93): a file nothing claims is FOREIGN, and nothing in this initiative "
        "can install it, remove it or repair it"
    )
    assert target.snapshot()[INSTALLED_REFERENCE] == INSTALLED_BYTES
    assert raised.value.code is ErrorCode.TARGET_UNWRITABLE


def test_a_pruning_apply_writes_the_union_first_and_the_drop_afterwards() -> None:
    """R93 as the pair of records it is, on a run that succeeds.

    The first claims everything the run will write **and** everything it will delete, so no
    pruned file is ever on disk unclaimed; the second drops them, because by then they are
    gone. The result carries the second, which is what is on disk.
    """
    target = target_holding((INSTALLED_REFERENCE, INSTALLED_BYTES))
    manifests = FakeManifestStore()

    result = apply(
        _prune_plan(),
        a_library(SKILL_NAME),
        target,
        manifests=manifests,
        manifest=_pruning_manifest(),
        prune=True,
    )

    assert [_recorded_paths(written) for written in manifests.written] == [{REFERENCE}, set()]
    assert result.manifest is manifests.written[-1]


def test_a_run_that_prunes_nothing_writes_the_record_exactly_once() -> None:
    """**What keeps ruling R64's promise.** `MANIFEST_UNWRITABLE` means *nothing happened* only
    because the record an ordinary apply writes is written before the first file and never
    rewritten. R93 adds a second write on the prune path alone, and this is the assertion that
    says "alone"."""
    target = FakeTargetRepository()
    manifests = FakeManifestStore()

    apply(
        InstallPlan(entries=(entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),)),
        a_library(SKILL_NAME),
        target,
        manifests=manifests,
    )

    assert len(manifests.written) == 1


def test_a_second_record_that_cannot_be_written_is_record_stale_and_not_unwritable() -> None:
    """**Ruling R90 on the prune path.** The pruned file is gone, so `MANIFEST_UNWRITABLE`'s
    promise that nothing happened would be exactly false — a script that believed it would
    retry, report success, or do nothing.

    Asserted on the code and on the target together, and on the record that *is* on disk: it
    still names the pruned path, so nothing is disowned and running the command again is safe.
    """
    target = target_holding((INSTALLED_REFERENCE, INSTALLED_BYTES))
    manifests = _ManifestStoreRefusingTheSecondWrite()

    with pytest.raises(RecordStaleError) as raised:
        apply(
            _prune_plan(),
            a_library(SKILL_NAME),
            target,
            manifests=manifests,
            manifest=_pruning_manifest(),
            prune=True,
        )

    assert raised.value.code is ErrorCode.RECORD_STALE
    assert raised.value.operation == "install --prune"
    assert INSTALLED_REFERENCE not in target.snapshot()
    assert _recorded_paths(manifests.written[-1]) == {REFERENCE}


# -------------------------------------------------------------------------------------------
# Ruling R63 — the order, and the three refusals
# -------------------------------------------------------------------------------------------


def test_the_manifest_is_on_disk_before_the_first_file_is_written() -> None:
    """**The must-fail assertion of mutation (a), and ruling R63's whole point.**

    A failure is injected into the *first* file write. Two things must then be true: the manifest
    is already recorded, and the target is byte-identical to what it was before the run. Move the
    manifest write below the file loop and the first assertion fails — nothing else in the suite
    notices, because a run that does not fail cannot tell the two orders apart.

    Why this ordering: a manifest written first can only over-claim, and an over-claim comes back
    as `LOCAL_EDIT` or `CONFLICT` on the next `hl diff`. A manifest written last would leave the
    target modified with no record at all, every installed path reading `FOREIGN` — untouchable by
    install, unremovable by uninstall, recoverable by nothing this initiative ships.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    target = FakeTargetRepository(
        (target_file(FOREIGN, FOREIGN_BYTES),),
        contents={FOREIGN: FOREIGN_BYTES},
        fail_write_after=0,
    )
    manifests = FakeManifestStore()
    before = target.snapshot()
    plan = InstallPlan(
        entries=(
            entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),
            entry(INSTALLED_OTHER, Verdict.CREATE, artifact_id=OTHER_ID, library_sha="b" * 64),
        )
    )

    with pytest.raises(TargetUnwritableError) as raised:
        apply(plan, library, target, manifests=manifests)

    assert manifests.latest is not None, (
        "the manifest must already be on disk when the first file write happens (R63): a crash "
        "here with no manifest leaves every installed path FOREIGN and unrecoverable"
    )
    assert manifests.latest.artifacts != ()
    assert target.snapshot() == before
    assert raised.value.code is ErrorCode.TARGET_UNWRITABLE
    assert raised.value.path == INSTALLED_ENTRY


def test_a_backup_of_every_path_the_run_touches_is_taken_before_any_write() -> None:
    """**The must-fail assertion of mutation (b).** The plan has **two** entries, so a mutation
    that skips the backup for a plan of more than one cannot pass this.

    Every path the run will write or delete is in it, including one the target does not hold yet:
    a restore has to be able to *remove* what a first install created, or a first install is the
    one thing in this tool with no undo.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    target = target_holding((INSTALLED_ENTRY, INSTALLED_BYTES))
    backups = FakeBackupStore()

    result = apply(
        InstallPlan(
            entries=(
                entry(
                    INSTALLED_ENTRY,
                    Verdict.UPDATE,
                    library_sha="a" * 64,
                    manifest_sha="b" * 64,
                    target_sha="b" * 64,
                ),
                entry(INSTALLED_OTHER, Verdict.CREATE, artifact_id=OTHER_ID, library_sha="c" * 64),
            )
        ),
        library,
        target,
        backups=backups,
    )

    assert backups.created == [(INSTALLED_ENTRY, INSTALLED_OTHER)]
    assert result.backup_id == "2026-09-21T14-29-00Z"


def test_apply_refuses_when_the_backup_cannot_be_taken() -> None:
    """**F-9, and the must-stay-green control of mutation (b)** — its plan has exactly **one**
    entry, so a mutation that skips the backup only for longer plans cannot take its subject away.

    A write with no way back is the failure mode this initiative exists to remove, so the refusal
    comes before the manifest and before the first byte: nothing is recorded and nothing is
    written, asserted on both.
    """
    library = a_library(SKILL_NAME)
    target = target_holding((FOREIGN, FOREIGN_BYTES))
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(BackupFailedError) as raised:
        apply(
            InstallPlan(entries=(entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),)),
            library,
            target,
            backups=FakeBackupStore(fail=True),
            manifests=manifests,
        )

    assert raised.value.code is ErrorCode.BACKUP_FAILED
    assert manifests.written == []
    assert target.writes == []
    assert target.snapshot() == before


def test_apply_refuses_when_the_manifest_cannot_be_written() -> None:
    """**F-9 and ruling R64.** `MANIFEST_UNWRITABLE` under R63's ordering always means *nothing
    happened*, and this is the test that makes that a guarantee rather than a claim: the target is
    byte-identical, asserted per file."""
    library = a_library(SKILL_NAME)
    target = target_holding((FOREIGN, FOREIGN_BYTES), (INSTALLED_ENTRY, INSTALLED_BYTES))
    before = target.snapshot()

    with pytest.raises(ManifestWriteError) as raised:
        apply(
            InstallPlan(
                entries=(
                    entry(
                        INSTALLED_ENTRY,
                        Verdict.UPDATE,
                        library_sha="a" * 64,
                        manifest_sha="b" * 64,
                        target_sha="b" * 64,
                    ),
                )
            ),
            library,
            target,
            manifests=FakeManifestStore(fail=True),
        )

    assert raised.value.code is ErrorCode.MANIFEST_UNWRITABLE
    assert target.writes == []
    for path, content in before.items():
        assert target.snapshot()[path] == content
    assert target.snapshot() == before


def test_a_run_with_nothing_to_write_takes_no_backup() -> None:
    """`backup_id` is `None` when there was nothing to protect — C-11's own reading of the field.

    The control for the backup tests above: without it, "a backup is always taken" and "a backup
    is taken when one is needed" are the same result.
    """
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, LIBRARY_BYTES))
    backups = FakeBackupStore()

    result = apply(
        InstallPlan(
            entries=(
                entry(
                    INSTALLED_ENTRY,
                    Verdict.UNCHANGED,
                    library_sha="a" * 64,
                    manifest_sha="a" * 64,
                    target_sha="a" * 64,
                ),
            )
        ),
        library,
        target,
        backups=backups,
    )

    assert backups.created == []
    assert result.backup_id is None


def test_apply_does_not_rescan_the_target() -> None:
    """Apply acts on the plan it was given. A second snapshot disagreeing with the first is how a
    path gets written on the strength of a verdict decided about a different file."""
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository()

    apply(
        InstallPlan(entries=(entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),)),
        library,
        target,
    )

    assert target.scan_calls == 0


def test_a_plan_naming_a_path_no_artifact_produces_is_refused() -> None:
    """A plan and a library from two different runs. Refused with a bare `ValueError` rather than
    an `ErrorCode`: it is an unreachable state and a bug here, never a user's mistake."""
    with pytest.raises(ValueError, match="no artifact in this library produces"):
        apply(
            InstallPlan(entries=(entry("skills/ghost/SKILL.md", Verdict.CREATE, library_sha="a"),)),
            a_library(SKILL_NAME),
            FakeTargetRepository(),
        )


@pytest.mark.parametrize(
    "blocking", [Verdict.LOCAL_EDIT, Verdict.CONFLICT, Verdict.SKIPPED], ids=lambda v: v.value
)
def test_the_result_is_incomplete_exactly_when_the_plan_was(blocking: Verdict) -> None:
    """`ApplyResult.is_complete` is what a caller exits `INCOMPLETE = 6` from, and it must agree
    with the plan's own predicate — two answers to "must the user decide something" is one too
    many. Each row carries the same plan **without** the blocking entry as its control, so a
    result that were simply always incomplete could not pass."""
    library = a_library(SKILL_NAME)
    safe = entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64)
    blocked = InstallPlan(
        entries=(safe, entry(INSTALLED_REFERENCE, blocking, target_sha="b" * 64, reason="because"))
    )
    complete = InstallPlan(entries=(safe,))

    blocked_result = apply(blocked, library, target_holding((INSTALLED_REFERENCE, INSTALLED_BYTES)))
    complete_result = apply(complete, library, FakeTargetRepository())

    assert blocked_result.is_complete is blocked.is_complete
    assert not blocked_result.is_complete
    assert complete_result.is_complete


# -------------------------------------------------------------------------------------------
# Ruling R50 — the single-writer lock, and apply's half of it
# -------------------------------------------------------------------------------------------
#
# What this layer decides is *control flow*: that the lock is taken before the first thing the
# run does to a disk, and released however the run ends. That it actually excludes a second
# process is a sentinel file, proven in `tests/infrastructure/test_lock.py`, and that the two
# together keep a second apply from writing is proven in `tests/test_single_writer.py`.


class _BackupStoreMarkingTheLock(FakeBackupStore):
    """A `FakeBackupStore` that leaves a mark in the lock's own event list when it is called.

    One list holding both facts is what makes the *order* of the lock against the backup a single
    assertion rather than two that could each pass while the pair was wrong.
    """

    def __init__(self, lock: FakeWriteLock) -> None:
        super().__init__()
        self._lock = lock

    def create(self, paths: tuple[str, ...]) -> str:
        self._lock.events.append("backup")
        return super().create(paths)


def _one_create() -> InstallPlan:
    """A plan with one thing to write, so there is always a backup and always a file."""
    return InstallPlan(entries=(entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),))


def test_apply_requires_a_lock_and_gives_it_no_default() -> None:
    """Charter §12 and R50. The same argument `manifest` carries, and for the same reason: an
    unlocked apply must be a decision somebody wrote down, not a parameter somebody forgot.

    T-18 adds two more write use cases and T-22 the composition root; a default here is how one
    of them ends up running unprotected with every gate green.
    """
    parameter = inspect.signature(apply_install).parameters["lock"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_the_lock_is_taken_before_the_backup_and_released_on_success() -> None:
    """The backup is the first thing apply does to a disk, so the lock has to precede it.

    Asserted as one ordered list: a lock taken after the backup would still be "taken" and still
    be "released", and only the order says the copy was made under it.
    """
    lock = FakeWriteLock()
    backups = _BackupStoreMarkingTheLock(lock)

    apply(_one_create(), a_library(SKILL_NAME), FakeTargetRepository(), backups=backups, lock=lock)

    assert lock.events == ["acquired", "backup", "released"]
    assert lock.held is False


def test_apply_writes_nothing_when_the_lock_is_held() -> None:
    """**F-14 at this layer.** A run that cannot take the lock does not back up, does not record
    and does not write — the refusal is before all three, so `LOCK_HELD` carries the same "nothing
    happened" guarantee `MANIFEST_UNWRITABLE` does.

    The positive control is in the same test: the identical plan under a free lock does all three,
    so the three empty lists cannot be empty because the plan was.
    """
    library = a_library(SKILL_NAME)
    target = target_holding((FOREIGN, FOREIGN_BYTES))
    backups = FakeBackupStore()
    manifests = FakeManifestStore()
    before = target.snapshot()

    with pytest.raises(LockHeldError) as raised:
        apply(
            _one_create(),
            library,
            target,
            backups=backups,
            manifests=manifests,
            lock=FakeWriteLock(held_by_another=True),
        )

    assert raised.value.code is ErrorCode.LOCK_HELD
    assert backups.created == []
    assert manifests.written == []
    assert target.writes == []
    assert target.snapshot() == before

    apply(_one_create(), library, target, backups=backups, manifests=manifests)

    assert backups.created != []
    assert manifests.written != []
    assert target.writes != []


def test_the_lock_is_released_when_the_backup_cannot_be_taken() -> None:
    """The first of apply's three failure paths. A lock leaked here would wedge the target on the
    one run that already told the user something is wrong with their state directory."""
    lock = FakeWriteLock()

    with pytest.raises(BackupFailedError):
        apply(
            _one_create(),
            a_library(SKILL_NAME),
            FakeTargetRepository(),
            backups=FakeBackupStore(fail=True),
            lock=lock,
        )

    assert lock.events == ["acquired", "released"]
    assert lock.held is False


def test_the_lock_is_released_when_the_manifest_cannot_be_written() -> None:
    """The second. Under R63 nothing has been written at this point, so a wedged lock would be
    the only trace a run that changed nothing left behind."""
    lock = FakeWriteLock()

    with pytest.raises(ManifestWriteError):
        apply(
            _one_create(),
            a_library(SKILL_NAME),
            FakeTargetRepository(),
            manifests=FakeManifestStore(fail=True),
            lock=lock,
        )

    assert lock.events == ["acquired", "released"]
    assert lock.held is False


def test_the_lock_is_released_when_a_file_write_fails_part_way_through() -> None:
    """The third, and the one that matters most: this is the run that leaves the target modified
    and the manifest over-claiming, so it is the run whose user most needs to be able to try
    again — or to roll back (T-18) — without deleting a lock file by hand.

    The failure is injected into the **second** write, so the run really is part-way through:
    one file is on disk, asserted, and the lock is still released.
    """
    lock = FakeWriteLock()
    target = FakeTargetRepository(fail_write_after=1)
    plan = InstallPlan(
        entries=(
            entry(INSTALLED_ENTRY, Verdict.CREATE, library_sha="a" * 64),
            entry(INSTALLED_OTHER, Verdict.CREATE, artifact_id=OTHER_ID, library_sha="b" * 64),
        )
    )

    with pytest.raises(TargetUnwritableError):
        apply(plan, a_library(SKILL_NAME, OTHER_NAME), target, lock=lock)

    assert [path for path, _ in target.writes] == [INSTALLED_ENTRY]
    assert lock.events == ["acquired", "released"]
    assert lock.held is False
