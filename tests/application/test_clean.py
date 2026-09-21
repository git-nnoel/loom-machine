"""`CleanForeign` — F-10's other half. The one command that removes what this tool never wrote.

Two claims, and the module is built around telling them apart:

* **the listing is complete before the first removal** — a target that records `exists` and
  `delete` in one interleaving log is what proves it, because a run that deleted each path as it
  found it produces the same report and the same final directory;
* **nothing the manifest knows is ever in the list** — which is a claim about the *set*, says
  nothing about ordering, and is therefore a control the first claim's mutation cannot reach
  (L51).

Fakes only, zero disk (charter §10). What this layer cannot see: that a real scan reports every
leaf of Claude Code's `synced/` bucket without filtering it (R44), that a real `delete` unlinks a
foreign symlink as itself rather than following it, or that the directories left behind are
really left behind. `tests/test_clean.py` proves all three against the committed fixture target.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from harness_library.application.write import CleanResult, clean_foreign, foreign_entries
from harness_library.domain.errors import (
    BackupFailedError,
    ErrorCode,
    LockHeldError,
    RecordStaleError,
    TargetUnwritableError,
)
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.manifest import Manifest
from tests.application.fakes import (
    FakeBackupStore,
    FakeManifestStore,
    FakeTargetRepository,
    FakeWriteLock,
    make_file,
    manifest_artifact,
    manifest_of,
    target_holding,
)

SKILL_ID = "skill/delivery-lead"
ENTRY = "SKILL.md"

INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"

SWAP = "skills/delivery-lead/SKILL.md.swp"
"""A foreign file **under an artifact root**. Carries that artifact's id (R60) and is foreign
anyway — the id says whose directory it is sitting in, never who owns the file."""

SETTINGS = "settings.json"
"""A foreign file under no artifact root at all. `artifact_id` is `None` (R60)."""

SYNCED_MARKER = "skills/synced/.bucket-7c1f9a2e"
SYNCED_SKILL = "skills/synced/7c1f9a2e_4b0d3f61/remote-helper/SKILL.md"
"""Two leaves of Claude Code's own sync bucket, spelled as the committed fixture spells them.

`skills/synced` is not an artifact root merely by being shaped like one, so both are `FOREIGN`
and both are in the listing — which is the whole of ruling R44 at this layer: there is no name in
`clean.py`, so there is nothing here that could exclude them.
"""

INSTALLED_BYTES = b"# what this tool installed\n"
SWAP_BYTES = b"\x00vim swap\n"
SETTINGS_BYTES = b'{"theme": "dark"}\n'
MARKER_BYTES = b"7c1f9a2e\n"
SYNCED_BYTES = b"---\nname: remote-helper\n---\n"

INSTALLED_AT = datetime(2026, 9, 21, 19, 40, tzinfo=UTC)
"""When every clean in this module ran. A parameter, never a clock."""

# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


def a_manifest() -> Manifest:
    """One artifact recorded. Its installed file is the path clean must never list."""
    return manifest_of(manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),)))


def a_target() -> FakeTargetRepository:
    """One installed file and four the library and the manifest both disown."""
    return target_holding(
        (INSTALLED_ENTRY, INSTALLED_BYTES),
        (SWAP, SWAP_BYTES),
        (SETTINGS, SETTINGS_BYTES),
        (SYNCED_MARKER, MARKER_BYTES),
        (SYNCED_SKILL, SYNCED_BYTES),
    )


def entry(path: str, verdict: Verdict, *, artifact_id: str | None, content: bytes) -> PlanEntry:
    """One plan entry whose digests really describe `content` on the sides that hold it."""
    digest = hash_bytes(content)
    foreign = verdict is Verdict.FOREIGN
    return PlanEntry(
        artifact_id=artifact_id,
        path=path,
        verdict=verdict,
        library_sha=None if foreign else digest,
        manifest_sha=None if foreign else digest,
        target_sha=digest,
    )


def a_plan() -> InstallPlan:
    """What `diff_against_target` produces for `a_target` — in path order, as it produces it."""
    return InstallPlan(
        entries=(
            entry(
                INSTALLED_ENTRY,
                Verdict.UNCHANGED,
                artifact_id=SKILL_ID,
                content=INSTALLED_BYTES,
            ),
            entry(SWAP, Verdict.FOREIGN, artifact_id=SKILL_ID, content=SWAP_BYTES),
            entry(SYNCED_MARKER, Verdict.FOREIGN, artifact_id=None, content=MARKER_BYTES),
            entry(SYNCED_SKILL, Verdict.FOREIGN, artifact_id=None, content=SYNCED_BYTES),
            entry(SETTINGS, Verdict.FOREIGN, artifact_id=None, content=SETTINGS_BYTES),
        )
    )


def clean(
    target: FakeTargetRepository,
    *,
    plan: InstallPlan | None = None,
    manifest: Manifest | None = None,
    backups: FakeBackupStore | None = None,
    manifests: FakeManifestStore | None = None,
    lock: FakeWriteLock | None = None,
    remove: bool = True,
) -> CleanResult:
    """`clean_foreign` with this module's fixed instant, **removing by default**.

    The default is inverted relative to the use case's own, deliberately: the parameter's safe
    default is asserted once, in its own test, and every other test here is about what happens
    when a user has already said yes. Plumbing only — it asserts nothing (L29), and a fresh
    `FakeWriteLock` unless one is given, so every clean here runs under a lock (R82).
    """
    return clean_foreign(
        plan if plan is not None else a_plan(),
        target,
        backups if backups is not None else FakeBackupStore(target),
        manifests if manifests is not None else FakeManifestStore(),
        lock=lock if lock is not None else FakeWriteLock(),
        manifest=manifest if manifest is not None else a_manifest(),
        installed_at=INSTALLED_AT,
        remove=remove,
    )


class _TargetRecordingTheInterleaving(FakeTargetRepository):
    """A target that writes `exists` and `delete` into **one** log, in call order.

    Two recorders would not do: the claim is not "it listed" and "it deleted" but that *every*
    listing came before *any* deletion, and a pair of lists with no shared clock cannot say that.
    A run that deleted each path as it found it produces exactly the same `listed`, the same
    `removed` and the same final directory as a correct one — this log is the only place the two
    differ.
    """

    def __init__(self, inner: FakeTargetRepository) -> None:
        super().__init__(inner.scan(), contents=inner.snapshot())
        self.log: list[tuple[str, str]] = []

    def exists(self, path: str) -> bool:
        self.log.append(("listed", path))
        return super().exists(path)

    def delete(self, path: str) -> None:
        self.log.append(("removed", path))
        super().delete(path)


class _TargetRefusingOneDelete(FakeTargetRepository):
    """A target whose `delete` raises `OSError` on one named path. Ruling R24's posture."""

    def __init__(self, inner: FakeTargetRepository, *, refusing: str) -> None:
        super().__init__(inner.scan(), contents=inner.snapshot())
        self._refusing = refusing

    def delete(self, path: str) -> None:
        if path == self._refusing:
            raise OSError(f"the injected failure refuses to remove {path!r}")
        super().delete(path)


# -------------------------------------------------------------------------------------------
# The safety model — list before acting, and never list what the manifest knows
# -------------------------------------------------------------------------------------------


def test_every_foreign_path_is_listed_before_any_is_removed() -> None:
    """**The must-fail assertion of this task's mutation (a)** (act before listing — delete each
    path as it is found).

    This is the whole safety model of the most dangerous command in the project. Asserted on an
    **interleaving log**, not on the result: a run that deleted as it went returns the identical
    `listed` tuple, so nothing about the report can tell the two apart.

    The positive control is in the same test: the log really does contain removals, so "every
    listing came first" cannot mean "nothing was ever removed".
    """
    target = _TargetRecordingTheInterleaving(a_target())

    result = clean(target, backups=FakeBackupStore(target))

    kinds = [kind for kind, _ in target.log]
    assert "removed" in kinds, (
        "the log records no removal at all, so this test cannot prove an ordering: it would pass "
        "for a clean that never deleted anything"
    )
    assert kinds == ["listed"] * kinds.count("listed") + ["removed"] * kinds.count("removed"), (
        "clean must name every path it is going to remove before it removes any of them. This "
        "command deletes files the tool never wrote and no record of ours describes, so a run "
        "that failed part-way through would leave the user with files gone and no statement of "
        f"which ones were going. The interleaving was: {target.log}"
    )
    assert set(result.listed) == set(result.removed)


def test_no_path_the_manifest_records_is_ever_listed() -> None:
    """**The must-stay-green control of mutation (a).**

    It asserts a membership and a non-membership of `listed` and **nothing about ordering**, so
    the mutation cannot reach it (L51). Without the pair, "acted too early" and "listed the wrong
    set" would produce the same single failure.

    The non-membership carries its positive control in the same test (charter §10): the foreign
    paths really are in the list, so "the installed file is absent from it" cannot mean the
    listing is empty. The installed file's **bytes** are asserted too, because a listing that
    excluded it and a clean that removed it anyway are different failures.
    """
    target = a_target()

    result = clean(target)

    assert INSTALLED_ENTRY not in result.listed
    assert INSTALLED_ENTRY not in result.removed
    assert target.snapshot()[INSTALLED_ENTRY] == INSTALLED_BYTES
    assert SETTINGS in result.listed
    assert SWAP in result.listed


def test_every_path_of_the_sync_bucket_is_in_the_listing() -> None:
    """**Ruling R44 at this layer**: `skills/synced/` is foreign like anything else, and there is
    no name in `clean.py` that could make it otherwise.

    Both leaves are listed — the `.bucket-<uuid>` marker at the top and the `SKILL.md` two
    directories down — which is what a named exclusion would have hidden, along with whatever
    else lands in that directory next. That the real scanner reports them at all is proven one
    layer down; this says clean does not then filter them out.
    """
    result = clean(a_target(), remove=False)

    assert SYNCED_MARKER in result.listed
    assert SYNCED_SKILL in result.listed


def test_the_default_lists_and_removes_nothing() -> None:
    """**`remove` defaults to `False`, and that is the structural half of "list before acting".**

    C-9 fixes it for the verdict: a foreign path is acted on *only when asked*. The default call
    is the listing T-22 shows before it asks, and it must leave no trace — no delete, no backup,
    no record. Asserted on all four, because a run that merely *reported* nothing removed while
    taking a backup would still have written into the state directory.
    """
    target = a_target()
    backups = FakeBackupStore(target)
    manifests = FakeManifestStore()

    result = clean_foreign(
        a_plan(),
        target,
        backups,
        manifests,
        lock=FakeWriteLock(),
        manifest=a_manifest(),
        installed_at=INSTALLED_AT,
    )

    assert result.listed == (SWAP, SYNCED_MARKER, SYNCED_SKILL, SETTINGS)
    assert result.removed == ()
    assert result.backup_id is None
    assert result.manifest is None
    assert target.deletes == []
    assert backups.created == []
    assert manifests.written == []
    assert target.snapshot()[SETTINGS] == SETTINGS_BYTES


def test_a_foreign_path_the_plan_names_and_the_target_lost_is_neither_listed_nor_removed() -> None:
    """The plan's snapshot had it and the disk does not.

    Not in the listing, because the listing is what the user authorises and nobody should be
    asked to authorise destroying something that is not there. Not raised on either: aborting a
    destructive run over a file somebody already deleted would leave the rest of it half done.
    """
    target = target_holding(
        (INSTALLED_ENTRY, INSTALLED_BYTES),
        (SETTINGS, SETTINGS_BYTES),
    )

    result = clean(target)

    assert result.listed == (SETTINGS,)
    assert result.absent == (SWAP, SYNCED_MARKER, SYNCED_SKILL)


def test_foreign_entries_selects_on_the_verdict_and_nothing_else() -> None:
    """The selector, as a fact about the function. No name, no prefix, no exception — the list is
    C-9's `FOREIGN` verdict and there is nowhere in it for R44 to be violated."""
    selected = foreign_entries(a_plan())

    assert tuple(one.path for one in selected) == (SWAP, SYNCED_MARKER, SYNCED_SKILL, SETTINGS)
    assert all(one.verdict is Verdict.FOREIGN for one in selected)


def test_clean_never_scans_the_target() -> None:
    """The listing the user authorised has to be the listing that is acted on.

    A rescan inside this function would answer a different question about a directory that may
    have changed, and the paths it turned up would be removed without ever having been shown.
    """
    target = a_target()

    clean(target)

    assert target.scan_calls == 0


# -------------------------------------------------------------------------------------------
# R88 — the backup, which is the only way back from this command
# -------------------------------------------------------------------------------------------


def test_the_backup_covers_exactly_the_listing_and_is_taken_before_the_first_delete() -> None:
    """R88, and the sharpest case of F-9 in the project: no library and no manifest describes a
    foreign path, so this copy is the only record of it that will ever exist.

    Asserted against `listed` rather than against a literal, because the two being the same set
    is the claim: a backup narrower than the listing would leave part of an authorised removal
    unrecoverable, and one wider would copy a file the user was never told about.
    """
    target = a_target()
    backups = FakeBackupStore(target)

    result = clean(target, backups=backups)

    assert backups.created == [result.listed]
    assert result.backup_id == backups.list()[0].backup_id
    assert backups.list()[0].kept == result.listed


def test_clean_refuses_to_remove_anything_when_the_backup_cannot_be_taken() -> None:
    """R88's refusal. Asserted on the target's content and not on the report — every foreign file
    is still exactly where it was, and the record was never written."""
    target = a_target()
    manifests = FakeManifestStore()

    with pytest.raises(BackupFailedError) as raised:
        clean(target, backups=FakeBackupStore(target, fail=True), manifests=manifests)

    assert raised.value.code is ErrorCode.BACKUP_FAILED
    assert target.snapshot()[SETTINGS] == SETTINGS_BYTES
    assert target.snapshot()[SYNCED_SKILL] == SYNCED_BYTES
    assert target.deletes == []
    assert manifests.written == []


def test_a_run_with_nothing_foreign_takes_no_backup_and_writes_no_record() -> None:
    """Nothing happened, so nothing is recorded — the same rule the listing-only run keeps.

    A record written here would name a `backup_id` of `None` and a fresh `installed_at`, claiming
    a destructive run against a target nothing was removed from.
    """
    target = target_holding((INSTALLED_ENTRY, INSTALLED_BYTES))
    backups = FakeBackupStore(target)
    manifests = FakeManifestStore()
    plan = InstallPlan(
        entries=(
            entry(
                INSTALLED_ENTRY,
                Verdict.UNCHANGED,
                artifact_id=SKILL_ID,
                content=INSTALLED_BYTES,
            ),
        )
    )

    result = clean(target, plan=plan, backups=backups, manifests=manifests)

    assert result.listed == ()
    assert result.manifest is None
    assert backups.created == []
    assert manifests.written == []


# -------------------------------------------------------------------------------------------
# The record, last — charter §13b
# -------------------------------------------------------------------------------------------


def test_the_record_keeps_every_artifact_and_names_the_backup() -> None:
    """Clean removes only paths the manifest does not record, so the artifacts it records are
    untouched. What changes is `backup_id`, which points at the only way back.

    `installed_at` moves too: the record is a statement about this target as of this run.
    """
    target = a_target()
    manifests = FakeManifestStore()

    result = clean(target, manifests=manifests)

    assert result.manifest is not None
    assert manifests.latest is result.manifest
    assert result.manifest.artifacts == a_manifest().artifacts
    assert result.manifest.backup_id == result.backup_id
    assert result.manifest.installed_at == INSTALLED_AT


def test_the_record_is_written_only_after_the_foreign_paths_are_gone() -> None:
    """Charter §13b, and L52: a run that does not fail cannot tell the two orders apart.

    A failure is injected into the *second* removal. Clean is the one run for which §13b's rule
    is vacuous — it disowns nothing, because nothing it removes was ever owned — and the ordering
    is kept anyway, so that "a run that makes files disappear records last" has no exception to
    remember in the module least suited to holding one.
    """
    target = _TargetRefusingOneDelete(a_target(), refusing=SYNCED_MARKER)
    manifests = FakeManifestStore()

    with pytest.raises(TargetUnwritableError) as raised:
        clean(target, manifests=manifests, backups=FakeBackupStore(target))

    assert SWAP not in target.snapshot()
    assert manifests.written == []
    assert raised.value.path == SYNCED_MARKER


def test_a_record_that_cannot_be_written_after_the_removals_is_record_stale() -> None:
    """**Ruling R90.** The files are gone and only the record is behind.

    Nothing is unreachable — clean disowns nothing — so what is lost is the `backup_id` pointing
    at the way back, and `BackupStore.list()` still holds it. `MANIFEST_UNWRITABLE` would promise
    that nothing happened, over a target that has just lost four files.
    """
    target = a_target()

    with pytest.raises(RecordStaleError) as raised:
        clean(target, manifests=FakeManifestStore(fail=True))

    assert raised.value.code is ErrorCode.RECORD_STALE
    assert raised.value.operation == "clean"
    assert SETTINGS not in target.snapshot()


# -------------------------------------------------------------------------------------------
# C-16 / R82 — the lock, at this layer
# -------------------------------------------------------------------------------------------


def test_clean_requires_a_lock_and_gives_it_no_default() -> None:
    """The signature itself. Nothing in the toolchain can see a write use case without a lock."""
    parameter = inspect.signature(clean_foreign).parameters["lock"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_the_lock_wraps_the_listing_as_well_as_the_removals() -> None:
    """A listing taken outside the lock would offer the user paths that are about to stop being
    foreign — another writer's install, mid-run, turns a `FOREIGN` path into a `CREATE`.

    Asserted by refusing the lock and finding the listing empty: not even the read half ran.
    """
    target = a_target()

    with pytest.raises(LockHeldError) as raised:
        clean(target, lock=FakeWriteLock(held_by_another=True))

    assert raised.value.code is ErrorCode.LOCK_HELD
    assert target.snapshot()[SETTINGS] == SETTINGS_BYTES
    assert target.deletes == []


def test_the_lock_is_released_when_a_removal_fails_part_way_through() -> None:
    """A lock leaked on the error path only bites after something has already gone wrong."""
    lock = FakeWriteLock()
    target = _TargetRefusingOneDelete(a_target(), refusing=SYNCED_MARKER)

    with pytest.raises(TargetUnwritableError):
        clean(target, lock=lock, backups=FakeBackupStore(target))

    assert lock.events == ["acquired", "released"]
    assert lock.held is False
