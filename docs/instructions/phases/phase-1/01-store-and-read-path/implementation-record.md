# Implementation record — Store, validation, read path, MCP

**Status:** Open — T-1 accepted, T-2 next
**Phase:** 1 · **Initiative:** 01-store-and-read-path · **Owner:** delivery lead
**Last updated:** 2026-08-28

Backward-facing: what actually shipped. The forward-facing intent is `implementation-plan.md`.

## Delivery status

| Id | What | Status |
|---|---|---|
| F-1 … F-6 | see plan §4 | Not started |
| **T-1** | Scaffold, gate, three import contracts | **Accepted** 2026-08-28 — commit `9256c60` |
| T-2 … T-9 | see plan §7 | Not dispatched |

## Evidence

**T-1 — gate re-run by the delivery lead, not accepted on the specialist's report.**

`uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest` → **exit 0**. 20 files formatted, all ruff checks passed, mypy clean over 15 source files, 3 contracts KEPT, 4 tests passed.

**T-1 — mutation check re-run independently.** Probe: `from harness_library import application` appended to `domain/__init__.py`.
- Broken: `lint-imports` → `layered-architecture BROKEN`, `domain-is-pure BROKEN`, `Contracts: 1 kept, 2 broken`; `pytest` → 3 failed, 1 passed. **Both halves fired**, so the contract is wired as a test and not merely as a lint step.
- Independence control: `mcp-is-read-only` stayed `KEPT` throughout, and its parametrized test was the one that passed.
- Restored: `Contracts: 3 kept, 0 broken`, 4 passed.

**Boundary:** `git status --porcelain docs/` showed only the specialist's own task plan. No commit was authored by the specialist.

## Rulings (R-N)

Every boundary call, numbered. Specialists do not read this file — the delivery lead carries each
binding ruling into the dispatch prompt in their own words.

| # | Date | Ruling | Binding on |
|---|---|---|---|
| **R1** | 2026-08-28 | **`pyyaml` is permitted**, as a carve-out from `backend-system-architecture` §5's config-format prohibition. `library.yaml` is user-authored *data*, not application configuration; the ban targets config sprawl. Spec §3.4 mandates the format, and `python-frontmatter` vendors PyYAML regardless. Application config uses `pydantic-settings`, never YAML. | T-4 |
| **R2** | 2026-08-28 | **`pydantic-settings` is in the dependency set.** House baseline. One settings object is the sole reader of the environment; no other module calls `os.environ`. | T-1, T-7 |
| **R3** | 2026-08-28 | **`structlog` is in the dependency set, bound to stderr.** No log record at any level may reach stdout in any process. `hl mcp` owns stdout for JSON-RPC; one stray line kills the client with no diagnosable error. The stdout-purity test is an acceptance criterion. | T-1, T-7, T-8 |
| **R4** | 2026-08-28 | **Search covers the entry file and every `.md` reference; binary is never searched**, and each skipped binary is reported so the omission is visible. Resolves spec §12.5. | T-6, T-8 |
| **R5** | 2026-08-28 | **`updated_at` derives from the last git commit touching the artifact's paths**, falling back to max mtime when the library is not a repo or the artifact is uncommitted, in which case `is_dirty` is set. A clone rewrites every mtime, and D2 makes clones the normal case. | T-2, T-5 |
| **R6** | 2026-08-28 | **Symlinks are skipped and reported** as a V6 warning. Never followed, never hashed, never installed. A link resolving outside the artifact root is how a copy writes outside its target, and initiative 02 writes into `~/.claude`. | T-3, T-5; **initiative 02** |
| **R7** | 2026-08-28 | **`--json` is contract; human columnar output is not.** Tests assert the JSON payload, never substrings of the human format. Initiative 04 consumes the API or `--json`, never the columnar text. | T-7 |
| **R8** | 2026-08-28 | **Superseded artifacts appear in the default listing**, ranked below their successors, carrying `superseded_by` in every payload. `include_superseded` defaults true. Hiding them would make a redirect stub invisible, which is the opposite of why supersession is first-class. | T-6, T-8 |
| **R10** | 2026-08-28 | **`uv.lock` is committed.** This is an application, not a distributed library, and D2 makes clones the normal case — an unlocked resolution means the gate can pass on one machine and fail on another. Version floors stay out of `pyproject.toml`; the lockfile is the pin. | every task |
| **R11** | 2026-08-28 | **`ruff` permanently excludes `docs/`**, and the exclusion survives every `pyproject.toml` edit. Ruff's formatter rewrites Python code fences inside Markdown and names no files when it does, which let a specialist silently edit two documents outside their territory. Every task confirms `git status --porcelain docs/` is clean before reporting. | every task |
| **R12** | 2026-08-28 | **`.claude/agent-memory/` is gitignored.** Agent-local scratch is not a project artifact; the durable form of anything learned there is a numbered lesson in the dispatch-lessons log, which is the delivery lead's to write. | every task |
| **R9** | 2026-08-28 | **File mode is excluded from the content hash.** Every file in the real library is `-rwxrw-rw-`, an accident of how it was copied. Initiative 02 normalises mode on install. | T-2; **initiative 02** |

## Deviations from plan

| # | Deviation | Whose reasoning won |
|---|---|---|
| 1 | T-1 did not add `[project.scripts] hl = ...`. | **Specialist.** The entry point would name `cli/main.py`, which T-7 has not written, and a dangling entry point breaks the install. Deferred to T-7. |

## Delivery-lead defects found by specialists

| # | Defect | Fix |
|---|---|---|
| 1 | T-1's dispatch said "nothing under `~/.claude/` has been **read**". That contradicts the specialist's standing instruction to consult `backend-system-architecture`, which lives at `~/.claude/skills/`. The plan's §8 criterion is correctly worded — *created, modified or deleted* — and the prompt was the defect, not the plan. | Prompt wording corrected from T-2 onward. The specialist flagged rather than guessed, which is the behaviour the prompt asks for. |

## Carried forward

| Item | Tracked in |
|---|---|
| Review item S8 — the import-linter contract as drafted did not express spec §7.3's guarantee and permitted `infrastructure → application` | Fixed in plan DEC-2 and T-1's mutation check; spec §14 records that §7.3's statement was correct and the translation was not |
| Spec §12.2 plugin-format export | Shapes 02's export; C-4's `read_bytes` is frozen here to keep it possible |
| Scan-cost measurement | Plan §2 Deferred; measure at T-9 |
| `mcp` pulls `starlette`/`uvicorn`/`sse-starlette` transitively — an HTTP stack is present in the venv that T-8 must not touch | Lesson L11, bound to T-8 |
| No `py.typed` marker in `src/harness_library/` | Not needed while nothing imports the library externally; revisit if initiative 03 or 04 consumes it as a package |

## Lessons

Reconciled into `docs/instructions/specialist-dispatch-lessons.md` (L1–L7) when this initiative closes.
