# Implementation plan — Store, validation, read path, MCP

**Status:** CLOSED 2026-09-20 — all ten tasks accepted. **Frozen-contract source for initiatives 02–04.**
**Phase:** 1 · **Initiative:** 01-store-and-read-path · **Owner:** delivery lead
**Last updated:** 2026-09-20
**Reviewed:** 2026-09-20 · `phase-reviewer` · **NOT READY** · 8 blocking · see the record's Reviewed row for the disposition of each
**Derived from:** `docs/specs/2026-08-28-harness-library-design.md` · `2026-08-28-backend-review.md`
**Depends on:** nothing · **Blocks:** 02-install-and-drift, 03-http-api, 04-web-ui
**Independently deployable:** Yes — a working read-only CLI and MCP server

> This plan carries no code. Signatures in §6 are frozen shapes; function and test bodies are the
> specialist's to write with full file context.

---

## 1. Goal

Build the foundation every later initiative sits on: a filesystem-backed store that reads skills and
agents out of the library tree, validates them against seven rules, and exposes them through a
read-only CLI and a read-only stdio MCP server. Nothing here writes to `~/.claude/` or to any other
install target. When this closes, a user can browse, inspect, search and validate their library from a
terminal, and any MCP client can pull a skill or a single reference file on demand.

## 2. Scope

**In.** The domain vocabulary and pure rules · the `library.yaml` reader · the scanner and repository ·
the read use cases · the read CLI with a `--json` contract · the stdio MCP server with four read tools ·
the architecture import contracts · a fixture library committed to the repo · acceptance against the
real library.

**Out.** Anything that writes: install, backup, manifest, drift, rollback, prune, `hl new`, `hl edit`.
The HTTP API. The React SPA.

**Deferred.**

| Item | Where it is tracked |
|---|---|
| `ExportArtifact` / zip and plugin-format export | 02-install-and-drift; its repository primitive (`read_bytes`, C-4) is frozen **here** |
| Scan-cost measurement and any caching | spec §12.6 — measure once T-9 exists; do not pre-optimise |
| Additional install targets, non-Claude harnesses | spec §12.1, §12.3 — both are 02 concerns |
| Editing reference files in the UI | 04-web-ui |

## 3. Prerequisites & external dependencies

| # | What | Owner | Blocking |
|---|---|---|---|
| P-1 | Git repository initialised, spec and plan committed | delivery lead | **Done** — `main`, 2 commits |
| P-2 | `uv` available on the build machine | specialist | Yes — T-1 |
| P-3 | Approved dependency set (charter §4) | delivery lead | **Done** — R1, R2, R3 |
| P-4 | A fixture library committed to the repo, distinct from `~/.claude/` | specialist, in T-5 | Yes — T-9 needs it **in addition to** `~/.claude/`, which cannot prove collections, tags or supersession (L6) |

## 4. Features (F-N)

| # | Capability | Spec ref |
|---|---|---|
| **F-1** | **Browse the library.** List every artifact with its type, description, tags, file count and validity. Filter by type, tag, collection, or invalid-only. Sort by name, last update, or size. | §7.1, §7.2 |
| **F-2** | **Inspect one artifact.** Its entry text, its full file list, its parsed frontmatter, and any validation findings — including for an artifact that is broken. | §7.1 |
| **F-3** | **Search the library.** Find a phrase across entry files and markdown references, with the matching line, its line number, and one line of context either side. | §7.1, §7.3 |
| **F-4** | **Know what is broken.** Report every validation finding with its rule code and severity, and exit non-zero when any ERROR exists. | §4 |
| **F-5** | **Collections.** List collections and resolve their members, so a set of artifacts can be addressed as one thing. | §3.4 |
| **F-6** | **Reach the library from any LLM session.** Four read-only MCP tools over stdio, including fetching a single reference file without its parent skill. | §7.3 |

## 5. Decisions (DEC-N)

| # | Decision | Why | Rejected alternative | Affects |
|---|---|---|---|---|
| **DEC-1** | **Validation is a pure function over a `RawArtifact`, written *before* the repository exists.** | The original plan built the repository first and retrofitted validation and metadata into it across two later tasks. Root cause: the builder assembled an `Artifact` from inputs it then discarded. One pure intermediate type removes both retrofits and moves most behaviour into zero-I/O tests. | Repository first, validation bolted on — rejected: two of eight tasks existed only to reopen a third. | T-2, T-3, T-5 |
| **DEC-2** | **The architecture import contracts land in the scaffold, not at the end.** | Seven tasks would otherwise be written with no guard, and a layering violation introduced early is found last. | Contracts with the MCP server — rejected: costs nothing in T-1 and protects everything after it. | T-1 |
| **DEC-3** | **Per-file hashes are part of the frozen entity.** | Spec §8.1 judges install per path on three hashes. Without per-file digests, initiative 02 re-implements scanning on a second code path and the two drift. | Whole-artifact hash only — rejected: guarantees duplicate scanners. | C-1, C-2 |
| **DEC-4** | **Findings carry severity; `is_valid` means no ERROR.** | Spec §4 grades V6 a warning. A single boolean would let a stray `.swp` file make an artifact uninstallable. | Boolean validity — rejected: blocks install on cosmetic findings. | C-3 |
| **DEC-5** | **`--json` is the machine contract; human output is not.** | Frees the columnar format to change forever, and removes the brittle substring assertions the review flagged. | Human output as contract — rejected: every column tweak becomes breaking. Ruling R7. | C-5, T-7 |
| **DEC-6** | **MCP wire payloads are shared DTOs in `application/read/dtos.py`.** | `mcp/` must not import `api/`, and initiative 03 must not invent a second serialisation of the same entity. | Inline dict construction per adapter — rejected: two serialisations of one entity, guaranteed to diverge. | C-7 |
| **DEC-9** | **References belong to the skill that owns them; V3 resolves locally and applies only to directory-kind artifacts.** | The on-disk structure already models this — `skills/<name>/references/*.md`. An agent is one file and can never own a `references/` folder, so a citation inside one is prose about a skill's files, never a claim about its own. This keeps the rule's teeth: the failure that justified V3 — a skill citing references into its own empty directory — is a directory-kind artifact and is still caught. | **Library-wide resolution**, where a citation is satisfied if the path exists under any artifact. Chosen first, then superseded before any code was written: it takes the real library to zero findings but accepts a typo silently whenever it collides with another skill's filename, and it costs more — a new cross-artifact index and a move to the library-level pass, against a one-line kind gate. | T-10 |
| **DEC-8** | **The `library.yaml` domain types (`ArtifactMetadata`, `Collection`, `LibraryMetadata`) move from T-4 into T-2.** | T-3 implements V7, which validates that every `library.yaml` entry resolves — so it consumes those types. With them in T-4, T-3 and T-4 share a type and must run sequentially. Moving the types into T-2, where the domain vocabulary already lives, leaves T-4 as a pure infrastructure reader and makes the pair genuinely independent: different files, different layers, both consuming frozen T-2 types. | Leaving them in T-4 — rejected: forces the only available parallelism in the plan to be given up for no structural benefit. Also considered moving V7 into T-4, rejected because it splits the validation rules across two layers and fights DEC-1. | T-2, T-3, T-4 |
| **DEC-7** | **The MCP tool list is derived from one source, not hand-maintained beside it.** | A hand-written name tuple next to the schema list means the test guarding the read-only surface passes through exactly the change it exists to catch. | Parallel constant — rejected: the guard is theatre. | C-7, T-8 |

## 6. Contracts & interfaces (C-N)

Frozen. Initiatives 02–04 build against these; changing one is a plan-level decision, not a task-level
one. Field lists and signatures only — the specialist writes the bodies.

| # | Contract | Shape | Frozen because |
|---|---|---|---|
| **C-1** | `ArtifactFile` | `path: str` · `sha256: str` · `size: int` · `is_text: bool` | 02 judges install per path; without this it rebuilds the scanner |
| **C-2** | `Artifact` | spec §3.2 as amended — including `frontmatter`, `is_dirty`, `files: tuple[ArtifactFile, ...]`, `findings` | every layer and every later initiative consumes it |
| **C-3** | `ValidationFinding` | `code: ValidationCode` (closed enum, V1–V10 as of R33; charter §8 is the register) · `severity: ERROR \| WARNING` · `message: str` · `path: str \| None` | 04's SPA branches on the code; a string would let a rename pass silently |
| **C-4** | `ArtifactRepository` | `list_all() -> list[Artifact]` · `get(id) -> Artifact \| None` · `read_bytes(id, path) -> bytes` · `read_text(id, path) -> str` · `list_collections() -> list[Collection]` · `library_findings() -> list[ValidationFinding]`, with documented snapshot semantics | `read_bytes` is what makes binary install and zip export possible in 02/03; `read_text` alone forecloses both |
| **C-5** | Read use-case surface | `ArtifactFilter` (typed, not `str`) · `SortKey` · `SearchResults` with `matches`, `truncated: bool`, `skipped: tuple[SkippedFile, ...]` each carrying a `SearchSkipReason`, capped at 200 · `ValidationReport` · `--json` payload shape | the CLI, the MCP server and 03's API all render from these |
| **C-6** | Error taxonomy | one base exception · stable string codes · mapping to CLI exit codes now, HTTP status in 03 | a code is added to the contract before it is emitted |
| **C-7** | MCP wire payloads | Pydantic DTOs in `application/read/dtos.py`; tool names and schemas derived from one registry | `mcp/` may not import `api/`; 03 must reuse, not re-serialise |
| **C-8** | Composition root | `--library` → `$HL_LIBRARY` → cwd; single settings object; fails loudly on a non-library directory | every adapter and every later initiative resolves the root identically |

## 7. Work breakdown & dispatch (T-N)

All tasks: owner `backend-developer-specialist`, territory `src/harness_library/**` and `tests/**`.

**Concurrency.** Graded per `cost-and-time.md` §2 — shared *files*, *types*, *vocabulary* and *test
fixtures* all force sequencing, and topic separation is not independence. Exactly one pair qualifies.

| Group | Tasks | Why |
|---|---|---|
| **P-A** | T-3 ∥ T-4 | Independent after DEC-8: `domain/assembly.py` vs `infrastructure/library_yaml.py`, different layers, no shared type. Run in separate worktrees, **gates staggered** (§3). |
| — | all others | T-7 and T-8 both register commands in `cli/main.py` — a shared file, therefore sequential regardless of the wall-clock appeal. Every other task consumes the previous one's frozen types. |

**T-1 is reconnaissance** (§4). The toolchain traps L1, L3 and L4 all land in it, and it runs alone
before anything is scoped against its outcome.

| # | Deliverable | Layer | Depends on |
|---|---|---|---|
| **T-1** | Scaffold, the one gate command, and the three architecture import contracts. Package `__init__.py` files for `tests` and every subpackage (L1). | — | — |
| **T-2** | Domain vocabulary: `ArtifactType`, `ArtifactKind`, `ValidationCode`, `Severity`, `ValidationFinding`, `ArtifactFile`, `Artifact`, content hashing, the type registry. | domain | T-1 |
| **T-3** | `RawArtifact` and the pure assembler, including **all of V1–V7**. The task that removes the rework (DEC-1). | domain | T-2 |
| **T-4** | `library.yaml` reader with shape validation and line-numbered failures. | domain + infra | T-2 |
| **T-4b** | Corrections arising mid-initiative: the error taxonomy moved from `infrastructure/` to `domain/` (R17), V8 case collision (R19), V9 duplicate `library.yaml` keys (R20). Added after T-4 returned; recorded here so the task list accounts for every dispatch. | domain + infra | T-4 |
| **T-5** | The scanner and the repository, composed from T-3 and T-4. Includes the committed fixture library (P-4). | infrastructure | T-3, T-4 |
| **T-6** | Read use cases, including collections. | application | T-5 |
| **T-7** | Read CLI, composition root, `--json` output, loud failure on a non-library root. | cli | T-6 |
| **T-8** | MCP server driven over real JSON-RPC frames, plus the stdout-purity test. | mcp | T-6 |
| **T-9** | Acceptance against **both trees**: the committed fixture library, which is the only one that proves collections, tags and supersession; **and** `~/.claude`, which is the only one that holds real authored content and the 184 KB HTML asset. Output recorded in `<date>-acceptance.md` and cited from the implementation record. | — | T-7, T-8 |
| **T-10** | Corrections from acceptance: V3 scoped to directory-kind artifacts (DEC-9), V10 for unparseable frontmatter, and a lazy MCP import so every non-`mcp` command stops paying 1.3 s for an SDK it never touches. | domain + cli | T-9 |

**Changed from the superseded plan:** old T-1+T-2 merged into T-2 · old T-5 (validation) moved **ahead**
of the repository as T-3 · import contracts moved from last to first · old T-8 split into T-1, T-8 and
T-9. Net 8 → 9. Nothing dropped.

## 8. Acceptance criteria

Per feature, so F-N ↔ acceptance stays traceable.

| F | Criterion |
|---|---|
| **F-1** | Every artifact in the fixture library appears in `hl list --json`, including invalid ones. Each filter returns exactly the expected id set. Each sort key returns a defined, stable order. Superseded artifacts appear by default, ranked below their successors (R8). |
| **F-2** | `hl show <id>` returns entry text, file list and frontmatter for a valid artifact, **and for an invalid one returns its findings rather than raising**. A skill with no `SKILL.md` is shown with its V1 finding — this is the case §4 exists to serve, and the superseded plan crashed on it. |
| **F-3** | A phrase present only in a reference file is found, with correct path, line number and context. Only the entry document and `.md` references are searched, per R4. The 184 KB HTML asset is not searched and is reported as skipped — it is valid UTF-8, so the reason is *not a markdown reference*, never *binary*. A genuinely non-UTF-8 file is reported the same way. A result set above the cap sets `truncated: true`. |
| **F-4** | Each of **V1–V10** fires on a fixture built for it and does **not** fire on a clean artifact. (V8, V9 and V10 were added mid-initiative by R19, R20 and R33; V8/V9/V10 are proven under `tmp_path` rather than in the committed fixture — see `tests/fixtures/README.md` for why.) V6 findings do not make an artifact invalid. `hl validate` exits non-zero on ERROR, zero when only warnings exist. |
| **F-5** | `hl list --collection <key>` returns exactly the declared members. A member id that resolves to nothing produces V7. |
| **F-6** | A real MCP client handshake enumerates exactly four tools, **read from the server** rather than a constant. Each tool returns its documented payload. `get_reference` returns one reference without its parent's entry text. `hl mcp` emits **nothing** on stdout under any error, including an invalid flag. |

**Cross-cutting:** no file under `~/.claude/` is created, modified or deleted by anything in this
initiative. Asserted, not assumed.

## 9. Verification

**The gate** — one command, run whole. A path-scoped subset is not the gate; a run stopping at
type-check is not green (L2).

```
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

**Baseline:** no code exists. T-1 establishes the baseline as green on an empty tree with the contracts
reported as kept.

**Mutation checks** — the assertion that must fail is named **before** the run. Each: break it, quote the
named failure, restore, quote green.

| Task | Mutation | Named assertion that must fail |
|---|---|---|
| T-1 | Add an import of `application` into `domain` | `lint-imports` reports the `domain-is-pure` contract broken **and** `tests/test_architecture.py` fails. If only one fires, the contract is not wired as a test (L3). |
| T-2 | Reverse the sort in the content-hash input | the hash-stability test fails, and no other test does — an independence check |
| T-3 | Remove the `superseded_by` exemption from V3 | the redirect-stub fixture test fails with **seven** findings (L5), and the plain missing-reference test still passes |
| T-4 | Return an empty metadata object instead of raising on malformed YAML | the malformed-`library.yaml` test fails; the absent-file test stays green |
| T-5 | Stop recording skipped paths in the scan | the V6 test fails **at the repository level**. This mutation must sit above the fake — a V6 test that only ever receives a hand-built list proves nothing, which is how the superseded plan shipped V6 unwired. |
| T-6 | Remove the search result cap | the truncation test fails |
| T-7 | Return exit code 0 when ERROR findings exist | the `hl validate` exit-code test fails |
| T-8 | Write one line to stdout in the MCP entry path | the stdout-purity test fails (L7) |

**Positive controls.** Every assertion of absence — "no stdout output", "no file written under
`~/.claude/`", "this rule does not fire" — carries a sibling test proving the assertion is capable of
failing. An absence test with no positive control is not evidence.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| A contract in §6 turns out unbuildable, forcing a rewrite of finished tasks | They were derived by the specialist who reviewed the whole plan, not by the delivery lead. A task that finds one wrong **stops and reports** rather than adapting locally. |
| `import-linter`'s layer ordering silently permits what it appears to forbid | T-1's mutation check is exactly this, and it is the first check performed (L3). |
| `updated_at` from git costs a subprocess per artifact on every scan | Measure in T-9 before optimising. The fallback path is already specified, so a cache is additive, not a redesign. |
| Acceptance against `~/.claude/` looks green while proving little | T-9 runs against **both** trees and states what each proves. `~/.claude/` is a target layout with no `library.yaml`, so it cannot exercise collections, tags or supersession (L6); the fixture library cannot exercise real authored content. Neither alone is acceptance. |
| The seven V3 stub findings are mistaken for a regex bug and "fixed" | L5 is pasted verbatim into T-3 and T-9, and the exemption is in charter §8. |

## 11. Next

Closing this unblocks **02-install-and-drift**, which consumes C-1 (per-file hashes), C-4 (`read_bytes`)
and C-8 (root resolution) directly. 03-http-api consumes C-5 and C-7. Ruling R6 (symlinks) and R9 (file
mode) are recorded here because 02 inherits them silently otherwise.
