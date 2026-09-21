"""The three-source join and every verdict reachable from it — T-15, features F-8 and F-10.

Fakes only, zero disk (charter §10). What this layer decides is *which target-relative path each
source lines up on* and *which verdict comes back for it*; what it cannot see is whether a real
walk records a symlink or a real write lands at `0644`, both of which
`tests/infrastructure/test_target.py` proves against real files.

Every verdict is asserted **as a verdict value**, never as a count or a truthy report, because a
count cannot tell `UPDATE` from `CONFLICT` and those are the two answers a user must not confuse.
"""

from __future__ import annotations

import pytest

from harness_library.application.read.drift import (
    UNHASHED_TARGET_SHA,
    diff_against_target,
    target_sha_of,
)
from harness_library.application.write.install import plan_install
from harness_library.domain.artifact import Artifact
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.identity import ArtifactType, make_artifact_id
from harness_library.domain.install_plan import InstallPlan, PlanEntry, Verdict
from harness_library.domain.manifest import Manifest, ManifestArtifact
from harness_library.domain.target import TargetFile
from tests.application.fakes import (
    FakeArtifactRepository,
    FakeTargetRepository,
    make_artifact,
    make_file,
    manifest_artifact,
    manifest_of,
    target_file,
    target_symlink,
)

SKILL_NAME = "delivery-lead"
SKILL_ID = "skill/delivery-lead"
ENTRY = "SKILL.md"
INSTALLED_ENTRY = "skills/delivery-lead/SKILL.md"
"""Where the library's `SKILL.md` lands. A literal on purpose: it is the join's answer, and a test
that recomputed it with the code under test would agree with any join at all."""

AGENT_NAME = "scribe"
AGENT_ID = "agent/scribe"
AGENT_ENTRY = "scribe.md"
INSTALLED_AGENT = "agents/scribe.md"

LIBRARY_BYTES = b"# the library has moved on\n"
INSTALLED_BYTES = b"# what this tool installed\n"
EDITED_BYTES = b"# what the user wrote afterwards\n"


# -------------------------------------------------------------------------------------------
# Builders. They assemble sources and never decide anything (L29).
# -------------------------------------------------------------------------------------------


def _plan_of(
    artifacts: list[Artifact],
    records: list[ManifestArtifact] | None,
    target_entries: tuple[TargetFile, ...],
) -> InstallPlan:
    """A plan over three explicit sources. `records=None` means this target has no manifest."""
    manifest: Manifest | None = None if records is None else manifest_of(*records)
    return plan_install(
        FakeArtifactRepository(artifacts),
        FakeTargetRepository(target_entries),
        manifest=manifest,
    )


def _one_path_plan(
    *,
    library: bytes | None,
    manifest: bytes | None,
    target: bytes | None,
) -> InstallPlan:
    """One skill holding one file, seen from whichever of the three sides hold it.

    `None` means that side does not hold the path at all — presence before equality (R55).
    """
    artifacts = (
        [] if library is None else [make_artifact(SKILL_NAME, files=(make_file(ENTRY, library),))]
    )
    records = (
        None if manifest is None else [manifest_artifact(SKILL_ID, (make_file(ENTRY, manifest),))]
    )
    entries = () if target is None else (target_file(INSTALLED_ENTRY, target),)
    return _plan_of(artifacts, records, entries)


def _entry(plan: InstallPlan, path: str) -> PlanEntry:
    """The one entry for `path`, or a failure naming what the plan did hold."""
    found = [entry for entry in plan.entries if entry.path == path]
    assert len(found) == 1, (
        f"expected exactly one entry for {path!r}; the plan holds "
        f"{[entry.path for entry in plan.entries]}"
    )
    return found[0]


# -------------------------------------------------------------------------------------------
# The join, as this module consumes it
# -------------------------------------------------------------------------------------------
#
# `target_path_of` itself moved to `domain/registry.py` with ruling R73 and its three tests moved
# with it, to `tests/domain/test_registry.py`. What stays here is what *this* module owes: that
# both the library and the manifest reach a target path through the same call, which is asserted
# by every verdict test below and by the `FILE`-kind row in particular.


def test_the_library_and_the_manifest_reach_one_key_through_the_registrys_join() -> None:
    """The one thing this layer adds to the join: **both** sources go through it.

    A manifest that reached a different key from the library's would make every installed file
    read `CREATE` plus `FOREIGN`, and the next apply would rewrite a target it did not need to
    touch while reporting the user's own copy as foreign.
    """
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, INSTALLED_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (target_file(INSTALLED_ENTRY, INSTALLED_BYTES),),
    )

    assert [plan_entry.path for plan_entry in plan.entries] == [INSTALLED_ENTRY]
    assert _entry(plan, INSTALLED_ENTRY).verdict is Verdict.UNCHANGED


def test_the_manifest_joins_through_the_same_root_path_as_the_library() -> None:
    """The manifest records artifact-root-relative paths and no root (C-11). If it reached a
    different key from the library's, every installed file would read `CREATE` plus `FOREIGN`."""
    plan = _one_path_plan(library=INSTALLED_BYTES, manifest=INSTALLED_BYTES, target=None)
    entry = _entry(plan, INSTALLED_ENTRY)

    assert entry.library_sha == entry.manifest_sha == hash_bytes(INSTALLED_BYTES)
    assert len(plan.entries) == 1


def test_an_agent_and_its_installed_copy_line_up_on_one_key() -> None:
    """End to end for the `FILE` kind, which the `DIRECTORY` formula would have got wrong."""
    agent = make_artifact(
        AGENT_NAME,
        artifact_type=ArtifactType.AGENT,
        files=(make_file(AGENT_ENTRY, INSTALLED_BYTES),),
    )
    plan = _plan_of(
        [agent],
        [manifest_artifact(AGENT_ID, (make_file(AGENT_ENTRY, INSTALLED_BYTES),))],
        (target_file(INSTALLED_AGENT, INSTALLED_BYTES),),
    )

    assert _entry(plan, INSTALLED_AGENT).verdict is Verdict.UNCHANGED


def test_a_manifest_artifact_whose_id_is_not_an_identity_is_refused() -> None:
    """Not skipped. A record whose files cannot be located leaves them held by neither the
    library nor the manifest — `FOREIGN`, unprunable and ununinstallable, orphaned by the record
    that exists to make them removable.

    **The refusal moved one layer down with ruling R74**, which put the guard on
    `ManifestArtifact.__post_init__`: it now fires while the record is being built, before a plan
    can be composed at all, and `manifest_store` renders it as a located `ManifestError` carrying
    `MANIFEST_UNREADABLE`. The subject and the sentence are unchanged, and `_manifest_files` keeps
    its own raise — unreachable through a constructed `Manifest`, which is the point.
    """
    with pytest.raises(ValueError, match="not a <type>/<name> identity"):
        _plan_of([], [manifest_artifact("nonsense", ())], ())


# -------------------------------------------------------------------------------------------
# The mutation subjects, each named and standing alone
# -------------------------------------------------------------------------------------------


def test_a_library_file_and_its_identical_installed_copy_are_unchanged() -> None:
    """**The must-fail assertion of the join mutation.** Drop the `TypeSpec.root_path` join and
    this file and its installed copy stop being one path: the library's `SKILL.md` becomes a
    `CREATE` nobody asked for, and the target's real copy reads `FOREIGN`."""
    plan = _one_path_plan(library=INSTALLED_BYTES, manifest=INSTALLED_BYTES, target=INSTALLED_BYTES)
    entry = _entry(plan, INSTALLED_ENTRY)

    assert entry.verdict is Verdict.UNCHANGED
    assert entry.artifact_id == SKILL_ID


def test_the_foreign_synced_tree_is_foreign_whole() -> None:
    """**The must-stay-green control of the join mutation**, and ruling R44's rule as a test.

    Claude Code's `synced/` bucket gets no named exclusion anywhere. Every path of it is foreign
    like anything else the library and the manifest both disown, and none of it belongs to an
    artifact: `skills/synced` is not an artifact root merely by being shaped like one.

    It is also the control that stops the join mutation passing by making *everything* foreign —
    these paths are foreign before the mutation and after it, so a run in which they fail proves
    something other than the mutation.
    """
    synced = (
        "skills/synced/.bucket-7c1f9a2e",
        "skills/synced/7c1f9a2e_4b0d3f61/remote-helper/SKILL.md",
    )
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, INSTALLED_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (
            target_file(INSTALLED_ENTRY, INSTALLED_BYTES),
            *(target_file(path, b"not ours\n") for path in synced),
        ),
    )

    for path in synced:
        entry = _entry(plan, path)
        assert entry.verdict is Verdict.FOREIGN
        assert entry.artifact_id is None


# -------------------------------------------------------------------------------------------
# Every verdict, from three real sources
# -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("library", "manifest", "target", "expected"),
    [
        (INSTALLED_BYTES, INSTALLED_BYTES, INSTALLED_BYTES, Verdict.UNCHANGED),
        (LIBRARY_BYTES, INSTALLED_BYTES, INSTALLED_BYTES, Verdict.UPDATE),
        (INSTALLED_BYTES, INSTALLED_BYTES, EDITED_BYTES, Verdict.LOCAL_EDIT),
        (LIBRARY_BYTES, INSTALLED_BYTES, EDITED_BYTES, Verdict.CONFLICT),
        (LIBRARY_BYTES, None, None, Verdict.CREATE),
        (None, INSTALLED_BYTES, INSTALLED_BYTES, Verdict.PRUNE),
        (None, None, EDITED_BYTES, Verdict.FOREIGN),
        (LIBRARY_BYTES, None, LIBRARY_BYTES, Verdict.MANIFEST_REPAIR),
    ],
    ids=[
        "unchanged",
        "update",
        "local_edit",
        "conflict",
        "create",
        "prune",
        "foreign",
        "manifest_repair",
    ],
)
def test_each_verdict_is_produced_from_three_real_sources(
    library: bytes | None,
    manifest: bytes | None,
    target: bytes | None,
    expected: Verdict,
) -> None:
    """All eight producible verdicts, each from a fixture built for it, each asserted as a value.

    One row per presence-and-equality combination the composition can reach. The digests are real
    hashes of real bytes, so no row can pass by two sentinels happening to match.
    """
    plan = _one_path_plan(library=library, manifest=manifest, target=target)

    assert _entry(plan, INSTALLED_ENTRY).verdict is expected


def test_a_conflict_explains_itself_without_a_second_lookup() -> None:
    """R61: `plan_entry_for` is the only constructor, because only the rule knows which of the
    four conflict shapes fired. A plan built by hand would have to invent the sentence."""
    plan = _one_path_plan(library=LIBRARY_BYTES, manifest=INSTALLED_BYTES, target=EDITED_BYTES)
    entry = _entry(plan, INSTALLED_ENTRY)

    assert entry.verdict is Verdict.CONFLICT
    assert entry.reason is not None
    assert "three different versions" in entry.reason


def _every_verdict_plan() -> InstallPlan:
    """One plan carrying all eight producible verdicts at once."""
    library_files = (
        make_file("unchanged.md", INSTALLED_BYTES),
        make_file("update.md", LIBRARY_BYTES),
        make_file("local-edit.md", INSTALLED_BYTES),
        make_file("conflict.md", LIBRARY_BYTES),
        make_file("create.md", LIBRARY_BYTES),
        make_file("repair.md", LIBRARY_BYTES),
    )
    manifest_files = (
        make_file("unchanged.md", INSTALLED_BYTES),
        make_file("update.md", INSTALLED_BYTES),
        make_file("local-edit.md", INSTALLED_BYTES),
        make_file("conflict.md", INSTALLED_BYTES),
        make_file("prune.md", INSTALLED_BYTES),
    )
    root = "skills/delivery-lead"
    target_entries = (
        target_file(f"{root}/unchanged.md", INSTALLED_BYTES),
        target_file(f"{root}/update.md", INSTALLED_BYTES),
        target_file(f"{root}/local-edit.md", EDITED_BYTES),
        target_file(f"{root}/conflict.md", EDITED_BYTES),
        target_file(f"{root}/prune.md", INSTALLED_BYTES),
        target_file(f"{root}/repair.md", LIBRARY_BYTES),
        target_file("settings.json", b"{}\n"),
    )
    return _plan_of(
        [make_artifact(SKILL_NAME, files=library_files)],
        [manifest_artifact(SKILL_ID, manifest_files)],
        target_entries,
    )


PRODUCIBLE_VERDICTS = frozenset(Verdict) - {Verdict.SKIPPED}
"""The eight this composition can reach. `SKIPPED` is T-20's and nothing here may emit it."""


def test_no_verdict_outside_the_eight_appears_in_a_plan() -> None:
    """The sweep feature F-8 asks for, **with its positive control in the same test**.

    Absence: `SKIPPED` is never produced — it is the ninth member, reserved for V11's symlinked
    artifact root, which T-20 owns and which nothing in this composition can even see. Control:
    each of the other eight *is* produced by this same plan, so the sweep had something to find.
    Without that half, a composition that produced nothing at all would pass.
    """
    counts = _every_verdict_plan().counts

    assert counts[Verdict.SKIPPED] == 0
    assert sorted(verdict for verdict in Verdict if counts[verdict] > 0) == sorted(
        PRODUCIBLE_VERDICTS
    )


def test_a_plan_that_holds_a_local_edit_is_not_complete() -> None:
    """R57: an incomplete plan is what makes the run exit `INCOMPLETE = 6` rather than 0."""
    assert _every_verdict_plan().is_complete is False
    assert _one_path_plan(
        library=INSTALLED_BYTES, manifest=INSTALLED_BYTES, target=INSTALLED_BYTES
    ).is_complete


# -------------------------------------------------------------------------------------------
# A symlink planted over an installed path
# -------------------------------------------------------------------------------------------


def test_a_symlink_planted_over_an_installed_path_is_a_local_edit() -> None:
    """R6 never hashes a link, so its content can never compare equal to the library's. The
    answer is the ordinary table's, reached through a rule somebody wrote rather than through
    whatever the scanner happens to put in `sha256`."""
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, INSTALLED_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (target_symlink(INSTALLED_ENTRY),),
    )
    entry = _entry(plan, INSTALLED_ENTRY)

    assert entry.verdict is not Verdict.UNCHANGED
    assert entry.verdict is Verdict.LOCAL_EDIT


def test_a_symlink_planted_over_a_path_the_library_has_moved_on_from_is_a_conflict() -> None:
    """The other side of the same fact: no side can be preferred, and the link is not content."""
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (target_symlink(INSTALLED_ENTRY),),
    )
    entry = _entry(plan, INSTALLED_ENTRY)

    assert entry.verdict is not Verdict.UNCHANGED
    assert entry.verdict is Verdict.CONFLICT


def test_a_symlink_is_a_path_the_target_holds_and_not_one_it_lacks() -> None:
    """**The expensive mistake, asserted directly.** A link carries no digest; passing that
    absence through would say the target does not hold the path, which is judged `CREATE` and
    written straight through the link on the next apply.

    The control is in the same test: a library file the target really lacks *is* `CREATE`, so
    "not `CREATE`" is an assertion that can fail.
    """
    plan = _plan_of(
        [
            make_artifact(
                SKILL_NAME,
                files=(make_file(ENTRY, INSTALLED_BYTES), make_file("new.md", LIBRARY_BYTES)),
            )
        ],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (target_symlink(INSTALLED_ENTRY),),
    )
    linked = _entry(plan, INSTALLED_ENTRY)

    assert linked.target_sha is not None
    assert linked.verdict is not Verdict.CREATE
    assert _entry(plan, "skills/delivery-lead/new.md").verdict is Verdict.CREATE


def test_the_installed_bytes_at_that_same_path_are_unchanged() -> None:
    """The control for the three tests above: swap the link for the file it should have been and
    the same sources produce `UNCHANGED`. Without it, a composition that answered `LOCAL_EDIT` to
    everything would look correct."""
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, INSTALLED_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (target_file(INSTALLED_ENTRY, INSTALLED_BYTES),),
    )

    assert _entry(plan, INSTALLED_ENTRY).verdict is Verdict.UNCHANGED


@pytest.mark.parametrize("absent", [None, ""], ids=["none", "empty-string"])
def test_a_target_entry_with_no_digest_is_reported_present_whichever_sentinel_is_used(
    absent: str | None,
) -> None:
    """The rule under **both** spellings of "no digest". T-14 wrote `""`, ruling R68 writes
    `None`, and `target_sha_of` tests for truth rather than for `is not None` so that changing
    the sentinel again cannot silently turn a present path into an absent one.

    The entry is built with `is_symlink=False` because `TargetFile` now refuses a link carrying
    `""` — the invariant is about what must never be hashed, and this is about what the rule
    reading it does with either value.
    """
    entry = TargetFile(path=INSTALLED_ENTRY, sha256=absent, size=0, is_symlink=False)

    assert target_sha_of(entry) == UNHASHED_TARGET_SHA


def test_a_target_entry_with_a_digest_is_judged_on_that_digest() -> None:
    """The positive control for the two rows above."""
    assert target_sha_of(target_file(INSTALLED_ENTRY, INSTALLED_BYTES)) == hash_bytes(
        INSTALLED_BYTES
    )


def test_the_unhashed_sentinel_cannot_collide_with_a_real_digest() -> None:
    """`hash_bytes` returns 64 lowercase hex characters; this is neither, so no content can ever
    hash to it and be reported unchanged by accident."""
    assert hash_bytes(b"") != UNHASHED_TARGET_SHA
    assert not all(character in "0123456789abcdef" for character in UNHASHED_TARGET_SHA)


# -------------------------------------------------------------------------------------------
# Foreign paths and who they belong to (ruling R60)
# -------------------------------------------------------------------------------------------


def test_a_foreign_path_under_no_artifact_root_belongs_to_no_artifact() -> None:
    """R60. `settings.json` sits under no artifact root and has no `<type>/<name>` to give it."""
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, INSTALLED_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (target_file(INSTALLED_ENTRY, INSTALLED_BYTES), target_file("settings.json", b"{}\n")),
    )
    entry = _entry(plan, "settings.json")

    assert entry.verdict is Verdict.FOREIGN
    assert entry.artifact_id is None


def test_a_foreign_file_inside_an_installed_artifact_root_names_that_artifact() -> None:
    """The other half of R60, and the reason it is `None` *only* for a path under no root: an
    editor swap file beside an installed `SKILL.md` is still foreign — install never touches it —
    but a report that could not say whose directory it is in would be less useful than the `ls`
    it replaces."""
    plan = _plan_of(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, INSTALLED_BYTES),))],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (
            target_file(INSTALLED_ENTRY, INSTALLED_BYTES),
            target_file(f"{INSTALLED_ENTRY}.swp", b"\x00swap\n"),
        ),
    )
    entry = _entry(plan, f"{INSTALLED_ENTRY}.swp")

    assert entry.verdict is Verdict.FOREIGN
    assert entry.artifact_id == SKILL_ID


def test_a_foreign_file_under_the_root_of_an_artifact_only_the_manifest_holds_names_it() -> None:
    """An artifact that left the library still has a root inside the target holding the files a
    prune is about to remove. A foreign file beside them belongs to it just as much."""
    plan = _plan_of(
        [],
        [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))],
        (
            target_file(INSTALLED_ENTRY, INSTALLED_BYTES),
            target_file(f"{INSTALLED_ENTRY}.swp", b"\x00swap\n"),
        ),
    )

    assert _entry(plan, INSTALLED_ENTRY).verdict is Verdict.PRUNE
    assert _entry(plan, f"{INSTALLED_ENTRY}.swp").artifact_id == SKILL_ID


def test_no_entry_carries_the_empty_artifact_id() -> None:
    """R69, reached through the composition rather than through the constructor: every entry of a
    plan built from three real sources carries a real id or `None`.

    Control in the same test: the plan really does carry both kinds, so the sweep had something
    to look at.
    """
    plan = _every_verdict_plan()
    ids = {entry.artifact_id for entry in plan.entries}

    assert "" not in ids
    assert ids == {SKILL_ID, None}


# -------------------------------------------------------------------------------------------
# Shape of the plan, and the read use case's read-only promise
# -------------------------------------------------------------------------------------------


def test_entries_come_back_in_path_order() -> None:
    """`InstallPlan` neither sorts nor deduplicates, so the order is decided here. Total, so two
    runs over one pair of snapshots can be compared."""
    paths = [entry.path for entry in _every_verdict_plan().entries]

    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))


def test_a_first_install_with_no_manifest_creates_every_library_file() -> None:
    """Absent is not empty. A target nothing was ever installed into has no manifest at all, and
    every library file is a `CREATE` rather than a repair."""
    plan = _plan_of(
        [
            make_artifact(
                SKILL_NAME,
                files=(make_file(ENTRY, LIBRARY_BYTES), make_file("references/a.md", b"a\n")),
            )
        ],
        None,
        (),
    )

    assert [entry.verdict for entry in plan.entries] == [Verdict.CREATE, Verdict.CREATE]


def test_an_artifact_the_library_holds_with_no_files_contributes_no_entries() -> None:
    """A skill directory whose `SKILL.md` is missing is still an artifact, carrying its V1
    finding. It declares no files, so it proposes nothing — and it is not an error here: no
    verdict in C-9 spells "invalid", and the one refusal that is spelled is T-20's `SKIPPED`."""
    plan = _plan_of([make_artifact(SKILL_NAME, files=())], None, ())

    assert plan.entries == ()


def test_the_drift_report_writes_nothing_to_the_target() -> None:
    """Feature F-10's promise at this layer, **with its positive control in the same test**.

    Absence: building a report calls `scan()` and neither `write` nor `delete`. Control: the fake
    does record a write when one is made, so an empty `writes` list means nothing was written and
    not that nothing is ever recorded.
    """
    target = FakeTargetRepository((target_file(INSTALLED_ENTRY, EDITED_BYTES),))
    library = FakeArtifactRepository(
        [make_artifact(SKILL_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))]
    )

    plan = diff_against_target(library, target, manifest=None)

    assert plan.entries != ()
    assert target.writes == []
    assert target.deletes == []
    assert target.scan_calls == 1

    target.write("proof.md", b"the recorder works\n")
    assert target.writes == [("proof.md", b"the recorder works\n")]


def test_the_drift_report_and_the_install_plan_agree_entry_for_entry() -> None:
    """They answer the same question today and share one implementation. When they stop agreeing
    it must be because a write-only narrowing was added in `application/write/`, and this test is
    what will say so."""
    artifacts = [make_artifact(SKILL_NAME, files=(make_file(ENTRY, LIBRARY_BYTES),))]
    records = [manifest_artifact(SKILL_ID, (make_file(ENTRY, INSTALLED_BYTES),))]
    entries = (target_file(INSTALLED_ENTRY, INSTALLED_BYTES),)

    reported = diff_against_target(
        FakeArtifactRepository(artifacts),
        FakeTargetRepository(entries),
        manifest=manifest_of(*records),
    )
    planned = _plan_of(artifacts, records, entries)

    assert reported.entries == planned.entries
    assert reported.entries[0].verdict is Verdict.UPDATE


def test_the_identity_the_library_reports_is_the_one_the_plan_carries() -> None:
    """The id is derived from the tree (charter §7), never stored, and the plan must not invent a
    second spelling of it."""
    plan = _one_path_plan(library=INSTALLED_BYTES, manifest=INSTALLED_BYTES, target=INSTALLED_BYTES)

    assert _entry(plan, INSTALLED_ENTRY).artifact_id == make_artifact_id(
        ArtifactType.SKILL, SKILL_NAME
    )
