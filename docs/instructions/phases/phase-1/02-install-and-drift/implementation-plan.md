# Implementation plan — Install, backup, drift

**Status:** Draft — cold read pending, then the user's review gate. **Not dispatchable.**
**Phase:** 1 · **Initiative:** 02-install-and-drift · **Owner:** delivery lead
**Last updated:** 2026-09-21
**Derived from:** `docs/specs/2026-08-28-harness-library-design.md` §8 · initiative 01's record (R6, R9, R34, R38, R43–R48)
**Depends on:** initiative 01 — contracts C-1 (per-file hashes), C-4 (`read_bytes`), C-6 (error taxonomy), C-8 (root resolution). **Blocks:** 03-http-api
**Independently deployable:** Yes — `hl install` replaces the manual `cp -a` on its own

> This plan carries no code. Signatures in §6 are frozen shapes; bodies are the specialist's.

---

## 1. Goal

Replace the manual directory copy that started this project with an install that can be inspected
before it runs, undone after it runs, and that cannot destroy a file it did not put there. The
library stays canonical; a target is derived. When this closes, installing the library into
`~/.claude/` — or any other directory — is a reviewable plan followed by a reversible write.

## 2. Scope

**In.** The three-hash verdict function · the target scanner · the manifest · backups · plan and
apply · drift reporting · rollback · uninstall and prune · foreign-file reporting and deliberate
cleaning · `--target PATH` · V11, the symlinked artifact root · export as a plain zip.

**Out.** Anything that reads only: the HTTP API (03), the SPA (04). Plugin-format export (R45).
Installing into a non-Claude harness layout (R47, closed).

**Deferred.**

| Item | Where |
|---|---|
| Plugin-format export | Its own initiative, when there is something to share (R45) |
| A three-way merge UI | Never — spec §8.5. Conflicts choose a side or open `$EDITOR` |
| Concurrency and locking | Charter §12 says 01 is read-only and 02 revisits it. **F-7 below** |

## 3. Prerequisites & external dependencies

| # | What | Owner | Blocking |
|---|---|---|---|
| P-1 | Initiative 01 closed, T-11 landed | delivery lead | **Yes** — C-5/C-7 settle in T-11 |
| P-2 | A real `library.yaml` for the user's own skills and agents | **user**, with the lead's help | No for the code; **yes** for F-5's real-content proof (R39) |
| P-3 | A target fixture tree, distinct from `~/.claude/` and from the library fixture | specialist, in T-3 | Yes — T-10 |

## 4. Features (F-N)

| # | Capability | Spec |
|---|---|---|
| **F-1** | **See what would change.** A plan over every artifact and path, grouped by verdict, before anything is written. `hl diff` reports drift without proposing a write. | §8.1 |
| **F-2** | **Install safely.** Apply the plan, backing up every path it will touch first, refusing on conflict. | §8.1, §8.3 |
| **F-3** | **Never touch what we did not write.** Foreign paths are reported and left. Removing one is a deliberate, listed act. | §8.2 |
| **F-4** | **Undo.** Restore a target to its state before any previous apply. | §8.3 |
| **F-5** | **Remove cleanly.** Uninstall an artifact by the manifest; prune what left the library. | §8.4 |
| **F-6** | **More than one target.** `--target PATH`, one manifest per target (R43). | §8.4, R43 |
| **F-7** | **Two installs cannot corrupt each other.** 01 was read-only; this one writes. | charter §12 |

## 5. Decisions (DEC-N)

| # | Decision | Why | Rejected | Affects |
|---|---|---|---|---|
| **DEC-10** | **The verdict function is pure, and written before anything reads a disk.** | DEC-1's lesson from 01, which removed two retrofit tasks: the task that computes is separated from the task that fetches. All eight hash combinations, including the three impossible ones, are table-tested with no I/O. | Computing verdicts inside the scanner — rejected: it is what made 01's V6 untestable above its fake. | T-1, T-4 |
| **DEC-11** | **Apply refuses on `LOCAL-EDIT` and `CONFLICT`; resolution is an explicit flag.** | Non-interactive and scriptable, and it cannot destroy an edit you forgot you made — the failure that started this project. Safe verdicts still write; the run stops with the plan printed. | Interactive prompting — rejected: hangs unattended and needs a second code path for CI. Back-up-and-overwrite — rejected: turns "I edited that" into a restore operation. R48. | T-5, T-8 |
| **DEC-12** | **`skill/synced` needs no rule.** | Claude Code's sync bucket is in the target, unknown to library and manifest — which is precisely `FOREIGN`. A named exclusion would silently hide whatever else lands there. | Special-casing the name — rejected. Suppressing its V1 — rejected: V1 is true, and suppressing a true finding to tidy a report is the shape two cold reads just undid. R44. | T-3 |
| **DEC-13** | **V11 covers both halves in one initiative.** | R38 deferred the symlinked root here precisely so the scan warning and the install refusal are decided together, rather than a warning in 01 and an unrelated policy in 02. | Warning only, install left alone — rejected: splits one question across two initiatives, which R38 existed to avoid. R46. | T-9 |
| **DEC-14** | **The manifest lives outside every tree it describes.** | `~/.local/state/harness-library/manifests/<sha256 of target path>.json`. Inside the target it would be a file the harness must learn to ignore; inside the library it would be committed and would differ per machine. | Either tree — rejected for the reasons above. Spec §8.4. | T-2 |

## 6. Contracts & interfaces (C-N)

Continuing 01's series. C-1…C-8 are inherited unchanged.

| # | Contract | Shape | Frozen because |
|---|---|---|---|
| **C-9** | `Verdict` | closed enum: `UNCHANGED` · `UPDATE` · `LOCAL_EDIT` · `CONFLICT` · `CREATE` · `PRUNE` · `FOREIGN` · `MANIFEST_REPAIR` | 03 renders a drift view from it; a rename would pass silently |
| **C-10** | `PlanEntry` · `InstallPlan` | entry: `artifact_id`, `path`, `verdict`, `library_sha`, `manifest_sha`, `target_sha` (each `str \| None`). Plan: entries, plus counts by verdict and an `is_applicable` flag | the CLI, 03's API and the apply step all read it |
| **C-11** | `Manifest` | `target_path`, `installed_at`, `library_git_sha`, `backup_dir`, and per artifact: `artifact_id`, `content_hash`, `files: tuple[ArtifactFile, ...]` reusing C-1 | it answers "which version is on this machine" across clones |
| **C-12** | `TargetRepository` (protocol, `domain/`) | `scan() -> tuple[TargetFile, ...]` · `read_bytes(path)` · `write(path, bytes)` · `delete(path)` · `exists(path)` | the one seam a fake replaces so apply is testable without a disk |
| **C-13** | `BackupStore` (protocol, `domain/`) | `create(paths) -> BackupId` · `restore(BackupId)` · `list() -> tuple[BackupRecord, ...]` | rollback is a first-class feature, not a directory convention |
| **C-14** | install exit codes | extends C-6: a distinct status for *refused on conflict*, separate from *failed* | a script must tell "you must decide" from "it broke" |

**Amendment to C-6:** the error taxonomy gains codes for target-not-writable, manifest-unreadable,
backup-failed and conflict-refused. Each enters the contract before it is emitted (charter §9).

## 7. Work breakdown & dispatch (T-N)

Owner `backend-developer-specialist`, territory `src/harness_library/**` and `tests/**`.

| # | Deliverable | Layer | Depends on |
|---|---|---|---|
| **T-1** | The pure verdict function and `InstallPlan` (C-9, C-10). All eight hash combinations table-tested, the three impossible ones raising. Zero I/O. | domain | — |
| **T-2** | The manifest: read, write, its location, and a corrupt-manifest path that fails loudly (C-11, DEC-14). | domain + infra | T-1 |
| **T-3** | The target scanner and `TargetRepository` (C-12), plus the committed target fixture (P-3), including a foreign tree standing in for `synced/`. | infra | T-1 |
| **T-4** | `PlanInstall` — compose library, manifest and target into a plan. Pure over the three protocols. | application | T-2, T-3 |
| **T-5** | `BackupStore` (C-13) and `ApplyInstall`: back up before writing, all-or-nothing per invocation, refuse on conflict (DEC-11). | application + infra | T-4 |
| **T-6** | Rollback and uninstall, both driven by the manifest and neither touching a foreign path. | application | T-5 |
| **T-7** | Prune and `clean --foreign`, each listing before acting. | application | T-6 |
| **T-8** | CLI: `install`, `diff`, `uninstall`, `rollback`, `clean`, `export`; `--target`, `--dry-run`, `--prune`, `--resolve`; exit codes (C-14). | cli | T-7 |
| **T-9** | V11: the symlinked artifact root — warning on scan, refusal on install (DEC-13). Touches 01's assembler and this initiative's apply. | domain + application | T-5 |
| **T-10** | Acceptance against the real library **and** the target fixture, including a real `library.yaml` authored with the user (P-2), which also gives 01's F-5 its real-content proof (R39). | — | T-8, T-9 |

**Parallelism, graded per `cost-and-time.md` §2.** T-2 ∥ T-3 is the only pair: different layers,
different files, both consuming only T-1's frozen types. Everything else shares a type or a file.

## 8. Acceptance criteria

| F | Criterion |
|---|---|
| **F-1** | Each of the five reachable verdicts is produced by a fixture built for it, asserted **as a verdict value**, not as the presence of a row. The three impossible hash combinations raise rather than defaulting. `hl diff` on an untouched target reports `UNCHANGED` for every path and exits 0. |
| **F-2** | Apply writes every safe verdict and **refuses** the run when any `LOCAL_EDIT` or `CONFLICT` is present, printing the whole plan and exiting with the conflict-refused status — distinct from the failure status. A backup exists before the first byte is written; apply with an injected mid-write failure leaves the target byte-identical to its pre-apply state. |
| **F-3** | A foreign path is **byte-identical** after apply, asserted on the file, not on the report. `clean --foreign` lists every path before removing any, and removes nothing the manifest knows. |
| **F-4** | Rollback restores a target to its exact prior hash set, asserted per file. |
| **F-5** | Uninstall removes exactly the manifest's files and nothing else; a foreign file in the same directory survives, asserted. `--prune` removes a manifest-known file that left the library, and only that. |
| **F-6** | Two targets installed from one library keep separate manifests; installing into one leaves the other's manifest and files untouched, asserted. |
| **F-7** | Two concurrent applies to the same target do not interleave writes. **The mechanism is the specialist's to choose and must be stated in their task plan before implementation.** |
| **V11** | A symlinked artifact root produces a WARNING on scan and is named and refused in the plan. Neither the link nor its destination is written, asserted on both. |

**Cross-cutting.** No test writes to `~/.claude/`. Asserted by content hash, never by mtime (L37).

## 9. Verification

**The gate** — unchanged, one command, run whole:

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

**Baseline at open:** initiative 01's final count, recorded in its record at close.

**Mutation checks** — the assertion that must fail is named before the run, with a surviving control.

| Task | Mutation | Must fail | Must stay green |
|---|---|---|---|
| T-1 | Collapse `MANIFEST_REPAIR` into `CONFLICT` | the manifest-stale table row, by verdict value | every other row |
| T-2 | Return an empty manifest for a corrupt file | the corrupt-manifest test | the absent-manifest test — absent is not corrupt |
| T-3 | Stop recording foreign paths | the foreign-file test **at repository level** | the domain-level verdict test, correctly blind |
| T-5 | Skip the backup when the plan has one entry | the backup-exists test | the refuse-without-backup test |
| T-5 | Apply the safe verdicts and ignore the conflict | the refusal test, **on exit code and on the file** | the all-safe-verdicts run, which must still write |
| T-6 | Have uninstall remove the whole artifact directory | the foreign-file-survives test | uninstall's own removal test |
| T-9 | Follow the symlink instead of refusing | the destination-untouched test | the warning test — warning and refusal are two facts |

**Positive controls.** Every assertion of absence — "no file written", "foreign untouched", "nothing
outside the target" — carries a sibling proving it can fail.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| A bug here **destroys the user's working harness** — the first initiative that writes outside the repo | Backup before any write, refused apply if the backup cannot be taken, all-or-nothing per invocation, and `~/.claude/` never used as a test target |
| "Install worked" verified against stale state | R31's incident. Acceptance asserts on file content hashes, never on a command's own report |
| A verdict test that passes for the wrong reason | 01's V6 shipped unwired for exactly this. T-3's mutation sits **above** the fake |
| `~/.claude` moves under us mid-run | The sync bucket rewrites itself (L37). The scan is a snapshot; a target changing mid-apply is a stated limitation, not a silent one |
| The conflict path is the least-exercised and the most dangerous | It is the one verdict with two mutation rows |

## 11. Next

Closing this unblocks **03-http-api**, which renders C-9 and C-10 as a drift view. It also gives
initiative 01's F-5 its real-content proof as a side effect of P-2, and retires R34, R38 and R39.
