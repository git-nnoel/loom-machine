"""Contracts C-9 and C-10 — the install verdict, and the plan that carries it.

One path is judged on three digests: what the library holds, what the manifest says was last
installed on this target, and what is on the target's disk now. This module is the only place that
judgement is made. Everything above it — apply, prune, rollback, uninstall, the drift report,
initiative 03's API and initiative 04's view — reads a `Verdict` and never recomputes one. A second
implementation of this table would disagree with this one exactly where it matters: on a file about
to be overwritten or deleted.

**Presence is resolved before equality (R55).** A side may not hold the path at all, and `None` is
not "a digest that fails to match". Encoding absence as inequality was this plan's first draft, and
it turned a library artifact dropped while manifest and target still agreed — a prune — into an
update, which writes back a file the library no longer has. `decide_verdict` settles presence
first; `verdict_for_equalities` applies only once all three sides hold the path.

**Paths are `str`, never `pathlib.Path`** — R21, already frozen by C-10, C-11 and C-12. This layer
performs no I/O, and `tests/domain/test_purity.py` bars `pathlib` from it beyond what
`import-linter` can see. Written down here as confirmation of a settled rule, not as one reopened.

**Nothing here produces `SKIPPED`.** It is the ninth member so that T-20 can put V11's symlinked
artifact root into a plan without amending a frozen contract: such a root is present in the
library, unscannable, and so neither applied nor conflicted. The verdict exists; its emitter does
not yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class Verdict(StrEnum):
    """Contract C-9. What install intends to do about one path. Closed, nine members.

    A `StrEnum` rather than a bare string because initiatives 03 and 04 branch on the value: a
    rename then fails at every emitter instead of passing silently as a token nothing handles. The
    underscored spelling is canonical; the spec's hyphenated prose names the same values.
    """

    UNCHANGED = "unchanged"
    """Library, manifest and target agree. Nothing is written."""

    UPDATE = "update"
    """The target still holds exactly what was installed, and the library has moved on. Safe to
    overwrite: no edit of the user's can be lost, because there is none."""

    LOCAL_EDIT = "local_edit"
    """The library still holds what was installed, and the target was edited out of band. Never
    overwritten without `--resolve` (F-15), and it makes a plan incomplete."""

    CONFLICT = "conflict"
    """No side can be preferred on merit without losing someone's work. Always carries a `reason`,
    because the four ways to reach it call for four different resolutions."""

    CREATE = "create"
    """The library holds a path the target does not. Written."""

    PRUNE = "prune"
    """The manifest records a path the library no longer holds, and the target still holds exactly
    what was installed. Removable without destroying an edit."""

    FOREIGN = "foreign"
    """The target holds a path neither the library nor the manifest knows. Install never writes it
    and never removes it (F-10); only `clean --foreign` acts on one, and only when asked."""

    MANIFEST_REPAIR = "manifest_repair"
    """Library and target agree; only the manifest is stale. The files are already correct, so the
    repair is a manifest rewrite and not a file write.

    A verdict of its own rather than `UNCHANGED` plus an action (R52): a consumer must be able to
    *count* it, and a count is exactly what an action hidden behind another verdict does not have.
    """

    SKIPPED = "skipped"
    """An artifact the scanner could not read — V11's symlinked root. Present in the library,
    never scanned, so neither applied nor conflicted. Always carries a `reason`. Produced by T-20;
    nothing in this module emits it."""


BLOCKING_VERDICTS: frozenset[Verdict] = frozenset(
    {Verdict.LOCAL_EDIT, Verdict.CONFLICT, Verdict.SKIPPED}
)
"""The verdicts that make a plan incomplete — C-10's predicate, as a register.

`InstallPlan.is_complete` reads this set rather than restating its three members, so the rule and
the exit status it drives (`INCOMPLETE = 6`, R57) cannot come to disagree. Every member is a
verdict whose artifact install deliberately leaves alone: two await a human decision and one was
never readable.
"""

EXPLAINED_VERDICTS: frozenset[Verdict] = frozenset({Verdict.SKIPPED, Verdict.CONFLICT})
"""The verdicts C-10 requires a `reason` on, so a plan explains itself without a second lookup.

The implication runs one way only: these two must carry a reason, and any other verdict *may*.
Nothing is gained by forbidding an explanation on an `UPDATE`.
"""


VERDICT_BY_EQUALITY: Mapping[tuple[bool, bool, bool], Verdict] = MappingProxyType(
    {
        # (library == manifest, manifest == target, library == target)
        (True, True, True): Verdict.UNCHANGED,
        (False, True, False): Verdict.UPDATE,
        (True, False, False): Verdict.LOCAL_EDIT,
        (False, False, True): Verdict.MANIFEST_REPAIR,
        (False, False, False): Verdict.CONFLICT,
    }
)
"""The equality table of the all-three-present case, keyed on the three pairwise comparisons.

Five rows, not eight. The three absent keys — `(True, True, False)`, `(True, False, True)` and
`(False, True, True)` — each assert that two digests equal a third but not each other, which string
equality cannot produce. They are missing from the table rather than mapped to a fallback verdict
so that reaching one raises instead of quietly choosing a side.
"""


_CONFLICT_REASONS: Mapping[tuple[bool, bool, bool], str] = MappingProxyType(
    {
        # (the library holds it, the manifest records it, the target holds it)
        (False, True, True): (
            "the target's copy differs from what the manifest recorded, and the library no longer "
            "holds this path: pruning it would destroy an edit"
        ),
        (True, True, False): (
            "the path was removed from the target, and the library's copy has changed since the "
            "manifest recorded it: restoring it would not restore what was deleted"
        ),
        (True, False, True): (
            "the target already holds a different copy of this path and no manifest records "
            "installing it: it was not put there by this tool"
        ),
        (True, True, True): (
            "the library, the manifest and the target hold three different versions of this path"
        ),
    }
)
"""Why each conflict is a conflict, keyed on which sides hold the path.

Written here, beside the rule that decides the verdict, rather than at the call site that renders
it. The four conflicts have four different causes and four different resolutions, and a caller
reconstructing the cause from the entry would be deriving a second time what the rule already knew.
"""


def verdict_for_equalities(
    *,
    library_equals_manifest: bool,
    manifest_equals_target: bool,
    library_equals_target: bool,
) -> Verdict:
    """The verdict for a path all three sides hold, from the three pairwise comparisons.

    Public, and taking booleans rather than digests, for one reason: the three transitivity
    violations are unreachable through `decide_verdict` — equality of three real strings cannot
    produce them — so this is the only surface on which the raise can be given an input and shown
    to fire. A rule nobody has seen fail is a rule that does not run.

    Raises:
        ValueError: on a combination that violates transitivity. Deliberately bare, with no
            `ErrorCode`: charter §9's taxonomy is for faults a caller branches on and a CLI turns
            into an exit status, and this is an unreachable state — a bug here, never a user's.
    """
    key = (library_equals_manifest, manifest_equals_target, library_equals_target)
    verdict = VERDICT_BY_EQUALITY.get(key)
    if verdict is None:
        raise ValueError(
            "impossible digest combination "
            f"(library == manifest, manifest == target, library == target) = {key}: "
            "equality is transitive, so two digests cannot both equal a third and differ "
            "from each other"
        )
    return verdict


def decide_verdict(
    *,
    library_sha: str | None,
    manifest_sha: str | None,
    target_sha: str | None,
) -> Verdict | None:
    """Judge one path. `None` means no side holds it, which is not an entry at all.

    Each argument is that side's digest of this path, or `None` when that side does not hold it —
    presence first, equality second (R55).

    `None` rather than a raise for the empty case: the caller enumerates the union of three path
    sets, where a path absent from all three simply does not arise, and a caller that builds its
    input another way should skip it rather than crash. This mirrors `identity.parse_artifact_id`,
    which answers `None` for the same reason.
    """
    library = library_sha is not None
    manifest = manifest_sha is not None
    target = target_sha is not None

    if not (library or manifest or target):
        return None
    if not library and not manifest:
        return Verdict.FOREIGN
    if not manifest and not target:
        return Verdict.CREATE
    if not library:
        # The manifest and the target hold it; the library does not.
        return Verdict.PRUNE if manifest_sha == target_sha else Verdict.CONFLICT
    if not target:
        # The library and the manifest hold it; the target does not — the user deleted it.
        return Verdict.CREATE if library_sha == manifest_sha else Verdict.CONFLICT
    if not manifest:
        # The library and the target hold it; no manifest records installing it.
        return Verdict.MANIFEST_REPAIR if library_sha == target_sha else Verdict.CONFLICT
    return verdict_for_equalities(
        library_equals_manifest=library_sha == manifest_sha,
        manifest_equals_target=manifest_sha == target_sha,
        library_equals_target=library_sha == target_sha,
    )


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """Contract C-10. One path, its three digests and what install intends to do about it.

    Attributes:
        artifact_id: the `<type>/<name>` the path belongs to. Not validated: a `FOREIGN` path may
            sit outside every artifact root, in which case there is no id to give it and the empty
            string is the honest answer.
        path: relative to the target root. A `str`, never a `Path` (R21).
        verdict: what install intends. The branchable value; `reason` is prose.
        library_sha: the library's digest of this path, or `None` when the library does not hold
            it. `None` is absence, never "a digest that did not match".
        manifest_sha: the digest the manifest recorded for this path at the last install, or
            `None` when no install recorded it.
        target_sha: the digest on the target's disk now, or `None` when the target does not hold
            it.
        reason: why, for the verdicts that need explaining. Required on `CONFLICT` and `SKIPPED`
            and optional on the rest — the implication does not run both ways.

    All three digests are `None` together only for a `SKIPPED` artifact root that was never
    scanned and that neither the manifest nor the target holds; the rule in this module never
    returns a verdict for that input.
    """

    artifact_id: str
    path: str
    verdict: Verdict
    library_sha: str | None = None
    manifest_sha: str | None = None
    target_sha: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("PlanEntry.path must not be empty")
        if self.verdict in EXPLAINED_VERDICTS and not self.reason:
            raise ValueError(
                f"a {self.verdict.value} entry must carry a reason: contract C-10 makes a plan "
                "explain its conflicts and skips without a second lookup, and the user is being "
                "asked to decide something"
            )


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Contract C-10. Everything one install would do, decided before anything is written.

    `counts` and `is_complete` are derived rather than stored. C-10 lists all three as fields, and
    a consumer reads all three as attributes; storing the latter two would allow a plan whose
    counts disagree with its own entries, which is the drift this contract exists to prevent.

    Attributes:
        entries: one per path any side holds, in the caller's order. Order is the caller's
            business — this layer neither sorts nor deduplicates.
    """

    entries: tuple[PlanEntry, ...] = ()

    @property
    def counts(self) -> Mapping[Verdict, int]:
        """How many entries carry each verdict — **every** verdict, in declaration order.

        Dense, including the zeros: R52 wants a consumer able to count a verdict, and a consumer
        that has to guard every lookup with `.get(verdict, 0)` will forget one. A report that only
        wants the non-empty rows filters them out; a report reading a sparse map cannot invent the
        rows that are missing.
        """
        tally = dict.fromkeys(Verdict, 0)
        for entry in self.entries:
            tally[entry.verdict] += 1
        return MappingProxyType(tally)

    @property
    def is_complete(self) -> bool:
        """Whether every entry can be applied without a human deciding something first.

        False when any entry carries a verdict in `BLOCKING_VERDICTS`. A complete run exits 0; an
        incomplete one applies everything it safely can and exits `INCOMPLETE = 6` (R57), which is
        T-13's to define and T-22's to return.
        """
        return not any(entry.verdict in BLOCKING_VERDICTS for entry in self.entries)


def plan_entry_for(
    *,
    artifact_id: str,
    path: str,
    library_sha: str | None,
    manifest_sha: str | None,
    target_sha: str | None,
) -> PlanEntry | None:
    """Build the entry for one path, or `None` when no side holds it.

    The one constructor that fills `reason`, because the rule that decides a conflict is the only
    thing that knows which of the four conflicts it is. A caller building `PlanEntry` by hand for
    any other verdict is fine and expected; building a `CONFLICT` by hand means inventing a
    sentence this module already owns.
    """
    verdict = decide_verdict(
        library_sha=library_sha,
        manifest_sha=manifest_sha,
        target_sha=target_sha,
    )
    if verdict is None:
        return None
    reason = None
    if verdict is Verdict.CONFLICT:
        reason = _CONFLICT_REASONS[
            (library_sha is not None, manifest_sha is not None, target_sha is not None)
        ]
    return PlanEntry(
        artifact_id=artifact_id,
        path=path,
        verdict=verdict,
        library_sha=library_sha,
        manifest_sha=manifest_sha,
        target_sha=target_sha,
        reason=reason,
    )
