"""V11 end to end — a committed symlinked artifact root, warned about and refused. T-20.

**The fourth cross-layer module in this suite, and it has to be.** V11's two halves are produced
in two layers and the criterion joins them: a real scan of a **committed** link must produce the
value, the assembler must turn that value into a WARNING the repository hands out, and a real
apply must refuse that one artifact while writing every other. No single layer can witness it —
`tests/domain/test_assembly.py` is handed its `SymlinkedRoot` by the test, so a green run there
says only that the rule fires on a value the test author wrote, and `tests/application/
test_install.py` is handed its library by a fake, which has no filesystem to hold a link at all.

That gap is the one plan §9 names by its history: *the half that went unwired last time*. A rule
decided in the domain and never reached from a real scan is a rule that does not run.

**The warning and the refusal are two facts and are asserted separately, on purpose.** Dropping
the finding must leave the refusal standing, and following the link must leave the warning
standing. So the warning test reads `library_findings()` and the refusal test reads
`symlinked_roots()`, and neither reads the other's source.

**Nothing writes outside `tmp_path`.** The committed library is read and never written, the
target is a fresh directory, and `default_state_root()` is never called.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness_library.application.write import apply_install, plan_install
from harness_library.cli.exit_codes import INCOMPLETE
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.validation import Severity, ValidationCode
from harness_library.infrastructure.backup import FilesystemBackupStore
from harness_library.infrastructure.lock import FilesystemWriteLock
from harness_library.infrastructure.manifest_store import FilesystemManifestStore
from harness_library.infrastructure.repository import FilesystemArtifactRepository
from harness_library.infrastructure.target import FilesystemTargetRepository
from tests.infrastructure.conftest import FIXED_TIMESTAMPS, FIXTURE_LIBRARY

LINKED_ROOT = "skills/linked-skill"
"""The committed symlinked artifact root. `tests/fixtures/README.md` describes it."""

LINKED_ID = "skill/linked-skill"
LINK_DESTINATION = "../../outside/linked-skill"

DESTINATION = FIXTURE_LIBRARY.parent / "outside" / "linked-skill" / "SKILL.md"
"""What the link points at: a skill with no fault of any kind, which is why its absence is the
whole fault. Read here and never written."""

APPLIED_AT = datetime(2026, 9, 21, 21, 0, tzinfo=UTC)
"""When every apply in this module ran. A parameter, never a clock."""

SOUND_ARTIFACTS = (
    "skills/delivery-lead/SKILL.md",
    "agents/scribe.md",
)
"""Two fixture paths that install cleanly. R53 is per artifact, so these must land whatever V11
says about the linked one — without them, "the linked skill was not written" would be satisfied
by a run that wrote nothing at all."""


# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


@pytest.fixture
def library() -> FilesystemArtifactRepository:
    """The committed fixture library, opened over real files with R5 held still."""
    return FilesystemArtifactRepository(FIXTURE_LIBRARY, timestamps=FIXED_TIMESTAMPS)


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Where the manifest, the backup and the sentinel go. Never `default_state_root()`."""
    return tmp_path / "state"


@pytest.fixture
def target_root(tmp_path: Path) -> Path:
    """An empty install target, so every path the run writes is one this run put there."""
    root = tmp_path / "target"
    root.mkdir()
    return root


def plan_for(
    library: FilesystemArtifactRepository, target_root: Path, **kwargs: bool
) -> InstallPlan:
    """The plan a real install would execute against this target.

    `unscannable` comes from the repository's own scan and **never** from its findings: the
    refusal has to survive the warning being dropped, which is mutation (a).
    """
    return plan_install(
        library,
        FilesystemTargetRepository(target_root),
        manifest=None,
        unscannable=library.symlinked_roots(),
        **kwargs,
    )


def apply(
    plan: InstallPlan, library: FilesystemArtifactRepository, target_root: Path, state_root: Path
) -> tuple[str, ...]:
    """One real apply into `target_root`. Returns the paths it wrote."""
    result = apply_install(
        plan,
        library,
        FilesystemTargetRepository(target_root),
        FilesystemBackupStore(state_root, target_root, now=lambda: APPLIED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: APPLIED_AT),
        manifest=None,
        target_path=str(target_root),
        installed_at=APPLIED_AT,
    )
    assert result.is_complete is False, (
        "a run over this library cannot be complete: the linked root is skipped, so the caller "
        f"exits INCOMPLETE = {INCOMPLETE}"
    )
    return result.written


def skipped_entry(plan: InstallPlan, path: str) -> PlanEntry:
    """The one entry at `path`, failing loudly rather than raising `StopIteration`."""
    found = [entry for entry in plan.entries if entry.path == path]
    assert len(found) == 1, f"expected exactly one entry at {path!r}, found {len(found)}"
    return found[0]


def contents_under(root: Path) -> dict[str, bytes]:
    """Every file under `root` and its bytes. The evidence a byte-identical assertion needs."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


# -------------------------------------------------------------------------------------------
# The warning — ruling R46's first half, at repository level
# -------------------------------------------------------------------------------------------


def test_the_committed_symlinked_root_is_a_v11_warning_at_repository_level(
    library: FilesystemArtifactRepository,
) -> None:
    """**The must-fail assertion of mutation (a), and the half that went unwired last time.**

    A real scan of a real committed link, through the real assembler, reaching a real
    repository. Drop `_check_v11` from `assemble_library` and this fails; nothing else in the
    suite does, because every other V11 test is either handed the value or reads the scanner
    directly.

    The finding names the root and the destination, because both are the diagnosis: the user
    made that link and is the only one who can decide what should happen to it.

    **It asserts the warning and nothing else**, deliberately. This is mutation (b)'s
    must-stay-green control as well, and a control that also asserted the artifact's absence
    would redden under (b) — which follows the link and so makes the artifact appear — taking
    its own control away. The absence is the test below; the two facts are separated because two
    different mutations reach them.
    """
    warnings = [f for f in library.library_findings() if f.code is ValidationCode.V11]

    assert len(warnings) == 1
    assert warnings[0].severity is Severity.WARNING
    assert warnings[0].path == LINKED_ROOT
    assert LINK_DESTINATION in warnings[0].message
    assert LINKED_ID in warnings[0].message


def test_the_symlinked_root_is_in_no_listing_the_library_can_produce(
    library: FilesystemArtifactRepository,
) -> None:
    """**The omission itself** — the fact V11 exists to make visible, asserted at the layer that
    produces it. R6 never walks the root, so no `Artifact` is built, so the skill appears in no
    `hl list`, no `hl search` and no install.

    The second assertion is the positive control: `skill/delivery-lead` *is* listed, so "absent"
    is a fact about this artifact and not about a library that came back empty.
    """
    listed = {artifact.id for artifact in library.list_all()}

    assert LINKED_ID not in listed
    assert "skill/delivery-lead" in listed


def test_the_warning_is_a_warning_and_the_library_is_still_reported_on(
    library: FilesystemArtifactRepository,
) -> None:
    """R22, kept where it belongs. V11 refuses **one install**; it does not make the library
    invalid, it does not stop `hl validate` exiting on its own verdict, and it does not silence
    the other library-level rules. The V7 findings beside it are the control."""
    codes = [f.code for f in library.library_findings()]

    assert ValidationCode.V11 in codes
    assert ValidationCode.V7 in codes
    assert all(
        f.severity is Severity.WARNING
        for f in library.library_findings()
        if f.code is ValidationCode.V11
    )


# -------------------------------------------------------------------------------------------
# The refusal — ruling R46's second half, and R53's per-artifact scope
# -------------------------------------------------------------------------------------------


def test_the_symlinked_root_is_skipped_in_the_plan_and_the_run_is_incomplete(
    library: FilesystemArtifactRepository, target_root: Path, state_root: Path
) -> None:
    """**The must-stay-green control of mutation (a).**

    It reads `symlinked_roots()`, never a finding, so dropping V11 from the report leaves it
    untouched — which is the whole reason the refusal is built from the scanner's values. It
    would be worthless as a control otherwise: warning and refusal would be one fact wearing two
    names.

    The entry carries a reason naming the rule, because C-10 makes a plan explain its skips
    without a second lookup, and the run comes back incomplete so a caller exits
    `INCOMPLETE = 6` rather than reporting a clean install of a library one of whose skills it
    never saw.
    """
    plan = plan_for(library, target_root)
    entry = skipped_entry(plan, LINKED_ROOT)

    assert entry.verdict is Verdict.SKIPPED
    assert entry.artifact_id == LINKED_ID
    assert entry.reason is not None
    assert "V11" in entry.reason
    assert LINK_DESTINATION in entry.reason
    assert plan.is_complete is False

    apply(plan, library, target_root, state_root)


def test_neither_the_symlinked_root_nor_its_destination_is_written(
    library: FilesystemArtifactRepository, target_root: Path, state_root: Path
) -> None:
    """**The must-fail assertion of mutation (b)**, and the criterion asserted on both halves.

    Remove `_artifact_name`'s `is_symlink` guard and the scan walks straight through the link:
    the destination becomes an ordinary artifact, and its bytes land in the user's target under
    a path the library only pretends to hold. The first assertion is the one that catches it —
    the destination's content reaches **nowhere** in the target — and it is written over the
    bytes rather than over the path, because a path assertion goes green the moment somebody
    renames the fixture.

    The link itself is not written either: nothing at `skills/linked-skill`, as a link or as a
    directory. And the destination file is byte-identical, which is the other direction of the
    same rule — install reads a library and must not write into one.

    The warning test above is the must-stay-green control, and it is: detection lives in
    `_scan_type` and does not depend on this guard.
    """
    destination_before = DESTINATION.read_bytes()

    apply(plan_for(library, target_root), library, target_root, state_root)

    assert destination_before not in contents_under(target_root).values()
    assert not (target_root / LINKED_ROOT).exists()
    assert not (target_root / LINKED_ROOT).is_symlink()
    assert DESTINATION.read_bytes() == destination_before


def test_every_other_artifact_is_still_applied(
    library: FilesystemArtifactRepository, target_root: Path, state_root: Path
) -> None:
    """**Ruling R53: the refusal is per artifact, not per run.**

    Without this, "the linked skill was not written" is satisfied by a run that refused
    everything — which is the failure mode R53 is a ruling against, and the one a user would
    notice as their whole harness disappearing because of one link.
    """
    written = apply(plan_for(library, target_root), library, target_root, state_root)

    for path in SOUND_ARTIFACTS:
        assert (target_root / path).is_file(), path
        assert path in written


def test_force_does_not_install_a_symlinked_root(
    library: FilesystemArtifactRepository, target_root: Path, state_root: Path
) -> None:
    """**The one difference from R75's refusal.** `--force` installs an artifact whose errors the
    user has decided to accept, because its bytes are right there. Here there are none: forcing
    could only mean following the link, which R6 forbids, or writing over it, which destroys it.

    The control is in the same test: `force=True` really is in effect, because an artifact R75
    would otherwise have refused — `skill/no-entry` carries V1 — is no longer `SKIPPED`.
    """
    plan = plan_for(library, target_root, force=True)

    assert skipped_entry(plan, LINKED_ROOT).verdict is Verdict.SKIPPED
    assert Verdict.SKIPPED not in {
        entry.verdict for entry in plan.entries if entry.path != LINKED_ROOT
    }

    apply(plan, library, target_root, state_root)

    assert not (target_root / LINKED_ROOT).exists()


def test_a_symlinked_root_the_target_also_holds_keeps_its_skip_and_is_not_removable(
    library: FilesystemArtifactRepository, target_root: Path, state_root: Path
) -> None:
    """The realistic collision, and why the entry is replaced rather than doubled.

    A developer who links `skills/linked-skill` in their library usually has the same link in
    their harness. The target scan reports it, so the plan would otherwise hold two entries for
    one path: `FOREIGN` from the join and `SKIPPED` from V11. One path, one entry — and the one
    that survives is the skip, which also stops `clean --foreign` offering to delete the link
    R22's exception exists to protect.

    Asserted on the file as well: the link is still a link afterwards, with the destination it
    had.
    """
    (target_root / "skills").mkdir()
    (target_root / LINKED_ROOT).symlink_to("../../elsewhere/linked-skill")

    plan = plan_for(library, target_root)
    entry = skipped_entry(plan, LINKED_ROOT)

    assert entry.verdict is Verdict.SKIPPED
    assert entry.target_sha is not None, "the target really does hold that path"

    apply(plan, library, target_root, state_root)

    assert (target_root / LINKED_ROOT).is_symlink()
    assert (target_root / LINKED_ROOT).readlink() == Path("../../elsewhere/linked-skill")


# -------------------------------------------------------------------------------------------
# The fixture itself
# -------------------------------------------------------------------------------------------


def test_the_committed_fixture_library_is_untouched(tmp_path: Path) -> None:
    """Charter §10 keeps these trees forever, and a run that wrote into the committed one would
    break every test above once and pass ever after.

    The copy is the positive control: `copytree(symlinks=True)` reproduces the link, so the
    fixture really is a link on disk and not a directory that happens to be named like one.
    """
    assert (FIXTURE_LIBRARY / LINKED_ROOT).is_symlink()
    assert (FIXTURE_LIBRARY / LINKED_ROOT).readlink() == Path(LINK_DESTINATION)
    assert DESTINATION.is_file()

    copy = tmp_path / "copy"
    shutil.copytree(FIXTURE_LIBRARY, copy, symlinks=True)
    assert (copy / LINKED_ROOT).is_symlink()
