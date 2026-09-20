# Implementation record — Store, validation, read path, MCP

**Status:** CLOSED — all ten tasks accepted. Initiative 01 is complete.
**Phase:** 1 · **Initiative:** 01-store-and-read-path · **Owner:** delivery lead
**Last updated:** 2026-09-20
**Reviewed:** 2026-09-20 · `phase-reviewer` · **NOT READY** · 8 blocking · resolved: B-3, B-4, B-7, B-8 fixed here; B-1, B-2, B-5 recorded as carried-forward and raised to the user; B-6 disputed in writing below and the remedy offered

Backward-facing: what actually shipped. The forward-facing intent is `implementation-plan.md`.

## Delivery status

| Id | What | Status |
|---|---|---|
| **F-1** Browse the library | `hl list` with filters and sorts, `--json` | **Delivered** — fixture + real library |
| **F-2** Inspect one artifact | `hl show`, incl. a broken artifact without raising | **Delivered** — verified on the entry-less fixture skill |
| **F-3** Search the library | `hl search` | **Delivered with a gap** — the matching line and number ship; **"one line of context either side" (spec §7.3) was never built**. See Carried forward |
| **F-4** Know what is broken | `hl validate`, exit non-zero on ERROR | **Delivered** — acceptance criterion covers V1–V7 only; V8–V10 shipped with tests but no criterion |
| **F-5** Collections | `hl collections` | **Delivered, proven against the fixture library only.** `~/.claude` declares no collections, so real-content proof was not available. Acceptance basis raised to the user |
| **F-6** MCP reach | four read-only tools over stdio | **Delivered** — verified over real JSON-RPC against the real library |
| **T-1** | Scaffold, gate, three import contracts | **Accepted** 2026-08-28 — commit `9256c60` |
| **T-2** | Domain vocabulary — C-1, C-2, C-3, registry, hashing, metadata types | **Accepted** 2026-08-28 — commit `57fff7f` |
| **T-3** | `RawArtifact`, the pure assembler, rules V1–V7 | **Accepted** 2026-08-28 — commit `519b7ed` |
| **T-4** | `library.yaml` reader, error taxonomy | **Accepted** 2026-08-28 — commit `519b7ed` |
| **T-4b** | Corrections: errors.py → domain/, V8 case collision, V9 duplicate keys | **Accepted** 2026-08-28 — commit `61d9c2f` |
| **T-5** | Scanner, repository, committed fixture library | **Accepted** 2026-08-28 — commit `ff5f540` |
| **T-6** | Read use cases, wire DTOs (C-5, C-7), error codes | **Accepted** 2026-09-01 — commit `2679cf2` |
| **T-7** | Read CLI, composition root, exit-code table (C-6, C-8) | **Accepted** 2026-09-01 — commit `785fb74` |
| **T-8** | Read-only stdio MCP server, four tools, `NOT_A_LIBRARY` | **Accepted** 2026-09-01 — commit `b569f92` |
| **T-9** | Acceptance against the real library | **Accepted** 2026-09-01 — commit `c5c38e8` |
| **T-10** | Corrections: V3 scope, V10, lazy MCP import | **Accepted** 2026-09-20 — commit `12896e1` |

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

**T-7 — gate re-run by the delivery lead:** exit 0, `381 passed` (up from 321). Nothing below `cli/` changed.

~~the `pyproject.toml` diff is the authorised `[project.scripts]` line only~~ — **struck 2026-09-20.** False. `git show 785fb74 -- pyproject.toml` contains no `[project.scripts]`; that line first landed in `b569f92` (T-8). The diff that *was* there is the **R28 layer-contract change** — `"harness_library.cli | harness_library.mcp"` split into two ordered layers — which is the one structural edit in that commit and went unnamed in this Evidence block. R31 below already records the underlying incident; this line was never corrected to match it.

~~`hl validate` / `hl list --json` / F-2 verified directly~~ — **re-attributed 2026-09-20.** Those hand-runs executed against a **stale installed entry point** (R31), so they verified nothing about the tree as committed. The conclusions survive on other evidence: F-2 is covered by `tests/cli/test_show.py::test_show_renders_findings_for_the_entry_less_skill` through Typer's runner rather than the installed binary, and the 9-error/3-warning figure reconciles rule-by-rule against `tests/fixtures/README.md`.
- **Exercised by hand, not only by test.** `hl validate` against the fixture library exits **1** and reports 9 errors and 3 warnings, with `skill/messy` correctly `[ok]` despite three V6 warnings (R22) and the two V7s landing under `library.yaml` (R23). `hl list --json` parses as JSON and reports 11 artifacts. A non-library directory exits **5** with a message naming what it expected.
- **F-2 verified directly:** `hl show skill/no-entry` — the entry-less fixture skill — exits **0** and renders the artifact. This is the case the superseded plan crashed on with an unhandled `FileNotFoundError`.
- **Mutation** — forcing `hl validate` to exit 0 failed `test_validate_exits_non_zero_when_an_error_finding_exists`; the control `test_validate_exits_zero_when_the_only_findings_are_warnings` **stayed green**. The specialist additionally ran the converse (always exit 1) to prove the pair is not satisfiable by a constant.
- Restored: `381 passed`.

**T-8 — gate re-run by the delivery lead:** exit 0, `405 passed` (up from 381). The MCP suite costs ~50s of the 60s wall clock, all subprocess spawn — that cost buys stdout purity being a fact about bytes rather than an inspection.
- **stdout-purity mutation** — a stray line in the `hl mcp` command body failed 3 purity tests; the control `test_the_server_still_reports_its_tool_calls_on_stderr` **stayed green**, so the rule is "nothing on stdout", not "no logging".
- **read-only mutation** — importing `application.write` into `mcp/tools.py` broke the `mcp-is-read-only` contract **and** failed `tests/test_architecture.py` on two assertions. Both halves fired, so the guarantee is structural rather than a promise.
- Restored: `405 passed`, `Contracts: 3 kept, 0 broken`.

**T-9 — acceptance.** Full output in the sibling document `2026-09-01-acceptance.md`, which plan §7 requires this record to reference and previously did not. Verdict there: F-1, F-2, F-3, F-6 pass against real content; F-4 passes on mechanism; **F-5 NOT PROVABLE against `~/.claude`**, which declares no collections.

**T-10 — gate re-run by the delivery lead:** exit 0, `427 passed` (up from 410).
- **Real library, verified directly:** `hl --library ~/.claude validate` reports **7 V3** (all two redirect stubs), **1 V10**, **1 V1**. Both agents are clean; the 8 false positives are gone. `frontend-system-pattern` reports one V10 naming line 3 — the description line — with no false V5.
- **V3 narrowing mutation, the pair that is the point of the fix:** removing the kind gate failed exactly `test_a_file_kind_artifact_citing_another_artifacts_reference_reports_nothing` and `test_a_file_kind_artifact_citing_a_skills_reference_is_not_a_v3`, while every directory-kind V3 test **stayed green**. The rule was narrowed, not gutted.
- **Import cost:** 1811 ms → 534 ms, 115 MCP modules → 0, asserted on the module set rather than elapsed time.
- **Delivery-lead error, recorded:** I diagnosed the interrupted tree as "tests written, feature not implemented". It was in fact frozen **mid-mutation-check** — the mutation deletes exactly the kind gate's two lines, and `pytest` was OOM-killed (exit 137) before the restore. All three fixes were already complete. An interrupted mutation manufactures the failure signature of half-built work; see lesson L35.

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
| **R34** | 2026-09-20 | **`skill/synced` is a genuine V1, not a false positive.** `~/.claude/skills/synced/` is Claude Code's own skill-sync bucket, which appeared after T-9's acceptance: a `.bucket-<uuid>` marker beside a `<uuid>_<uuid>/` directory holding roughly 25 skills two levels down. To the scanner it is one directory-kind artifact with no `SKILL.md`, so V1 fires correctly on content nobody authored as an artifact. **Initiative 02 must decide what install does with it** — it is in the target tree and is not ours. | initiative 02 |
| **R32** | 2026-09-20 | **V3 applies only to DIRECTORY-kind artifacts, resolving citations against the artifact's own files.** References belong to the skill that owns them, exactly as the directory structure already models. A single-file artifact cannot own a `references/` folder, so a citation in one is prose about another artifact. **Supersedes an earlier answer of library-wide resolution**, which was given but never recorded and never implemented — nothing shipped on it. The user proposed this model and it is better on both axes: it preserves precision a library-wide index would lose (a typo colliding with another skill's filename would pass), and it costs a one-line kind gate instead of a new cross-artifact pass. On the real library: 15 findings → 7, and → 0 once the two redirect stubs declare supersession in `library.yaml`. | T-10 |
| **R33** | 2026-09-20 | **V10: unparseable frontmatter is its own ERROR, and suppresses the V2/V5 cascade behind it.** The file genuinely is malformed YAML — a plain scalar cannot contain `": "` — so flagging it is correct; the defect was reporting `required frontmatter key 'name' is missing` about a file whose second line is `name:`. **Rejected: matching Claude Code's leniency.** That parser is undocumented, so we would be guessing at it and re-guessing on every change, and a lenient reader silently accepts files that break the moment anything strict reads them. Stays ERROR rather than WARNING: it works today only by the runtime's forgiveness, and the fix is one pair of quotes. | T-10 |
| **R30** | 2026-09-01 | **T-8 was right to read SCOPE over CONSTRAINTS on `cli/composition.py`.** My prompt required it to make `LibraryRootError` a `HarnessLibraryError`, then omitted the file that class lives in from the permitted list. It made the minimal edit, propagated the one consequence (`_run`'s now-redundant `except` branch, which would otherwise have reported `code: null` for a condition that now has a code), and flagged both plainly rather than silently. Accepted. The prompt was internally inconsistent; that is my defect. | every task |
| **R31** | 2026-09-01 | **`[project.scripts] hl` is declared.** T-7 wrote it; my `git restore` of a broken TOML edit reverted it while it was still uncommitted, and my re-apply failed to match without my noticing — so the T-7 commit message claiming it was in the diff was **false**, and no `hl` binary existed. My hand-verification of the CLI had passed against a stale installed entry point, which is verification of nothing. Found and reported by T-8. Fixed and verified. | initiative 03 |
| **R28** | 2026-09-01 | **`cli` sits ABOVE `mcp` in the layer contract**; they are no longer independent siblings. `cli/` owns the process entry point and the composition root, and hands `mcp/` a ready repository — a real hierarchy, not a fudge to get an import through. This keeps R2 (one environment reader) and C-8 (one root resolver) true across both adapters. My defect: T-7's brief told it that T-8 would register `hl mcp` into `cli/main.py`, which the contract forbade. It probed with a throwaway import before writing any code, reported, and built for this resolution rather than working around it. | T-8, initiative 03 |
| **R29** | 2026-09-01 | **`NOT_A_LIBRARY` is added to `ErrorCode`, in T-8.** Charter §13 demands a loud failure for a directory that is not a library, and §9 forbids inventing a code at a raise site — so T-7 correctly left `LibraryRootError` uncoded, mapping it to exit 5 by class. It grepped the ruling table per L25 first and found nothing, so this is an amendment rather than a transcription. Initiative 03 needs an HTTP status for the same condition. | T-8 |
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
| **F-3's "one line of context either side" was never built.** Spec §7.3 and plan §4 both require it; the shipped `SearchMatch` carries four fields and no context lines, and the DTO docstring *redefines* the requirement (*"this is the context feature F-3 asks for"*) rather than meeting it. It survived T-6, T-7 and T-9 because plan §8's F-3 criterion said only "and context" — wording no test can fail. **C-5 is frozen and 03/04 render from it, so the cost of deciding rises once 03 starts.** | **Raised to the user:** build it, or amend spec §7.3 to the shipped shape. Found by `phase-reviewer`, B-1 |
| **Six shipped behaviours have no spec amendment.** Spec §4 still lists V1–V7 and states V3 unqualified; §7.3 and §14 still say `skipped_binary`; §12.6 still calls scan cost unmeasured. Shipped: V8 (R19), V9 (R20), V10 (R33), V3 narrowed to directory-kind (R32/DEC-9), `skipped: tuple[SkippedFile, …]` (R25/R27), and a measured scan cost. `README.md` and the review profile both say the spec is amended at the source, never patched from here. | **Raised to the user** — the amendments are theirs to make. Found by `phase-reviewer`, B-2 |
| Scan-cost measurement | Plan §2 Deferred; **measured at T-9** — 17 ms scan against a 1.81 s import, now 534 ms. Spec §12.6 still calls it unmeasured |
| **A symlinked artifact *root* is skipped silently.** Not followed (R6) and not scanned, so a symlinked skill that would load perfectly is absent from the library with no diagnostic. Silent omission is the failure this product exists to eliminate, so this is a real gap — but no rule covers it, and inventing a decorative charter row is worse. | **Retargeted to initiative 02, 2026-09-20.** The T-9 decision point passed unanswered — T-9, T-10 and the initiative all closed without it, and this row still pointed at a finished task. T-9's recommendation is written and argued: defer to 02, because 02 must answer the symlink question at the install target anyway, where following one writes outside the target and replacing one destroys the user's dev link. **Still needs the user's yes.** Found by `phase-reviewer`, B-5 |
| **F-3's 184 KB HTML asset is not in the committed fixture library.** The acceptance criterion names it, but only the real library has it. T-9 runs against both and must cover it there, or the criterion is untested. | **T-9** |
| **Widening V10's suppression to V3.** A directory-kind redirect stub whose frontmatter fails to parse declares no `superseded_by` through R15's fallback, so in a library with no `library.yaml` the exemption is lost and V3 floods — the exact case charter §8 carves out, reopened by one unquoted colon. Latent today (both stubs parse). My recommendation: widen it, on R33's own logic — when the block did not parse we cannot evaluate a rule that depends on it. **User decision, not taken.** | initiative 02, or a one-line correction whenever wanted |
| **`FindingPayload`'s docstring says `V1` to `V9`** after V10 shipped (`application/read/dtos.py`). Inside frozen contract C-7, which is what 03 and 04 read; the enum itself is correct. **Code, not mine to edit** — a one-line specialist fix, bundled into the next backend dispatch. Found by `phase-reviewer`, non-blocking 7 |
| **Plan §6's C-5 under-lists the shipped shape** — it names `matches`, `truncated`, `skipped`; `SearchResults` also carries `query` and `limit`. Additive, not contradictory, but 03 builds against the plan's list. | Amend C-5's row when 03 opens, or sooner if the user prefers |
| **Plan §9's mutation table stops at T-8** and its baseline still reads "no code exists". T-4b, T-9 and T-10's mutations were run and recorded in the record and the acceptance report, but no forward row named their assertion first. | Fix when the plan is next amended; the mutations themselves were named in advance in the dispatch prompts |
| Unparseable frontmatter fires V5 (entry declares nothing) rather than a dedicated code | Acceptable; revisit if a user hits it and the message misleads |
| `mcp` pulls `starlette`/`uvicorn`/`sse-starlette` transitively — an HTTP stack is present in the venv that T-8 must not touch | Lesson L11, bound to T-8 |
| No `py.typed` marker in `src/harness_library/` | Not needed while nothing imports the library externally; revisit if initiative 03 or 04 consumes it as a package |

## Disputed reviewer findings

| Finding | My position |
|---|---|
| **B-6** — T-10 changed frozen contract C-3 and reversed a prior answer with no design record, so it should have taken the architectural path. | **Partly disputed, and partly conceded.** Disputed: the *substance* of the design gate was met in conversation, not skipped. The user proposed the directory-kind model themselves, was shown the rejected alternative and its cost, and chose; R32 records that provenance and DEC-9 carries its rejected alternative at design-record depth. The reversal reversed an answer that had **never been recorded or implemented** — no code, no ruling, nothing shipped on it. Conceded: `collaboration.md` §2 is explicit that *every* reversal takes the architectural path regardless of how small the change looks, and the ratchet clause forbids downgrading. The missing thing is the **artifact and the gate**, not the agreement. **Remedy offered to the user (decision 6 below): assemble a dated correction design in this folder from DEC-9/R32/R33, or rule the change bounded.** I have not chosen for them, because choosing would repeat the original defect.

## Lessons

L1–L7 predate this initiative (they came from the backend review of the superseded plan). **This initiative produced L8–L37** — thirty lessons, including L35–L37 added by the closing commit itself.
