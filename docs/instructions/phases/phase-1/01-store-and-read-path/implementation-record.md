# Implementation record — Store, validation, read path, MCP

**Status:** Open — T-1…T-6 accepted; T-7 next
**Phase:** 1 · **Initiative:** 01-store-and-read-path · **Owner:** delivery lead
**Last updated:** 2026-08-28

Backward-facing: what actually shipped. The forward-facing intent is `implementation-plan.md`.

## Delivery status

| Id | What | Status |
|---|---|---|
| F-1 … F-6 | see plan §4 | Not started |
| **T-1** | Scaffold, gate, three import contracts | **Accepted** 2026-08-28 — commit `9256c60` |
| **T-2** | Domain vocabulary — C-1, C-2, C-3, registry, hashing, metadata types | **Accepted** 2026-08-28 — commit `57fff7f` |
| **T-3** | `RawArtifact`, the pure assembler, rules V1–V7 | **Accepted** 2026-08-28 — commit `519b7ed` |
| **T-4** | `library.yaml` reader, error taxonomy | **Accepted** 2026-08-28 — commit `519b7ed` |
| **T-4b** | Corrections: errors.py → domain/, V8 case collision, V9 duplicate keys | **Accepted** 2026-08-28 |
| **T-5** | Scanner, repository, committed fixture library | **Accepted** 2026-08-28 — commit `ff5f540` |
| **T-6** | Read use cases, wire DTOs (C-5, C-7), error codes | **Accepted** 2026-09-01 |
| T-7 … T-9 | see plan §7 | Not dispatched |

## Evidence

**T-1 — gate re-run by the delivery lead, not accepted on the specialist's report.**

`uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest` → **exit 0**. 20 files formatted, all ruff checks passed, mypy clean over 15 source files, 3 contracts KEPT, 4 tests passed.

**T-1 — mutation check re-run independently.** Probe: `from harness_library import application` appended to `domain/__init__.py`.
- Broken: `lint-imports` → `layered-architecture BROKEN`, `domain-is-pure BROKEN`, `Contracts: 1 kept, 2 broken`; `pytest` → 3 failed, 1 passed. **Both halves fired**, so the contract is wired as a test and not merely as a lint step.
- Independence control: `mcp-is-read-only` stayed `KEPT` throughout, and its parametrized test was the one that passed.
- Restored: `Contracts: 3 kept, 0 broken`, 4 passed.

**Boundary:** `git status --porcelain docs/` showed only the specialist's own task plan. No commit was authored by the specialist.

**T-2 — gate re-run by the delivery lead.** Same command → **exit 0**, `76 passed`, `Contracts: 3 kept, 0 broken`.

**T-2 — both mutation checks re-run independently.**
- `is_valid` changed to `not self.findings` → exactly one test failed, `test_warning_finding_does_not_make_an_artifact_invalid`. The DEC-4 semantics are genuinely guarded.
- `sorted(entries)` → `sorted(entries, reverse=True)` → exactly one test failed. **The assertion that caught it was `assert content_hash(FILE_SET) == GOLDEN_CONTENT_HASH`, not the order-independence assertion**, which passed straight through. See lesson L12 — this is the finding of T-2 and it generalises.

**Boundary:** only `src/**`, `tests/**` and the specialist's own task plan. No commit authored.

**T-3 ∥ T-4 — the parallel wave, verified INTEGRATED rather than per-branch.** The two worktrees had zero file overlap outside the shared task plan. Merged, then the gate run **alone** on the integrated tree: **exit 0**, `149 passed`, `Contracts: 3 kept, 0 broken`.

Both mutations re-run by the delivery lead on the integrated tree:
- **T-3** — removing the V3 `superseded_by` exemption failed `test_redirect_stubs_produce_seven_v3_findings_without_the_exemption` plus one sibling. The named must-stay-green control, `test_a_missing_reference_on_a_live_artifact_is_a_v3_error`, **passed throughout** — so the exemption is not "skip V3 for the wrong set of artifacts".
- **T-4** — making malformed YAML return empty metadata failed `test_malformed_yaml_raises_with_the_line_number` plus two siblings. The named control, `test_absent_file_is_empty_metadata`, **passed throughout** — a malformed file is not conflated with an absent one.
- Restored: `149 passed`.

**T-4b — gate re-run by the delivery lead:** exit 0, `172 passed` (up from 149), 3 contracts kept. `infrastructure/errors.py` confirmed gone, not copied.
- **V8 mutation** — grouping key made case-sensitive → `test_two_names_differing_only_by_case_are_a_v8_error` failed; the control `test_the_same_name_under_two_types_is_not_a_collision` **passed**, so `skill/foo` and `agent/foo` remain distinct.
- **V9 mutation** — duplicate collection returned empty → `test_an_artifact_id_declared_twice_is_recorded_as_a_duplicate` plus one sibling failed; the control `test_a_key_declared_once_records_no_duplicate` **passed**.
- Restored: `172 passed`.

**T-5 — gate re-run by the delivery lead:** exit 0, `256 passed` (up from 172). `subprocess` confirmed confined to `infrastructure/`; `src/harness_library/domain/` and `tests/domain/` byte-for-byte unchanged.
- **V6 mutation, above the fake** — dropping every `skipped.append` in the scanner failed `test_a_real_symlink_becomes_a_v6_warning_on_the_assembled_artifact`, driven off a symlink committed into the fixture library. The domain-level `test_a_symlink_is_reported_as_a_v6_warning_and_never_blocks` **stayed green**, correctly blind to a scanner defect. This is the check that would have caught the superseded plan shipping V6 entirely unwired.
- **R5 mutation** — forcing `GitTimestamps.for_artifact` to the mtime fallback failed 8 tests, `test_updated_at_is_the_last_commit_touching_the_artifact_and_not_its_mtime` among them.
- **Delivery-lead error, recorded for honesty:** my first attempt at the R5 mutation reported 256 passed and looked like a refuted claim. The regex had patched the *protocol stub* rather than `GitTimestamps.for_artifact`, so nothing was mutated. A no-op mutation is indistinguishable from a well-guarded one unless you check that the edit landed — verify the patch, not just the result.
- Restored: `256 passed`.

**T-6 — gate re-run by the delivery lead:** exit 0, `321 passed` (up from 256).
- **Search-cap mutation** → 2 named tests failed; the control `test_an_under_cap_search_returns_every_match_and_is_not_truncated` **stayed green**.
- **`library_findings()` mutation** → 4 tests failed including the named V7 and V9 cases, confirming R23: without it those two rules can never fail a library.
- **Third mutation, run on my initiative** — swapping the handler order so `ValueError` shadows `UnicodeDecodeError` failed 3 tests. The trap the specialist flagged is genuinely guarded, not merely commented.
- Restored: `321 passed`.

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
| **R26** | 2026-09-01 | **Transcribing an existing ruling into code is not amending a contract.** T-6 added `library_findings()` to `domain/repository.py`. R23 and plan §6 had already made it part of C-4, but the amendment landed only in the documents — T-5 added the method to its implementation and left the contract to me, and I amended the plan without dispatching the protocol edit. Under `mypy --strict` R23 was therefore unimplementable. Accepted; the gap was mine. **When a ruling amends a contract, the protocol change must be scoped into the next dispatch explicitly.** | every task |
| **R27** | 2026-09-01 | **C-5's search-skip field is `skipped: tuple[SkippedFile, ...]` carrying a `SearchSkipReason`, not `skipped_binary: list[str]`.** Follows R25. The enum's second member `unreadable_as_text` — a `.md` reference whose bytes contradict the scan — is accepted as new closed-enum surface; it is structurally unreachable for a non-markdown file because the path test runs first and reads nothing. Plan §6 corrected. | T-7, T-8, initiative 03 |
| **R23** | 2026-08-28 | **`library_findings()` joins contract C-4.** V7 and V9 land on `AssembledLibrary.findings` and were otherwise unreachable from the read path, so F-4 could report neither. That is R22's "decorative row" failure arriving by a different door: a rule that cannot reach a report cannot make a library invalid. The specialist added it as explicitly additive and did not touch the contract, which was correct — amending C-4 is mine. | T-6, T-7 |
| **R24** | 2026-08-28 | **The repository keeps raising plain Python exceptions; T-6's use cases translate them into typed errors with codes.** Charter §9 forbids emitting a code not in the contract, and `domain/errors.py` was outside T-5's territory, so it correctly raised `KeyError` / `FileNotFoundError` / `ValueError`. The application layer is where a code becomes meaningful, because that is what T-7 maps to an exit code and initiative 03 maps to an HTTP status. | T-6, T-7 |
| **R25** | 2026-08-28 | **F-3's `skipped_binary` wording was wrong and the plan is corrected.** R4's rule is "the entry document and every `.md` reference", not "everything that is text". The bundled 184 KB HTML asset is valid UTF-8, so a decode-based `is_text` correctly calls it text — and it is still not searched, because it is not a markdown reference. The reason reported is *not a markdown reference*, never *binary*. My defect: I wrote a criterion that contradicted my own ruling. | T-6, T-8, T-9 |
| **R21** | 2026-08-28 | **`LibraryYamlError.path` is `str`, not `pathlib.Path`.** Moving the taxonomy into `domain/` (R17) collided with `test_purity.py`'s forbidden-stdlib set, which lists `pathlib`. Three repairs existed; two — a `TYPE_CHECKING` import, or removing `pathlib` from the forbidden set — work by disarming the guard. Narrowing the field was the only one that kept both mechanisms honest. The absolute location it names is unchanged. | T-5 onward |
| **R22** | 2026-08-28 | **V9 is raised as a finding by the assembler, not as an error by the reader.** The reader *observes* each repeat and records a `DuplicateKey` with its line; the assembler decides severity and wording. This is V6's existing shape — observation in `infrastructure/`, severity in `domain/` — and V7 is the direct precedent: a `library.yaml` id resolving to nothing is a fault of the same document and is a finding. A rule in charter §8 that could never reach a report could never make `is_valid` false, so its row would be decorative. The surviving value stays last-wins, now documented: neither block can be preferred on merit, so the answer is the ERROR, not a cleverer merge. | T-6, T-7 |
| **R15** | 2026-08-28 | **`library.yaml` is authoritative for `superseded_by`, with a fallback to the entry document's frontmatter.** Accepting the specialist's addition: V3's exemption is a property of *being a redirect stub*, and a library with no `library.yaml` still has stubs, so without the fallback V3 floods on exactly the case §8 carves out. Noted for a later initiative: spec §3.4's own principle — that `library.yaml` holds only what the artifact files cannot express — arguably favours frontmatter as the primary home. Not churning it now. | T-5, T-6 |
| **R16** | 2026-08-28 | **`yaml.compose(..., Loader=yaml.SafeLoader)` satisfies R1**, whose literal words said `safe_load`. `compose` stops at the node tree and never reaches a constructor, so it meets R1's stated *reason* more strictly than `safe_load` does — and it is the only way to obtain a line number for a **shape** error, without which `tags: process` could be diagnosed but never located. Pinned by a test using a real `!!python/object/apply:os.system` payload and an observable marker file. R1's wording is hereby amended to name the reason, not the function. | T-4 onward |
| **R17** | 2026-08-28 | **`errors.py` moves from `infrastructure/` to `domain/`, in T-5, before a second error code is added.** The reason is structural, not cosmetic: `application/` may not import `infrastructure/` — they are independent siblings under `layered-architecture` — so an application-layer error cannot inherit from a base living there. The specialist identified this while correctly staying inside its own territory. | T-5 |
| **R18** | 2026-08-28 | **`types-PyYAML` is NOT added.** One `# type: ignore[import-untyped]` in the single quarantine module `infrastructure/_yaml_document.py`, which hands out a typed node model. A second module needing PyYAML is a stop-and-ask, not a second ignore. | any task touching YAML |
| **R19** | 2026-08-28 | **V8 (case collision) is added to charter §8.** §7 asserted the rule and §8 never defined a code for it, and §9 forbids emitting a code before it is in the contract — so the specialist correctly left it unimplemented and reported. My charter defect. Decided at the library level, like V4 and V7. | T-3 follow-up |
| **R20** | 2026-08-28 | **V9 (duplicate key in `library.yaml`) is added to charter §8**, and authorised as a follow-up. Last-wins silently discards the first block's tags — the exact silent-data-loss failure this product exists to eliminate. Detection is nearly free because the reader composes to a node tree, where `YamlMapping.pairs` is a list and both entries remain visible. | T-4 follow-up |
| **R13** | 2026-08-28 | **A `ValidationFinding`'s severity must agree with its code's entry in charter §8.** The specialist added a `__post_init__` check and a `for_code()` constructor so a caller cannot hand-downgrade a V1 to a warning. C-3's frozen shape is unchanged — the field stays — but the register is now the single authority for what a code means. Accepted: two places holding one decision is how they drift. | T-3 onward |
| **R14** | 2026-08-28 | **The `ArtifactRepository` protocol (C-4) stays in `domain/repository.py`**, declared with T-2's vocabulary rather than with T-5's implementation. A protocol is part of the domain's statement of what it needs; the implementation is infrastructure's answer. This is Mode A as the charter states it. | T-5, T-6 |
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
| 3 | Charter §7 asserted a case-collision rule that charter §8 never gave a code, while §9 forbids emitting a code outside the contract. The rule was unimplementable as written. | V8 added to charter §8 (R19). The specialist reported rather than inventing a code, which is the asked-for behaviour. |
| 2 | R12's `.gitignore` pattern `.claude/agent-memory/` never matched. A pattern containing a mid-string slash is anchored to the `.gitignore`'s own directory, so it matched only the repo root, never `docs/instructions/.claude/agent-memory/`. Every backend dispatch would have had to choose between violating the R11 boundary check and skipping its memory. | Corrected to `**/.claude/agent-memory/` and verified with `git check-ignore -v`. Found by the specialist, who correctly refused to edit a root config file outside its territory. |
| 1 | T-1's dispatch said "nothing under `~/.claude/` has been **read**". That contradicts the specialist's standing instruction to consult `backend-system-architecture`, which lives at `~/.claude/skills/`. The plan's §8 criterion is correctly worded — *created, modified or deleted* — and the prompt was the defect, not the plan. | Prompt wording corrected from T-2 onward. The specialist flagged rather than guessed, which is the behaviour the prompt asks for. |

## Carried forward

| Item | Tracked in |
|---|---|
| Review item S8 — the import-linter contract as drafted did not express spec §7.3's guarantee and permitted `infrastructure → application` | Fixed in plan DEC-2 and T-1's mutation check; spec §14 records that §7.3's statement was correct and the translation was not |
| Spec §12.2 plugin-format export | Shapes 02's export; C-4's `read_bytes` is frozen here to keep it possible |
| Scan-cost measurement | Plan §2 Deferred; measure at T-9 |
| **A symlinked artifact *root* is skipped silently.** Not followed (R6) and not scanned, so a symlinked skill that would load perfectly is absent from the library with no diagnostic. Silent omission is the failure this product exists to eliminate, so this is a real gap — but no rule covers it, and inventing a decorative charter row is worse. | **Decision point at T-9.** Either a new rule with an implementation in the same change, or an explicit recorded "won't fix" for initiative 02. Not left to a task. |
| Unparseable frontmatter fires V5 (entry declares nothing) rather than a dedicated code | Acceptable; revisit if a user hits it and the message misleads |
| `mcp` pulls `starlette`/`uvicorn`/`sse-starlette` transitively — an HTTP stack is present in the venv that T-8 must not touch | Lesson L11, bound to T-8 |
| No `py.typed` marker in `src/harness_library/` | Not needed while nothing imports the library externally; revisit if initiative 03 or 04 consumes it as a package |

## Lessons

Reconciled into `docs/instructions/specialist-dispatch-lessons.md` (L1–L7) when this initiative closes.
