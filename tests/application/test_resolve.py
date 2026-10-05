"""`--resolve` — the write-side use cases that settle a refusal. T-21, feature F-15, ruling R54.

Fakes only, zero disk (charter §10). **No test in this module launches `$EDITOR`**, and none can:
the editor is a protocol, `FakeConflictEditor` keeps what it was shown, and even the real adapter
is proven in `tests/infrastructure/test_editor.py` with an injected runner. A test that spawned an
editor would hang CI on a buffer nobody will ever close.

**Every byte-identical assertion in this module reads the target's content**, through
`FakeTargetRepository.snapshot`, and never the write recorder. A recorder can be empty because
nothing was written or because nothing recorded it; the file cannot.

What this layer cannot see: that a real write lands at `0644`, that a real backup reaches a real
directory, or that a real editor is ever started. Those are `tests/infrastructure/`'s. What it
*can* see is the only thing these use cases decide — which entries are acted on, which side is
taken, what the record says afterwards, and that nothing else moved.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from loom.application.read.drift import UNHASHED_TARGET_SHA, diff_against_target
from loom.application.write import (
    ComparisonResult,
    ResolveResult,
    compare_versions,
    plan_install,
    resolve_conflict,
)
from loom.domain.errors import (
    BackupFailedError,
    ErrorCode,
    LockHeldError,
    ManifestWriteError,
    NothingToResolveError,
    TargetUnwritableError,
)
from loom.domain.hashing import hash_bytes
from loom.domain.identity import ArtifactType
from loom.domain.install_plan import InstallPlan, Verdict
from loom.domain.manifest import Manifest
from loom.domain.raw import SymlinkedRoot
from loom.domain.resolution import Resolution
from loom.domain.target import TargetFile
from tests.application.fakes import (
    TARGET_PATH,
    FakeArtifactRepository,
    FakeBackupStore,
    FakeConflictEditor,
    FakeManifestStore,
    FakeTargetRepository,
    FakeWriteLock,
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

LIBRARY_BYTES = b"# the library has moved on\n"
INSTALLED_BYTES = b"# what this tool installed\n"
EDITED_BYTES = b"# and then the user edited it\n"

RESOLVED_AT = datetime(2026, 9, 21, 18, 45, tzinfo=UTC)
"""When every resolution in this module ran. A parameter, never a clock (R66)."""

LIBRARY_SHA = "f" * 40
"""The library commit a `LIBRARY` resolution records. Shaped like one; never looked up."""


# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


def installed_path(name: str) -> str:
    """Where one single-file skill's entry lands in the target."""
    return f"skills/{name}/{ENTRY}"


def a_library(*names: str, body: bytes = LIBRARY_BYTES) -> FakeArtifactRepository:
    """A library holding one single-file skill per name, all with the same body."""
    artifacts = [make_artifact(name, files=(make_file(ENTRY, body),)) for name in names]
    return FakeArtifactRepository(
        artifacts, contents={(artifact.id, ENTRY): body for artifact in artifacts}
    )


def a_manifest(*names: str, body: bytes = INSTALLED_BYTES) -> Manifest:
    """A manifest recording one single-file skill per name, at `body`'s digest."""
    return manifest_of(
        *(manifest_artifact(f"skill/{name}", (make_file(ENTRY, body),)) for name in names)
    )


def a_conflict(*names: str) -> tuple[FakeArtifactRepository, FakeTargetRepository, Manifest]:
    """One three-way conflict per name: three different versions of one path.

    The library, the manifest and the target each hold something different, which is C-9's
    four-way `CONFLICT` — the shape a user is most likely to meet and the one both sides of
    `--resolve` have to handle.
    """
    return (
        a_library(*names),
        target_holding(*((installed_path(name), EDITED_BYTES) for name in names)),
        a_manifest(*names),
    )


def plan_of(
    library: FakeArtifactRepository,
    target: FakeTargetRepository,
    manifest: Manifest | None,
) -> InstallPlan:
    """The plan a real install would execute, decided by the rule rather than by hand.

    Built through `plan_install` and not from literals, unlike `test_install.py`'s: a resolution
    reads `reason`, and ruling R61 says only `plan_entry_for` writes a conflict's.
    """
    return plan_install(library, target, manifest=manifest, unscannable=())


def resolve(
    plan: InstallPlan,
    library: FakeArtifactRepository,
    target: FakeTargetRepository,
    *,
    manifest: Manifest | None,
    resolution: Resolution,
    artifact_id: str = SKILL_ID,
    backups: FakeBackupStore | None = None,
    manifests: FakeManifestStore | None = None,
    lock: FakeWriteLock | None = None,
) -> ResolveResult:
    """`resolve_conflict` with this module's fixed instant and target path.

    A fresh `FakeWriteLock` unless one is given, so **every resolution here runs under a lock**
    (R82) — which is the point, and which is why the helper supplies one rather than letting each
    test decide whether this run is the locked kind.
    """
    return resolve_conflict(
        plan,
        library,
        target,
        backups if backups is not None else FakeBackupStore(target),
        manifests if manifests is not None else FakeManifestStore(),
        lock=lock if lock is not None else FakeWriteLock(),
        manifest=manifest,
        artifact_id=artifact_id,
        resolution=resolution,
        target_path=TARGET_PATH,
        installed_at=RESOLVED_AT,
        library_git_sha=LIBRARY_SHA,
    )


def compare(
    plan: InstallPlan,
    library: FakeArtifactRepository,
    target: FakeTargetRepository,
    *,
    editor: FakeConflictEditor,
    artifact_id: str = SKILL_ID,
    lock: FakeWriteLock | None = None,
) -> ComparisonResult:
    """`compare_versions` with this module's defaults. Plumbing only."""
    return compare_versions(
        plan,
        library,
        target,
        editor,
        lock=lock if lock is not None else FakeWriteLock(),
        artifact_id=artifact_id,
    )


def recorded(manifest: Manifest | None, artifact_id: str, path: str) -> str | None:
    """The digest a manifest records for one artifact-root-relative path, or `None`.

    `None` covers both "no such artifact" and "no such file", because every assertion below that
    cares about the difference says so in its own words.
    """
    if manifest is None:
        return None
    for record in manifest.artifacts:
        if record.artifact_id != artifact_id:
            continue
        for file in record.files:
            if file.path == path:
                return file.sha256
    return None


def verdict_at(plan: InstallPlan, path: str) -> Verdict | None:
    """What a plan says about one target path, or `None` when it says nothing."""
    return next((entry.verdict for entry in plan.entries if entry.path == path), None)


# -------------------------------------------------------------------------------------------
# F-15 — the two sides, and the mutation subjects
# -------------------------------------------------------------------------------------------


def test_resolve_library_writes_the_librarys_version_and_records_it() -> None:
    """**F-15's first half, and the must-stay-green control for both of T-21's mutations.**

    The library's bytes land at the refused path and the manifest records the library's digest:
    after this run the tool's record and the target agree, which is what makes the path stop
    being refused.

    Its plan holds **exactly one** blocking entry, belonging to the named artifact, which is what
    makes it a control for the per-artifact mutation: widening the entry filter selects the same
    single entry, so the mutation cannot pass here by resolving nothing. Nothing it asserts is
    about `resolve target`, which keeps it a control for that mutation too (L57).
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    manifests = FakeManifestStore()

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        manifests=manifests,
        resolution=Resolution.LIBRARY,
    )

    assert target.snapshot()[INSTALLED_ENTRY] == LIBRARY_BYTES
    assert result.written == (INSTALLED_ENTRY,)
    assert recorded(manifests.latest, SKILL_ID, ENTRY) == hash_bytes(LIBRARY_BYTES)
    assert result.is_complete


def test_resolve_target_leaves_the_file_byte_identical_and_repairs_the_record() -> None:
    """**F-15's second half, and the must-fail assertion of mutation (b)** (`resolve target`
    writes the library's bytes instead of only repairing the record).

    Asserted on the file's **bytes** and not on the report: a report saying "I wrote nothing" is
    exactly what the wrong implementation also says. The record is asserted in the same test,
    because "left the file alone" without "changed the record" is a run that did nothing at all.

    The digest recorded is **the target's current bytes** — this is the one operation in the
    initiative that makes the tool claim a file it did not put there, which is precisely what the
    user asked for.
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    manifests = FakeManifestStore()

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        manifests=manifests,
        resolution=Resolution.TARGET,
    )

    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert target.writes == []
    assert result.written == ()
    assert result.repaired == (INSTALLED_ENTRY,)
    assert recorded(manifests.latest, SKILL_ID, ENTRY) == hash_bytes(EDITED_BYTES)
    assert result.is_complete


def test_resolving_one_conflict_leaves_the_other_refused_and_byte_identical() -> None:
    """**F-15's per-artifact criterion, and the must-fail assertion of mutation (a)** (`--resolve`
    applies to every conflicted artifact rather than the named one).

    Two artifacts, both conflicted, one named. The other must come out untouched on **all three**
    counts a user would notice: its file's bytes, its record's digest, and the verdict the next
    diff reaches for it — which is still refused, so the run is still incomplete. A resolution
    that quietly decided both would look identical in every report.

    The positive control is the first assertion: the *named* artifact really was resolved, so
    "the other is unchanged" cannot mean "nothing happened".
    """
    library, target, manifest = a_conflict(SKILL_NAME, OTHER_NAME)
    manifests = FakeManifestStore()

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        artifact_id=SKILL_ID,
        manifests=manifests,
        resolution=Resolution.LIBRARY,
    )

    assert target.snapshot()[INSTALLED_ENTRY] == LIBRARY_BYTES
    assert target.snapshot()[INSTALLED_OTHER] == EDITED_BYTES
    assert result.written == (INSTALLED_ENTRY,)
    assert recorded(manifests.latest, OTHER_ID, ENTRY) == hash_bytes(INSTALLED_BYTES)

    after = diff_against_target(library, target, manifest=manifests.latest)
    assert verdict_at(after, INSTALLED_OTHER) is Verdict.CONFLICT
    assert not after.is_complete


def test_a_resolved_path_stops_being_refused() -> None:
    """The point of the whole feature, asserted as the verdict the next diff reaches.

    Both sides are checked, because "it stops being refused" is the claim and the two sides reach
    it by different routes: taking the library's version makes all three digests agree, and
    taking the target's makes the record agree with the disk so the library's newer copy becomes
    an ordinary, safe `UPDATE`.

    **`resolve target` therefore settles the refusal rather than pinning the file.** The manifest
    is a record of what was installed and not a preference, so a library that has moved on will
    install over the resolved path on the next run — no edit is being lost at that point, because
    the record says the target holds what this tool put there. Anything stronger would need a
    concept C-9 and C-11 do not have.
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    before = plan_of(library, target, manifest)
    assert verdict_at(before, INSTALLED_ENTRY) is Verdict.CONFLICT

    manifests = FakeManifestStore()
    resolve(
        before,
        library,
        target,
        manifest=manifest,
        manifests=manifests,
        resolution=Resolution.TARGET,
    )

    after = diff_against_target(library, target, manifest=manifests.latest)
    assert verdict_at(after, INSTALLED_ENTRY) is not Verdict.CONFLICT
    assert verdict_at(after, INSTALLED_ENTRY) is Verdict.UPDATE
    assert after.is_complete


def test_a_local_edit_is_resolvable_just_as_a_conflict_is() -> None:
    """`RESOLVABLE_VERDICTS` holds both, and a `LOCAL_EDIT` is the commoner of the two: the
    library still holds what was installed and the user edited the target out of band. Taking
    the library's side puts the library's bytes back, which is the whole of "undo my edit"."""
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, EDITED_BYTES))
    manifest = a_manifest(SKILL_NAME, body=LIBRARY_BYTES)
    plan = plan_of(library, target, manifest)
    assert verdict_at(plan, INSTALLED_ENTRY) is Verdict.LOCAL_EDIT

    result = resolve(plan, library, target, manifest=manifest, resolution=Resolution.LIBRARY)

    assert target.snapshot()[INSTALLED_ENTRY] == LIBRARY_BYTES
    assert result.written == (INSTALLED_ENTRY,)


def test_a_path_that_is_not_refused_is_never_touched_by_a_resolution() -> None:
    """One artifact, two paths: one refused and one already correct. Only the refused one moves.

    Without this, "resolution is per artifact" could still mean "and every path of it", which
    would rewrite files nobody asked about — and `UNCHANGED` is exactly the verdict whose whole
    content is that there is nothing to decide.
    """
    artifact = make_artifact(
        SKILL_NAME,
        files=(make_file(ENTRY, LIBRARY_BYTES), make_file(REFERENCE, INSTALLED_BYTES)),
    )
    library = FakeArtifactRepository(
        [artifact],
        contents={(SKILL_ID, ENTRY): LIBRARY_BYTES, (SKILL_ID, REFERENCE): INSTALLED_BYTES},
    )
    target = target_holding((INSTALLED_ENTRY, EDITED_BYTES), (INSTALLED_REFERENCE, INSTALLED_BYTES))
    manifest = manifest_of(
        manifest_artifact(
            SKILL_ID,
            (make_file(ENTRY, INSTALLED_BYTES), make_file(REFERENCE, INSTALLED_BYTES)),
        )
    )

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        resolution=Resolution.LIBRARY,
    )

    assert result.written == (INSTALLED_ENTRY,)
    assert target.snapshot()[INSTALLED_REFERENCE] == INSTALLED_BYTES
    assert [path for path, _ in target.writes] == [INSTALLED_ENTRY]


# -------------------------------------------------------------------------------------------
# The conflict shapes neither side can take, and the one only the target can
# -------------------------------------------------------------------------------------------


def a_library_that_dropped_it() -> tuple[FakeArtifactRepository, FakeTargetRepository, Manifest]:
    """The conflict shape where the library no longer holds the path and the target edited it."""
    return (
        FakeArtifactRepository([]),
        target_holding((INSTALLED_ENTRY, EDITED_BYTES)),
        a_manifest(SKILL_NAME),
    )


def test_resolve_library_refuses_a_path_the_library_no_longer_holds() -> None:
    """There is no version to take, and taking "the library's side" could only mean **deleting a
    file the user has edited**.

    Refused rather than deleted, because a resolution that both created and destroyed files would
    have to hold two record orderings and choose between them at runtime (charter §13b) — the one
    thing R63's position in apply exists to make impossible. It is not a dead end, which the next
    test proves: the target side resolves this shape.
    """
    library, target, manifest = a_library_that_dropped_it()
    manifests = FakeManifestStore()

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        manifests=manifests,
        resolution=Resolution.LIBRARY,
    )

    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert result.written == ()
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == [INSTALLED_ENTRY]
    assert "--resolve target" in str(result.left_alone[0].reason)
    assert manifests.written == []


def test_resolve_target_settles_the_shape_the_library_side_refuses() -> None:
    """The other half of the test above, and the reason the refusal is not a dead end.

    Keeping what is on disk records the target's digest, after which the manifest and the target
    agree and the library holds nothing — which is `PRUNE`, a safe verdict `--prune` acts on
    under its own record-last ordering.
    """
    library, target, manifest = a_library_that_dropped_it()
    manifests = FakeManifestStore()

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        manifests=manifests,
        resolution=Resolution.TARGET,
    )

    assert result.repaired == (INSTALLED_ENTRY,)
    assert recorded(manifests.latest, SKILL_ID, ENTRY) == hash_bytes(EDITED_BYTES)
    assert result.is_complete

    after = diff_against_target(library, target, manifest=manifests.latest)
    assert verdict_at(after, INSTALLED_ENTRY) is Verdict.PRUNE


def test_resolve_target_drops_a_path_the_target_no_longer_holds() -> None:
    """Keeping what is on disk, where what is on disk is **nothing**: the record stops naming it.

    Charter §13b is satisfied rather than bent — the rule forbids disowning a file that is still
    on disk, and this path is not. The artifact's record is left with no file and is dropped
    whole, which is the decision apply, prune and rollback all make.
    """
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository()
    manifest = a_manifest(SKILL_NAME)
    plan = plan_of(library, target, manifest)
    assert verdict_at(plan, INSTALLED_ENTRY) is Verdict.CONFLICT
    manifests = FakeManifestStore()

    result = resolve(
        plan, library, target, manifest=manifest, manifests=manifests, resolution=Resolution.TARGET
    )

    assert result.dropped == (INSTALLED_ENTRY,)
    assert result.repaired == ()
    assert target.writes == []
    assert manifests.latest is not None
    assert manifests.latest.artifacts == ()


def test_resolve_target_records_a_path_no_manifest_ever_recorded() -> None:
    """The commonest first-run conflict: a target already holding a hand-copied file, and no
    manifest at all. `manifest=None` is a real value, and the resolution is how a user settles it.

    The new record is built from nothing, so `target_path` has to come from the parameter rather
    than from a previous manifest — a first install has none to take it from.
    """
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, EDITED_BYTES))
    plan = plan_of(library, target, None)
    assert verdict_at(plan, INSTALLED_ENTRY) is Verdict.CONFLICT
    manifests = FakeManifestStore()

    result = resolve(
        plan, library, target, manifest=None, manifests=manifests, resolution=Resolution.TARGET
    )

    assert recorded(manifests.latest, SKILL_ID, ENTRY) == hash_bytes(EDITED_BYTES)
    assert result.manifest is not None
    assert result.manifest.target_path == TARGET_PATH
    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES


@pytest.mark.parametrize("resolution", list(Resolution), ids=lambda one: one.value)
def test_a_symlinked_target_path_is_resolvable_by_neither_side(resolution: Resolution) -> None:
    """**Ruling R72.** `UNHASHED_TARGET_SHA` means the target holds the path and its content was
    never read — today, a symlink.

    Taking the library's side would write *through* the link, which is the escape R6 exists to
    prevent and which C-12's `write` refuses outright. Taking the target's would mean recording a
    digest of content nobody read, and `<unhashed>` is a plan-time sentinel rather than a digest.
    So both sides refuse, and the reason names the link rather than leaving the user to guess.
    """
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository((target_symlink(INSTALLED_ENTRY),))
    manifest = a_manifest(SKILL_NAME)
    plan = plan_of(library, target, manifest)
    assert next(one.target_sha for one in plan.entries if one.path == INSTALLED_ENTRY) == (
        UNHASHED_TARGET_SHA
    )
    manifests = FakeManifestStore()

    result = resolve(
        plan, library, target, manifest=manifest, manifests=manifests, resolution=resolution
    )

    assert target.writes == []
    assert manifests.written == []
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == [INSTALLED_ENTRY]
    assert "symlink" in str(result.left_alone[0].reason)


@pytest.mark.parametrize("resolution", list(Resolution), ids=lambda one: one.value)
def test_a_skipped_artifact_is_not_resolvable_by_either_side(resolution: Resolution) -> None:
    """**Ruling R99: `--resolve` does not lift V11, and neither does `--force`.**

    A symlinked artifact root was never scanned, so the library holds no bytes for it and there
    are no two versions to choose between. The entry keeps its **own** V11 reason — the sentence
    that names the link and the rule — rather than acquiring one written by the resolution, which
    is what a user has to act on.
    """
    library = a_library(OTHER_NAME)
    target = FakeTargetRepository()
    root = SymlinkedRoot(
        type=ArtifactType.SKILL, name=SKILL_NAME, destination="../../outside/delivery-lead"
    )
    plan = plan_install(library, target, manifest=None, unscannable=(root,))
    manifests = FakeManifestStore()

    result = resolve(
        plan,
        library,
        target,
        manifest=None,
        manifests=manifests,
        artifact_id=SKILL_ID,
        resolution=resolution,
    )

    assert target.writes == []
    assert manifests.written == []
    assert result.manifest is None
    assert not result.is_complete
    assert [refused.path for refused in result.left_alone] == ["skills/delivery-lead"]
    assert "V11" in str(result.left_alone[0].reason)


def test_an_artifact_this_plan_refuses_nothing_about_is_a_loud_failure() -> None:
    """Charter §13's posture. A resolution that silently did nothing would be indistinguishable
    from one that resolved everything, and the user has just been told a run was incomplete — so
    "there was nothing to decide" is news.

    The positive control is in the same test: the *other* artifact, which really is refused,
    resolves through the same plan. Without it, "it raised" could mean the helper is broken.
    """
    library = a_library(SKILL_NAME, OTHER_NAME)
    target = target_holding((INSTALLED_ENTRY, LIBRARY_BYTES), (INSTALLED_OTHER, EDITED_BYTES))
    manifest = manifest_of(
        manifest_artifact(SKILL_ID, (make_file(ENTRY, LIBRARY_BYTES),)),
        manifest_artifact(OTHER_ID, (make_file(ENTRY, INSTALLED_BYTES),)),
    )
    plan = plan_of(library, target, manifest)

    with pytest.raises(NothingToResolveError) as refused:
        resolve(
            plan,
            library,
            target,
            manifest=manifest,
            artifact_id=SKILL_ID,
            resolution=Resolution.LIBRARY,
        )

    assert refused.value.code is ErrorCode.ARTIFACT_NOT_FOUND
    assert refused.value.artifact_id == SKILL_ID

    other = resolve(
        plan,
        library,
        target,
        manifest=manifest,
        artifact_id=OTHER_ID,
        resolution=Resolution.LIBRARY,
    )
    assert other.written == (INSTALLED_OTHER,)


def test_an_artifact_the_plan_says_nothing_about_is_the_same_loud_failure() -> None:
    """The other shape of "nothing", and it is the same answer: a user acts on both by going and
    looking at what is actually refused, which is what `ARTIFACT_NOT_FOUND`'s remedy already
    says."""
    library, target, manifest = a_conflict(SKILL_NAME)

    with pytest.raises(NothingToResolveError, match="says nothing about it"):
        resolve(
            plan_of(library, target, manifest),
            library,
            target,
            manifest=manifest,
            artifact_id="skill/never-existed",
            resolution=Resolution.TARGET,
        )


# -------------------------------------------------------------------------------------------
# R86, R88, R82 — the order, the backup and the lock
# -------------------------------------------------------------------------------------------


def test_the_record_is_on_disk_before_the_first_file_is_written() -> None:
    """**Ruling R86 for `resolve library`, which makes files appear.**

    Proven by injecting a failure into the first write and finding the record already there: a
    run that does not fail cannot tell the two orders apart (L52). Under the other order a crash
    here would leave a written file claimed by nobody — `FOREIGN`, which install will not touch
    and uninstall cannot remove.
    """
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository(
        (target_file(INSTALLED_ENTRY, EDITED_BYTES),),
        contents={INSTALLED_ENTRY: EDITED_BYTES},
        fail_write_after=0,
    )
    manifest = a_manifest(SKILL_NAME)
    manifests = FakeManifestStore()

    with pytest.raises(TargetUnwritableError):
        resolve(
            plan_of(library, target, manifest),
            library,
            target,
            manifest=manifest,
            manifests=manifests,
            resolution=Resolution.LIBRARY,
        )

    assert manifests.latest is not None, (
        "the record must already be on disk when the first file write happens (R86): a file "
        "written after a record that does not name it reads FOREIGN and nothing can reach it"
    )
    assert recorded(manifests.latest, SKILL_ID, ENTRY) == hash_bytes(LIBRARY_BYTES)


def test_a_record_that_cannot_be_written_leaves_the_target_byte_identical() -> None:
    """`MANIFEST_UNWRITABLE = 11` keeps its promise here: **nothing happened**.

    Both resolutions satisfy it for different reasons — a `LIBRARY` run has not reached its first
    write when the record fails, and a `TARGET` run moves no file at all — which is why this
    module raises `ManifestWriteError` and never `RecordStaleError`.
    """
    library, target, manifest = a_conflict(SKILL_NAME)

    with pytest.raises(ManifestWriteError) as failed:
        resolve(
            plan_of(library, target, manifest),
            library,
            target,
            manifest=manifest,
            manifests=FakeManifestStore(fail=True),
            resolution=Resolution.LIBRARY,
        )

    assert failed.value.code is ErrorCode.MANIFEST_UNWRITABLE
    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert target.writes == []


def test_resolve_library_backs_up_every_path_it_will_write_before_writing_one() -> None:
    """**Ruling R88.** This is the only operation in the project that deliberately destroys an
    edit of the user's — apply refuses precisely these paths for that reason — so a copy of what
    it is about to discard is the point rather than a formality.

    The backup names the path the run writes and nothing else: a backup wider than the run would
    make a rollback of it undo things this run never touched.
    """
    library, target, manifest = a_conflict(SKILL_NAME, OTHER_NAME)
    backups = FakeBackupStore(target)

    resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        backups=backups,
        resolution=Resolution.LIBRARY,
    )

    assert backups.created == [(INSTALLED_ENTRY,)]


def test_resolve_library_refuses_when_the_backup_cannot_be_taken() -> None:
    """F-9's refusal, unchanged: a write with no way back is the failure mode this initiative
    exists to remove. **Nothing is written and nothing is recorded** — the backup comes first."""
    library, target, manifest = a_conflict(SKILL_NAME)
    manifests = FakeManifestStore()

    with pytest.raises(BackupFailedError) as refused:
        resolve(
            plan_of(library, target, manifest),
            library,
            target,
            manifest=manifest,
            backups=FakeBackupStore(target, fail=True),
            manifests=manifests,
            resolution=Resolution.LIBRARY,
        )

    assert refused.value.code is ErrorCode.BACKUP_FAILED
    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert manifests.written == []


def test_resolve_target_takes_no_backup_because_it_writes_no_file() -> None:
    """**R88's other half, argued.** There is no target path whose bytes could be copied: the
    only thing this run changes is a record, and no backup in this project describes one.

    The control is the previous test: a `LIBRARY` resolution over the same plan does take one, so
    "no backup" here is a fact about this side rather than about this harness.
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    backups = FakeBackupStore(target)

    result = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        backups=backups,
        resolution=Resolution.TARGET,
    )

    assert backups.created == []
    assert result.backup_id is None


def test_a_run_that_resolves_nothing_writes_no_record_at_all() -> None:
    """A resolution that refused everything must leave no trace of having run.

    `CleanResult.manifest`'s rule, for a sharper reason: a target with no manifest must not
    acquire one from a run that resolved nothing, because a manifest recording zero artifacts is
    a real and different fact — it means this target was installed into and then emptied.
    """
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository((target_symlink(INSTALLED_ENTRY),))
    manifests = FakeManifestStore()

    result = resolve(
        plan_of(library, target, None),
        library,
        target,
        manifest=None,
        manifests=manifests,
        resolution=Resolution.TARGET,
    )

    assert manifests.written == []
    assert result.manifest is None
    assert not result.is_complete


def test_the_record_a_resolution_leaves_names_the_library_only_when_it_installed_from_it() -> None:
    """`library_git_sha` is a claim about where the files came from.

    A `LIBRARY` resolution really did install from that library state, so it records it. A
    `TARGET` resolution installed nothing, so the record keeps whatever the previous manifest
    said — the same rule prune and uninstall keep, and for the same reason: this run moved no
    artifact's provenance.
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    from_library = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        resolution=Resolution.LIBRARY,
    )

    library, target, manifest = a_conflict(SKILL_NAME)
    from_target = resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        resolution=Resolution.TARGET,
    )

    assert from_library.manifest is not None
    assert from_library.manifest.library_git_sha == LIBRARY_SHA
    assert from_target.manifest is not None
    assert from_target.manifest.library_git_sha == manifest.library_git_sha


@pytest.mark.parametrize(
    "use_case", [resolve_conflict, compare_versions], ids=lambda one: one.__name__
)
def test_the_lock_is_required_and_keyword_only(use_case: object) -> None:
    """**Ruling R82, C-16.** A write path that simply does not take a lock keeps every gate green
    while sitting outside charter §12, so the parameter is required and has no default — a
    default would make running unlocked a typo rather than a decision."""
    parameter = inspect.signature(use_case).parameters["lock"]  # type: ignore[arg-type]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_a_resolution_takes_the_lock_and_releases_it() -> None:
    """Held around the backup, the record and every write, and released however the run ends.

    The control is the failure case below: a run that raises releases it too, which is what a
    leaked lock on the error path would break — and a lock leaked after something has already
    gone wrong is worse than no lock at all.
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    lock = FakeWriteLock()

    resolve(
        plan_of(library, target, manifest),
        library,
        target,
        manifest=manifest,
        lock=lock,
        resolution=Resolution.LIBRARY,
    )

    assert lock.events == ["acquired", "released"]
    assert not lock.held


def test_the_lock_is_released_when_a_resolution_fails() -> None:
    library, target, manifest = a_conflict(SKILL_NAME)
    lock = FakeWriteLock()

    with pytest.raises(BackupFailedError):
        resolve(
            plan_of(library, target, manifest),
            library,
            target,
            manifest=manifest,
            backups=FakeBackupStore(target, fail=True),
            lock=lock,
            resolution=Resolution.LIBRARY,
        )

    assert lock.events == ["acquired", "released"]


def test_a_resolution_against_a_held_lock_changes_nothing() -> None:
    """Charter §12: one writer per target. A resolution is a write, so it waits its turn — and
    `LOCK_HELD` means nothing was written, which the target's content asserts."""
    library, target, manifest = a_conflict(SKILL_NAME)
    manifests = FakeManifestStore()

    with pytest.raises(LockHeldError):
        resolve(
            plan_of(library, target, manifest),
            library,
            target,
            manifest=manifest,
            manifests=manifests,
            lock=FakeWriteLock(held_by_another=True),
            resolution=Resolution.LIBRARY,
        )

    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES
    assert manifests.written == []


# -------------------------------------------------------------------------------------------
# `$EDITOR` — the seam, and what it is shown
# -------------------------------------------------------------------------------------------


def test_the_editor_is_shown_both_versions_of_a_refused_path() -> None:
    """R54's third way. Both versions, in one session, and nothing is decided.

    The library's bytes come through C-4 and the target's through C-12, so the user sees exactly
    what each side holds rather than a rendering of two digests.
    """
    library, target, manifest = a_conflict(SKILL_NAME)
    editor = FakeConflictEditor()

    result = compare(plan_of(library, target, manifest), library, target, editor=editor)

    assert result.compared == (INSTALLED_ENTRY,)
    assert [version.path for version in editor.shown] == [INSTALLED_ENTRY]
    assert editor.shown[0].library == LIBRARY_BYTES
    assert editor.shown[0].target == EDITED_BYTES


def test_comparing_versions_writes_nothing_and_records_nothing() -> None:
    """The whole of what this use case does to a disk, asserted as an absence — with the positive
    control in the same test: the recorder really does record a write when one is made."""
    library, target, manifest = a_conflict(SKILL_NAME)

    compare(plan_of(library, target, manifest), library, target, editor=FakeConflictEditor())

    assert target.writes == []
    assert target.deletes == []
    assert target.snapshot()[INSTALLED_ENTRY] == EDITED_BYTES

    target.write("proof.md", b"the recorder works\n")
    assert target.writes == [("proof.md", b"the recorder works\n")]


def test_an_unreadable_target_side_is_named_rather_than_left_blank() -> None:
    """**Ruling R72, at the one place a user sees it.** `$EDITOR` cannot fetch the content of a
    path the scan never read, and a symlink is exactly that: the target holds it and R6 will not
    follow it.

    So the comparison carries the library's version and a reason instead of the target's bytes.
    Showing an empty pane would say *this version is empty*, which is a different and confidently
    wrong answer from *there is something here I will not read through*.

    The control is the sibling path in the same session: an ordinary refused file **does** come
    back with its target bytes, so "no bytes" here is a fact about the link rather than about the
    comparison.
    """
    artifact = make_artifact(
        SKILL_NAME,
        files=(make_file(ENTRY, LIBRARY_BYTES), make_file(REFERENCE, LIBRARY_BYTES)),
    )
    library = FakeArtifactRepository(
        [artifact],
        contents={(SKILL_ID, ENTRY): LIBRARY_BYTES, (SKILL_ID, REFERENCE): LIBRARY_BYTES},
    )
    target = FakeTargetRepository(
        (
            target_file(INSTALLED_ENTRY, EDITED_BYTES),
            target_symlink(INSTALLED_REFERENCE),
        ),
        contents={INSTALLED_ENTRY: EDITED_BYTES},
    )
    manifest = manifest_of(
        manifest_artifact(
            SKILL_ID,
            (make_file(ENTRY, INSTALLED_BYTES), make_file(REFERENCE, INSTALLED_BYTES)),
        )
    )
    editor = FakeConflictEditor()

    compare(plan_of(library, target, manifest), library, target, editor=editor)

    shown = {version.path: version for version in editor.shown}
    assert shown[INSTALLED_REFERENCE].target is None
    assert shown[INSTALLED_REFERENCE].unreadable is not None
    assert shown[INSTALLED_REFERENCE].library == LIBRARY_BYTES
    assert shown[INSTALLED_ENTRY].unreadable is None
    assert shown[INSTALLED_ENTRY].target == EDITED_BYTES


def test_a_side_that_does_not_hold_the_path_is_shown_as_absent() -> None:
    """The third state's neighbours. A library that dropped the path has no version to show, and
    that is `None` rather than `b""` — an empty version would read as an empty file."""
    library, target, manifest = a_library_that_dropped_it()
    editor = FakeConflictEditor()

    compare(plan_of(library, target, manifest), library, target, editor=editor)

    assert editor.shown[0].library is None
    assert editor.shown[0].unreadable is None
    assert editor.shown[0].target == EDITED_BYTES


def test_a_skipped_artifact_has_nothing_to_compare() -> None:
    """**Ruling R99 on this side too.** The root was never scanned, so neither version exists;
    the editor is handed an empty session and the entry comes back in `left_alone`."""
    library = a_library(OTHER_NAME)
    target = FakeTargetRepository()
    root = SymlinkedRoot(
        type=ArtifactType.SKILL, name=SKILL_NAME, destination="../../outside/delivery-lead"
    )
    plan = plan_install(library, target, manifest=None, unscannable=(root,))
    editor = FakeConflictEditor()

    result = compare(plan, library, target, editor=editor, artifact_id=SKILL_ID)

    assert result.compared == ()
    assert [refused.path for refused in result.left_alone] == ["skills/delivery-lead"]
    assert editor.shown == ()


def test_comparing_an_artifact_this_plan_refuses_nothing_about_is_the_same_loud_failure() -> None:
    """The same posture as the resolution's, and deliberately the same error: a user who pointed
    `--resolve` at the wrong id gets one answer whichever of the three ways they spelled."""
    library = a_library(SKILL_NAME)
    target = target_holding((INSTALLED_ENTRY, LIBRARY_BYTES))
    manifest = a_manifest(SKILL_NAME, body=LIBRARY_BYTES)

    with pytest.raises(NothingToResolveError):
        compare(
            plan_of(library, target, manifest),
            library,
            target,
            editor=FakeConflictEditor(),
        )


def test_comparing_versions_takes_the_lock_and_releases_it() -> None:
    """R82, and not ceremony: while the user is looking at two versions of a path, no apply may
    move it underneath them."""
    library, target, manifest = a_conflict(SKILL_NAME)
    lock = FakeWriteLock()

    compare(
        plan_of(library, target, manifest),
        library,
        target,
        editor=FakeConflictEditor(),
        lock=lock,
    )

    assert lock.events == ["acquired", "released"]


def test_an_editor_that_will_not_start_releases_the_lock() -> None:
    """The failure propagates as a builtin — C-6 has no code for "the editor would not start" and
    charter §9 forbids inventing one at a raise site — and the lock is still released, which is
    the half that would bite: a lock leaked on the error path only ever bites after something has
    already gone wrong."""
    library, target, manifest = a_conflict(SKILL_NAME)
    lock = FakeWriteLock()

    with pytest.raises(OSError, match="refuses to start an editor"):
        compare(
            plan_of(library, target, manifest),
            library,
            target,
            editor=FakeConflictEditor(fail=True),
            lock=lock,
        )

    assert lock.events == ["acquired", "released"]


def test_an_unhashed_target_entry_is_what_the_plan_really_produces() -> None:
    """A precondition, asserted so the two R72 tests above are not resting on an assumption about
    what `target_symlink` becomes in a plan.

    `TargetFile.sha256` is `None` for a link and `target_sha_of` turns that into
    `UNHASHED_TARGET_SHA` — *present, unreadable* — which is what makes the verdict `LOCAL_EDIT`
    rather than `CREATE`.
    """
    entry = TargetFile(path=INSTALLED_ENTRY, sha256=None, size=12, is_symlink=True)
    library = a_library(SKILL_NAME)
    target = FakeTargetRepository((entry,))
    manifest = a_manifest(SKILL_NAME, body=LIBRARY_BYTES)

    plan = plan_of(library, target, manifest)
    refused = next(one for one in plan.entries if one.path == INSTALLED_ENTRY)

    assert refused.target_sha == UNHASHED_TARGET_SHA
    assert refused.verdict is Verdict.LOCAL_EDIT
