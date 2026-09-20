# Review profile — Harness Library

What is true *here*. The `phase-reviewer` agent carries the method; this file carries the facts.
**Orchestrator-owned, one per repository.** Seeded 2026-09-20 from the tree as it stands; every path
and id below resolved on that date.

**Update this file in the same response** that adds a (PLAN)-tagged lesson, creates or retires an
invariant, or moves a path it names. A profile that lags is worse than none — the reviewer reports
against it with confidence.

## 1. Layout

| What | Where | Verify |
|---|---|---|
| Spec suite | `docs/specs/2026-08-28-harness-library-design.md` — **one file, Tier 1** | `ls docs/specs/` |
| Instruction tree | `docs/instructions/` | `find docs/instructions -type f` |
| Backend charter | `docs/instructions/backend-charter.md` | — |
| Dispatch lessons | `docs/instructions/specialist-dispatch-lessons.md` | — |
| Phase map | `docs/instructions/README.md` | — |
| Initiatives | `docs/instructions/phases/phase-N/nn-<topic>/` | `find docs/instructions/phases -maxdepth 2 -type d` |
| Backend code | `src/harness_library/{domain,application,infrastructure,cli,mcp}/` | `ls src/harness_library/` |
| Tests | `tests/{domain,application,infrastructure,cli,mcp}/`, `tests/fixtures/` | `ls tests/` |
| Fixture library | `tests/fixtures/library/` — the regression suite; **never deleted** | charter §10 |

**Spec files this project does NOT have**, and must not be reported as missing: `domain-model.md`,
`api-specification.md`, `architecture-handbook.md`, `verification.md`, `ui-specification.md`,
`copy-deck.md`, `technical-specification.md`, `authority-model.md`, `integration-map.md`, `glossary.md`,
`runbooks/`. This is a Tier 1 suite by design — one design document. There is **no frontend charter and
no frontend territory**; initiative 04 opens one.

## 2. Precedence, and spec-versus-code disagreement

1. `docs/specs/2026-08-28-harness-library-design.md` — behaviour, the locked decisions D1–D8, the data model.
2. *(no brand reference; no mockups)*
3. `docs/instructions/backend-charter.md` — how this team builds. §8's rule register is the authority on validation rules.
4. The initiative plan and record — derived.

**This is a contract-first project.** C-1…C-8 are frozen in the initiative plan §6 and initiatives
02–04 build against them. **A locked-but-unbuilt contract is not drift.** A contract named in a ruling
but absent from the code is also not drift until a task has been dispatched to transcribe it — see
R26, where exactly that gap was found and the transcription was ruled *not* an amendment.

The spec carries an **amendment log at §14**. A spec claim contradicted by code is checked against that
log first: the spec is amended at the source, never patched from the instruction tree.

## 3. Document types under review

| Type | Path | Gate |
|---|---|---|
| Implementation plan | `<initiative>/implementation-plan.md` | review gate |
| Implementation record | `<initiative>/implementation-record.md` | review gate, at close |
| Design / correction design | `<initiative>/<date>-design.md` | design gate |
| Acceptance report | `<initiative>/<date>-acceptance.md` | review gate |
| Specialist task plan | `<initiative>/backend-task-plan.md` | **specialist-owned — read, never flag for format** |

## 4. Id series and their high-water marks

Computed, never recorded as a counter. As of 2026-09-20:

```
R-N    rulings, implementation-record.md          high-water 34
DEC-N  decisions, implementation-plan.md §5        high-water 9
C-N    contracts, implementation-plan.md §6        high-water 8   (frozen)
T-N    tasks, implementation-plan.md §7            high-water 10
F-N    features, implementation-plan.md §4         high-water 6
V-N    validation rules, backend-charter.md §8     high-water 10
L-N    lessons, specialist-dispatch-lessons.md     high-water 37
```

Recompute, do not trust the numbers above:
```
for s in R DEC C T F V L; do grep -rhoE "\b${s}-?[0-9]+\b" docs/instructions/ | grep -oE '[0-9]+' | sort -n | tail -1; done
```
**Gaps are defects.** V-N is the one series that is *not* dense by accident: V1–V10 all exist.

## 5. Gate

One command, run whole. A path-scoped subset is not the gate; a run stopping at type-check is not green.

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

**Newest baseline: 427 passed, 3 contracts kept, exit 0** — recorded in
`phases/phase-1/01-store-and-read-path/implementation-record.md` under Evidence, at commit `12896e1`.

`uv` is not on the default PATH and env does not persist between calls (L9). A bare exit **137 is OOM,
not a test failure** (L36).

## 6. Invariants

Every rule a design or plan may silently break. Each anchored, each checkable read-only.

| # | Invariant | Anchor | Check |
|---|---|---|---|
| I-1 | `domain/` imports nothing from another layer and binds no forbidden stdlib | charter §2, L13 | `uv run lint-imports`; `uv run pytest tests/domain/test_purity.py` |
| I-2 | `mcp/` never imports `application.write` | D6, charter §2 | `uv run lint-imports` — contract `mcp-is-read-only` |
| I-3 | `cli` sits **above** `mcp`; `application` and `infrastructure` are siblings | R28 | `grep -A6 '^layers' pyproject.toml` |
| I-4 | Nothing writes to stdout in the `hl mcp` process | D8, R3, charter §11 | `uv run pytest tests/mcp/test_stdout_purity.py` |
| I-5 | `is_valid` means **no ERROR finding**; a WARNING never blocks | R22, DEC-4 | `uv run pytest -k warning_finding_does_not_make` |
| I-6 | A finding's severity comes from the register via `for_code()` | R13 | `uv run pytest -k severity_from_the_register` |
| I-7 | Charter §8's register is the authority; a rule reaches a report or its row is decorative | R22, R23 | `uv run pytest tests/domain/test_validation.py` |
| I-8 | Every `ErrorCode` has an exit-status row | C-6 | `uv run pytest -k every_error_code_has_an_exit_status` |
| I-9 | Contracts C-1…C-8 keep their shapes; amending one is plan-level | charter §6 | plan §6 versus `domain/`, `application/read/dtos.py` |
| I-10 | Nothing in initiative 01 writes to `~/.claude/` or any install target | plan §8 | content hash before/after — **`find -newermt` lies here** (L37) |
| I-11 | The fixture library is never deleted or weakened | charter §10 | `git log --diff-filter=D -- tests/fixtures/` |
| I-12 | An absence assertion carries a positive control | charter §10 | read the test |
| I-13 | Plans carry **no code** — signatures and file-level guidance only | `plan-formats.md` §1 | `grep -c '```' <plan>` |

## 7. UI authorities

**None yet.** No frontend territory, no brand reference, no mockups. Initiative 04 opens a React/TS
SPA under `frontend-system-pattern`; until then, a finding about UI pattern adherence is out of scope
and should say so rather than inventing an authority.

The CLI's human output is **not** contract (R7); `--json` is. A review of CLI output format should
check the `--json` payload and the DTOs, never the columnar text.

## 8. Calibration set

Incidents that actually happened here, and what they became. A reviewer should expect these shapes.

| Incident | Became |
|---|---|
| Two skills shipped as directories with an empty `references/` and no `SKILL.md`; they silently never loaded and nothing reported it | V1, and the reason this product exists |
| A plan specified ~1,400 lines of class and test bodies — the specialist's work, authored by the orchestrator | `plan-formats.md` §1; I-13 |
| V6 shipped **non-functional and green**: nothing populated the extraneous-file list, and only a pure unit test that was *handed* one covered it | I-12; the T-5 mutation must sit above the fake |
| An order-independence test could not detect a reversed sort — only a pinned golden digest caught it | L12 |
| A charter asserted a case-collision rule §8 never gave a code; the specialist refused to invent one | V8, R19 |
| A ruling amended contract C-4 in the documents but no dispatch changed the protocol, so the ruling was unimplementable under `mypy --strict` | R26 — transcription is not amendment |
| `[project.scripts]` was reported as committed and was not; a hand-verification passed against a **stale installed entry point** | R31, L34 |
| V3 fired 15 times on the real library with **zero** true positives; the rule's scope was wrong, not its regex | DEC-9, R32 |
| `hl validate` called a skill invalid that Claude Code loads fine, reporting "name is missing" about a file whose second line is `name:` | V10, R33 |
| An interrupted mutation check was misdiagnosed as half-finished work by the orchestrator | L35 |

**The shape to expect:** defects here are rules that are *wrong or unreachable*, documents that are
*ahead of or behind the code*, and verifications that pass against the *wrong thing*. Not syntax.
