# Backend task plan — T-12, the verdict rule and the install plan entity

Initiative 02 · phase 1 · base commit `2b1b380` · owner `backend-developer-specialist`.
Realises contracts **C-9** (`Verdict`) and **C-10** (`PlanEntry`, `InstallPlan`). Pure domain, zero I/O.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/install_plan.py` | new. Holds `Verdict`, the equality table, the presence rule, `PlanEntry`, `InstallPlan`. One module, because the verdict vocabulary and the entity that carries it are one decision — splitting them would let a rename land on one side only |
| `tests/domain/test_install_plan.py` | new |
| `tests/domain/test_purity.py` | one line: `install_plan` joins `EXPECTED_MODULES` (L13, L18) |

Nothing else is touched. No `pathlib`, no `os`, no `io`, no `time`, no clock, no dependency change.

## 2. The rule, as two functions

Presence is resolved before equality (R55). The two halves are separate functions because only the
second one can be handed an impossible input:

* `decide_verdict(library_sha, manifest_sha, target_sha) -> Verdict | None` — the presence layer.
  `None` means "absent from all three sides", which is *not an entry at all* rather than an error:
  the caller (T-15) unions three path sets and skips what no side holds. It returns `None` rather
  than raising for the same reason `identity.parse_artifact_id` does — the caller is enumerating,
  not asserting.
* `verdict_for_equalities(library_equals_manifest, manifest_equals_target, library_equals_target)`
  — the all-three-present table, keyed on the three booleans. Five of the eight boolean triples are
  in `VERDICT_BY_EQUALITY`; the other three violate transitivity and raise a bare `ValueError`
  (no `ErrorCode`: they are unreachable states, not user-facing errors).

The three violations are **unreachable through `decide_verdict`**, because equality of three real
strings is transitive. That is precisely why the table function is public: a rule that can only be
proven by a test it cannot be given an input for is a rule nobody has seen fail.

`decide_verdict` calls `verdict_for_equalities`. One decision, one object.

## 3. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| Who fills `PlanEntry.reason` on `CONFLICT` | `plan_entry_for(...)` does, from the presence pattern that produced it. The four conflicts have four different causes; if T-15 wrote the sentences it would be re-deriving, at a distance, what the rule already knew |
| `counts` and `is_complete` as stored fields | realised as **properties** over `entries`. A stored count that can disagree with the entries it counts is the drift C-10 exists to prevent; every consumer still reads `plan.counts` / `plan.is_complete` |
| Is `counts` dense or sparse | **dense**: all nine verdicts, in declaration order, zeros included. `counts[Verdict.SKIPPED]` is `0`, never a `KeyError` — R52 wants a consumer able to *count* a verdict, and a renderer can filter zeros |
| `artifact_id` on a `FOREIGN` path | **not validated**. A foreign file outside every artifact root belongs to no artifact, so `""` must stay constructible. Flagged to the lead — T-14/T-15 decide what they put there |
| Is `reason` required on `SKIPPED`/`CONFLICT` | yes, enforced in `__post_init__`. The converse does **not** hold: another verdict may carry a reason |

## 4. Tests

Presence: six cases, nine rows (the three conditional cases carry both branches), asserted as
verdict values. Equality: the five reachable triples through `decide_verdict` with real shas; the
three transitivity violations through `verdict_for_equalities`, each with `pytest.raises`, plus a
positive control in the same test proving the function still reaches its table. A 4x4x4 sweep over
`{None, a, b, c}` asserts the produced set is exactly the eight producible verdicts, that `SKIPPED`
is never among them, and that no input raises. `is_complete` is false for each of `LOCAL_EDIT`,
`CONFLICT` and `SKIPPED`, each row carrying the same plan without the blocking entry as its control.

The `InstallPlan` tests build their entries by hand rather than through the rule, so the mutation
below reddens the rule's table and nothing else.

## 5. Mutation check (L35 — read this if the session was interrupted)

Mutation: in `VERDICT_BY_EQUALITY`, the row `(False, False, True)` — library differs from manifest,
manifest differs from target, library equals target — maps to `Verdict.UNCHANGED` instead of
`Verdict.MANIFEST_REPAIR`. Must fail: the manifest-stale row of the equality table, by verdict
value. Must stay green: every other row.

While the mutation was applied, `src/harness_library/domain/install_plan.py` was deliberately
wrong; the backup was taken at
`…/scratchpad/install_plan.py.orig` and the file restored from that copy rather than from memory of
the edit. A red gate here with an otherwise complete diff would be a mutation in flight, not
unfinished work.

**Result — the mutation is no longer applied; the module matches its backup by md5.** Under it,
`uv run pytest tests/domain -q` gave `1 failed, 197 passed`, the failure being
`test_the_equality_table_when_every_side_holds_the_path[only-the-manifest-is-stale]` with
`assert <Verdict.UNCHANGED: 'unchanged'> is <Verdict.MANIFEST_REPAIR: 'manifest_repair'>`. Every
other row of the table, both presence rows that reach `MANIFEST_REPAIR` and every `InstallPlan`
test stayed green. Restored: `198 passed`.

One structural note for the next mutation check here: the equality table is reachable through two
entry points, `decide_verdict` and `verdict_for_equalities`. Its five verdict values are asserted
**only** through `decide_verdict`, and `verdict_for_equalities` is asserted only on the three
raises plus one positive control. Asserting the same five rows at both entry points would have
reddened two tests under this one mutation and destroyed the independence control.

## 6. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time. Baseline 437 passed.
