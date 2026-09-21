# Implementation plan — Install, backup, drift

**Status:** Draft — second cold read pending.
**Reviewed:** 2026-09-21 · `phase-reviewer` × 2 · NOT READY (9 blocking), then NOT READY (7 blocking) · all sixteen resolved; one disputed in writing (§12); see the design record for the decisions behind them
**Phase:** 1 · **Initiative:** 02-install-and-drift · **Owner:** delivery lead
**Last updated:** 2026-09-21
**Derived from:** `docs/specs/2026-08-28-harness-library-design.md` §8 · initiative 01's record (R6, R9, R34, R38, R43–R48, R50–R54) · `2026-09-21-design.md` in this folder
**Depends on:** initiative 01, **closed 2026-09-21 at 437 tests** — contracts C-1 (per-file hashes), C-4 (`read_bytes`), C-6 (error taxonomy), C-8 (root resolution). Nothing here touches C-5. **C-7 is touched once** — `FindingPayload`'s code range widens with V11 (T-20). **Blocks:** 03-http-api
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
cleaning · `--target PATH` · V11, the symlinked artifact root · export as a plain zip · conflict resolution (`--resolve`).

**Out.** The HTTP API (03) and the SPA (04). *(Read-only use cases are not out — `DiffAgainstTarget` and `ExportArtifact` both live in `application/read/` and are In.)* Plugin-format export (R45).
Installing into a non-Claude harness layout (R47, closed).

**Mode normalisation is In** (R9, R56): install writes `0644` for files and `0755` for directories, owned by T-16 and asserted in F-9. Mode is excluded from the content hash, so it is not content — and every file in the real library is `-rwxrw-rw-`, an artefact of how it was copied.

**Concurrency is In**, not deferred: a single-writer advisory lock (R50), owned by T-17.

**Deferred.**

| Item | Where |
|---|---|
| Plugin-format export | Its own initiative, when there is something to share (R45) |
| A three-way merge beyond choose-a-side | Never — spec §8.5 |

## 3. Prerequisites & external dependencies

| # | What | Owner | Blocking |
|---|---|---|---|
| P-1 | Initiative 01 closed, T-11 landed | delivery lead | **Satisfied 2026-09-21** (`4167c44`). The dependency was never C-5/C-7 — nothing here touches search or the MCP DTOs — it was a **file** collision: T-11 edited `domain/assembly.py`, which T-20 also touches |
| P-2 | A real `library.yaml` for the user's own skills and agents | **user**, with the lead's help | No for the code; **yes** for F-5's real-content proof (R39) |
| P-3 | A target fixture tree, distinct from `~/.claude/` and from the library fixture | specialist, in T-14 | Yes — T-23 |

## 4. Features (F-N)

| # | Capability | Spec |
|---|---|---|
| **F-8** | **See what would change.** A plan over every artifact and path, grouped by verdict, before anything is written. `hl diff` reports drift without proposing a write. | §8.1 |
| **F-9** | **Install safely.** Apply the plan, backing up every path it will touch first, refusing on conflict. | §8.1, §8.3 |
| **F-10** | **Never touch what we did not write.** Foreign paths are reported and left. Removing one is a deliberate, listed act. | §8.2 |
| **F-11** | **Undo.** Restore a target to its state before any previous apply. | §8.3 |
| **F-12** | **Remove cleanly.** Uninstall an artifact by the manifest; prune what left the library. | §8.4 |
| **F-13** | **More than one target.** `--target PATH`, one manifest per target (R43). | §8.4, R43 |
| **F-14** | **Two installs cannot corrupt each other.** A single-writer advisory lock, held for the duration of an apply (R50). | charter §12 |
| **F-15** | **Resolve a refusal.** `--resolve library\|target` per artifact, or open both versions in `$EDITOR`. No merge UI. (R54) | §8.5 |
| **F-16** | **Export a collection as a plain zip.** The `ExportArtifact` use case 01 deferred here; read-only, `application/read/`. (R45) | §7.1, §7.2 |

## 5. Decisions (DEC-N)

| # | Decision | Why | Rejected | Affects |
|---|---|---|---|---|
| **DEC-10** | **The verdict function is pure, and written before anything reads a disk.** | DEC-1's lesson from 01, which removed two retrofit tasks: the task that computes is separated from the task that fetches. All eight hash combinations, including the three impossible ones, are table-tested with no I/O. | Computing verdicts inside the scanner — rejected: it is what made 01's V6 untestable above its fake. | T-12, T-15 |
| **DEC-11** | **Apply refuses on `LOCAL-EDIT` and `CONFLICT`; resolution is an explicit flag.** | Non-interactive and scriptable, and it cannot destroy an edit you forgot you made — the failure that started this project. Safe verdicts still write; the run stops with the plan printed. | Interactive prompting — rejected: hangs unattended and needs a second code path for CI. Back-up-and-overwrite — rejected: turns "I edited that" into a restore operation. R48. | T-16, T-22 |
| **DEC-12** | **`skill/synced` needs no rule.** | Claude Code's sync bucket is in the target, unknown to library and manifest — which is precisely `FOREIGN`. A named exclusion would silently hide whatever else lands there. | Special-casing the name — rejected. Suppressing its V1 — rejected: V1 is true, and suppressing a true finding to tidy a report is the shape two cold reads just undid. R44. | T-14 |
| **DEC-13** | **V11 covers both halves in one initiative.** | R38 deferred the symlinked root here precisely so the scan warning and the install refusal are decided together, rather than a warning in 01 and an unrelated policy in 02. | Warning only, install left alone — rejected: splits one question across two initiatives, which R38 existed to avoid. R46. | T-20 |
| **DEC-14** | **The manifest lives outside every tree it describes.** | `~/.local/state/harness-library/manifests/<sha256 of target path>.json`. Inside the target it would be a file the harness must learn to ignore; inside the library it would be committed and would differ per machine. | Either tree — rejected for the reasons above. Spec §8.4. | T-13 |

## 6. Contracts & interfaces (C-N)

C-1…C-8 are inherited from initiative 01 unchanged. **Two of them are amended here**, each with its
mirror target named, because a contract amended in a plan and nowhere else is R26's recorded failure.

| # | Contract | Shape | Frozen because |
|---|---|---|---|
| **C-9** | `Verdict` | closed `StrEnum`, nine members: `UNCHANGED` · `UPDATE` · `LOCAL_EDIT` · `CONFLICT` · `CREATE` · `PRUNE` · `FOREIGN` · `MANIFEST_REPAIR` · **`SKIPPED`** (V11's symlinked root — present in the library but unscannable, so it is neither applied nor conflicted). Underscored spelling is canonical; the spec's hyphenated prose is the same value | 03 renders a drift view from it; a rename would pass silently |
| **C-10** | `PlanEntry` · `InstallPlan` | **Presence is resolved before equality (R55): the §8.1 table applies only when library, manifest and target all hold the path. Five presence cases produce an entry; a sixth — absent from all three — produces none, which is why the rule's return type is `Verdict | None`.** `PlanEntry`: `artifact_id: str \| None` — `None` only for a `FOREIGN` path under no artifact root (R60) · `path: str` · `verdict: Verdict` · `library_sha: str \| None` · `manifest_sha: str \| None` · `target_sha: str \| None \| UNHASHED_TARGET_SHA` — three states (R72): a digest, `None` for *not held*, and the named constant for *held but unreadable*. **Only the three shas are optional**; a `None` means that side does not hold the path. `reason: str \| None` — set on `SKIPPED` and `CONFLICT`, so a plan explains itself without a second lookup, and filled by **`plan_entry_for(...)`, the one constructor that knows which of the four conflict shapes fired** (R61). `InstallPlan`: `entries: tuple[PlanEntry, ...]` · `counts: Mapping[Verdict, int]` (**derived, and dense over all nine verdicts** — R62) · `is_complete: bool` (**derived**), **defined as: no entry carries `LOCAL_EDIT`, `CONFLICT` or `SKIPPED`** — a complete run exits 0, an incomplete one exits `INCOMPLETE = 6` (R57). Named `PlanEntry`, superseding spec §5's `PlanAction` | the CLI, 03's API and apply all read it |
| **C-11** | `Manifest` | `target_path: str` · `installed_at: datetime` · `library_git_sha: str \| None` · `backup_id: str \| None` · `artifacts: tuple[ManifestArtifact, ...]`, each `artifact_id: str` · `content_hash: str` · `files: tuple[ArtifactFile, ...]` reusing C-1 | it answers "which version is on this machine" across clones |
| **C-12** | `TargetRepository` (protocol, `domain/`) | **+ `read_link(path) -> str` and `write_link(path, destination)`** (R97) · `scan() -> tuple[TargetFile, ...]` where `TargetFile` is `path: str` · `sha256: str` · `size: int` · `is_symlink: bool` · `read_bytes(path) -> bytes` · `write(path, data: bytes) -> None` · `delete(path) -> None` · `exists(path) -> bool` | the one seam a fake replaces so apply is testable without a disk |
| **C-13** | `BackupStore` (protocol, `domain/`) | `create(paths: tuple[str, ...]) -> str` returning a backup id · `restore(backup_id: str) -> None` · `list() -> tuple[BackupRecord, ...]` where `BackupRecord` is `backup_id: str` · `created_at: datetime` · `target_path: str` · `paths: tuple[str, ...]` | rollback is a feature, not a directory convention |
| **C-16** | `WriteLock` (protocol, `domain/`) | one member, `hold() -> AbstractContextManager[None]`, with `FilesystemWriteLock` in `infrastructure/`. **Required keyword-only on every write use case** (R82) | a write path without one is outside charter §12 and every gate stays green |
| **C-15** | `ManifestStore` (protocol, `domain/`) | one member, `write(manifest)`, with `FilesystemManifestStore` in `infrastructure/`. R78 — `application/` may not import `infrastructure/`, and the manifest was the one source left as module functions | apply, rollback and uninstall all write it |
| **C-14** | install exit statuses | extends C-6's table with **`INCOMPLETE = 6`** (some artifact was not applied; the plan says why — a conflict awaiting `--resolve`, or a V11 skip), **`TARGET_UNWRITABLE = 7`**, **`MANIFEST_UNREADABLE = 8`**, **`BACKUP_FAILED = 9`**, **`LOCK_HELD = 10`**, **`MANIFEST_UNWRITABLE = 11`**, **`TARGET_UNREADABLE = 12`** (R57, R59, R64, R70), **`RECORD_STALE = 13`** (R90 — the work was done and the record could not be written; the mirror of 11, and the reason 11 can promise *nothing happened*. Shipped in T-19 and **added to this row in T-22**, which found it in the code and not in the contract — R26's shape again) and **`EDITOR_FAILED = 14`** (R102 — `$EDITOR` is unset, unparseable, or would not run. The only status about the user's *machine* rather than about their library, their target or this tool's record, and the only one whose remedy is a shell variable; T-21 let the editor's `OSError` out rather than mislabel it, and without a code the user meets a traceback). `cli/exit_codes.py` ended at `LIBRARY_UNUSABLE = 5`, so 6–14 were next-free. There is no generic failure status, which is why 6 is named for the outcome rather than for one of its two causes | a script must tell "you must decide" from "it broke" |

**Amendment to C-3 — `ValidationCode` gains `V11`.** Mirror targets: charter §8 (already carries it),
spec §4 (amended 2026-09-21), `domain/validation.py`'s enum and its `SEVERITY_BY_CODE` row (WARNING),
`tests/domain/test_validation.py`'s register test, **`application/read/dtos.py`'s `FindingPayload` docstring** (it enumerates the code range and is inside C-7 — so the front matter's "nothing here touches C-7" is wrong and is corrected below), **`domain/assembly.py`'s `AssembledLibrary` docstring**, which enumerates its members, and initiative 01's plan §6 C-3 row. **Owned by T-20.**

**Amendment to C-6 — five new error codes:** `TARGET_UNWRITABLE`, `MANIFEST_UNREADABLE`,
`BACKUP_FAILED`, `INCOMPLETE`, `LOCK_HELD`, each with the exit status C-14 fixes. Charter §9 requires a code to enter the contract before it is
emitted, and **I-8 requires every `ErrorCode` to have a row in `cli/exit_codes.py` or the gate fails**.
**All five codes and all five exit rows land in T-13**, the first task that emits one — not in T-19,
which is three tasks later.

## 7. Work breakdown & dispatch (T-N)

Owner `backend-developer-specialist`, territory `src/harness_library/**` and `tests/**`.
**Ids are project-wide** (R51); initiative 01 used T-1…T-11 and F-1…F-7.

| # | Deliverable | Layer | Depends on |
|---|---|---|---|
| **T-12** | The pure verdict function and `InstallPlan` (C-9, C-10). All eight hash combinations table-tested, the three impossible ones raising. Paths crossing the domain boundary are `str`, already frozen by C-10/C-11/C-12 and by R21 — **confirm and document, do not relitigate**; `tests/domain/test_purity.py` bars `pathlib` from `domain/`. The three transitivity violations raise a bare `ValueError`; they are unreachable states, not user-facing errors, so they take no `ErrorCode`. Zero I/O. | domain | — |
| **T-13** | The manifest (C-11, DEC-14), **plus the whole C-6 amendment**: five error codes and their five `cli/exit_codes.py` rows, added before any is emitted. A corrupt manifest fails loudly and is not confused with an absent one. | domain + infra + cli | T-12 |
| **T-14** | The target scanner and `TargetRepository` (C-12), including `is_symlink` per entry, plus the committed target fixture (P-3) with a foreign tree standing in for `synced/`. | infra | T-13 |
| **T-15** | `PlanInstall` in `application/write/` — compose library, manifest and target into a plan. Also `DiffAgainstTarget` in `application/read/`. **Spec §5 fixes which use case lands on which side; `mcp-is-read-only` (I-2) stays green either way, so the contract will not catch a mistake here.** | application | T-14 |
| **T-16** | `BackupStore` (C-13) and `ApplyInstall`. Also carries three corrections: **R73** move `target_path_of` into `domain/registry.py`; **R74** the `<type>/<name>` guard onto `ManifestArtifact`; **R75** refuse an artifact with an ERROR finding as `SKIPPED` with a reason, `--force` overriding. **Order is load-bearing (R63): back up, then write the manifest, then write the files.** A failed manifest write aborts before any file is touched, raising `MANIFEST_UNWRITABLE`. Writing the manifest last would let a crash leave the target modified with no record, making every installed file read `FOREIGN` — untouchable by install and unremovable by uninstall. Also: back up before writing, refuse if the backup cannot be taken, **write every safe verdict and leave every `LOCAL_EDIT` / `CONFLICT` artifact untouched**, exit `INCOMPLETE` (DEC-11, R57). Never writes a path absent from the plan. | application + infra | T-15 |
| **T-17** | The single-writer advisory lock (R50): an `O_EXCL` sentinel beside the manifest, released on exit, stale-broken by pid check. Wraps every write path. **Also adds `TARGET_UNREADABLE = 12`'s `ErrorCode` member** (R81) — C-14 named the integer and no enum carries it. | infra | T-16 |
| **T-18** | Rollback and uninstall, manifest-driven, neither touching a foreign path. | application | T-17 |
| **T-19** | Prune and `clean --foreign`, each listing before acting. | application | T-18 |
| **T-20** | **V11** (C-3 amendment, R46, R53): detection in `infrastructure/scanner.py`, the finding on `AssembledLibrary.findings` **like V7 and V9 — not V8**, whose docstring says explicitly that it attaches to the colliding artifacts because it has two real ones; V11 has none, because the root was never scanned. That docstring enumerates its members and T-20 must extend it. — severity via `for_code()`, and the install refusal of **that artifact only**, not the run. | domain + infra + application | T-16 |
| **T-21** | `--resolve library\|target` per artifact plus `$EDITOR` with both versions (F-15, R54), and `ExportArtifact` as a plain zip (F-16, R45). **Also carries R97**: `symlinked_roots()` into C-4 and `read_link`/`write_link` into C-12, both of which T-20 left additive because the contracts were outside its scope. | application | T-20 |
| **T-22** | CLI: `install`, `diff`, `uninstall`, `rollback`, `clean`, `export`; `--target`, `--dry-run`, `--prune`, `--resolve`. Exit statuses per C-14. | cli | T-21 |
| **T-24** | Corrections from acceptance: **D-2** the backup records and restores file mode (R110, C-13 amendment, a security regression); **D-1** `STATE_UNWRITABLE = 15` and the lock translates `OSError` (R111); **R112** a rollback with nothing to put back is not an error; **R113** `hl backups` exposes `BackupStore.list()`. | domain + infra + cli | T-23 |
| **T-23** | Acceptance against the real library **and** the target fixture, including a real `library.yaml` authored with the user (P-2), which also gives initiative 01's **F-5** its real-content proof (R39). | — | T-22 |

**Parallelism: none.** T-13 and T-14 looked like a pair, but both are infrastructure and both depend on
the `str`-versus-`Path` vocabulary T-12 settles — `cost-and-time.md` §2 grades a shared vocabulary
sequential. Serial throughout.

## 8. Acceptance criteria

Stated as **values**, per L39: a criterion naming a thing rather than a value is one no test can fail.

| F | Criterion |
|---|---|
| **F-8** | **Eight of the nine `Verdict` members are producible here**; `SKIPPED` is T-20's and the rule must never emit it, asserted by a sweep. Each producible member is produced by a fixture built for it and asserted **as a verdict value**. The three impossible hash combinations raise rather than defaulting. `CREATE` fires for a library artifact absent from manifest and target; `PRUNE` for a manifest path gone from the library; `MANIFEST_REPAIR` rewrites the manifest and leaves every file byte-identical, asserted on the files. `hl diff` on an untouched target reports `UNCHANGED` for every path and exits 0. |
| **F-9** | A plan mixing safe and conflicted entries **writes every safe entry**, leaves every conflicted artifact byte-identical, and exits `INCOMPLETE = 6` — all three asserted in one test, because that combination is the ambiguity DEC-11 exists to settle. Installed files carry mode `0644` and directories `0755`, asserted on the stat (R56). **The manifest exists before the first file is written** — asserted by injecting a failure into the first file write and finding the manifest already on disk (R63). **A failed manifest write leaves the target byte-identical** and exits `MANIFEST_UNWRITABLE = 11`. A backup exists before the first byte is written. **A failed backup or a failed manifest write leaves the target byte-identical**, asserted per file — that is what R63's ordering buys. A failure at the *k*-th file write leaves earlier files written and the manifest over-claiming, which is deliberate: those paths return as `LOCAL_EDIT` on the next diff and the user is asked, rather than `FOREIGN` and unrecoverable. **Apply does not self-restore mid-run; that is rollback (F-11, T-18)** — R80. **Apply never writes a path absent from the plan**, asserted by a write-recording fake. **Apply refuses when the backup cannot be written**, simulated by a read-only backup directory. |
| **F-10** | A foreign path is **byte-identical** after apply, asserted on the file, not on the report. `clean --foreign` lists every path before removing any, and removes nothing the manifest knows. |
| **F-11** | Rollback restores a target to its exact prior hash set, asserted per file. |
| **F-12** | Uninstall removes exactly the manifest's files; a foreign file in the same directory survives, asserted. `--prune` removes a manifest-known file that left the library, and only that. |
| **F-13** | Two targets installed from one library keep separate manifests; installing into one leaves the other's manifest and files untouched, asserted. |
| **F-14** | A second apply against a target whose lock is held **exits without writing**, asserted on the target's hash set being unchanged and on the exit status. A stale sentinel whose pid is gone is broken and the apply proceeds. |
| **F-15** | `--resolve library` writes the library's version; `--resolve target` leaves the target byte-identical and repairs the manifest; both exit 0. Resolution is per artifact, asserted by resolving one of two conflicts and finding the other still refused. |
| **F-16** | Exporting a collection yields a zip whose entries are exactly the collection's artifacts' files, asserted as a path list; a binary file round-trips byte-identical. |
| **F-9 (R75)** | An artifact carrying an ERROR finding comes out `SKIPPED` with a reason naming the rule, is not written, and the run exits `INCOMPLETE = 6`. `--force` installs it anyway, asserted on the file. A WARNING-only artifact installs normally, which is the control. |
| **V11** | A symlinked artifact root produces a **WARNING on `AssembledLibrary.findings`** and is named and skipped in the plan. The run still applies every other artifact — refusal is per artifact (R53) — and exits `INCOMPLETE = 6`, asserted on the integer, so a script can tell it from a clean run (R57). Neither the link nor its destination is written, asserted on both. |

**Cross-cutting.** No test writes to `~/.claude/`. Asserted by content hash, never mtime (L37).

## 9. Verification

**The gate** — unchanged, one command, run whole:

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

**Baseline at open: `437 passed`, 3 contracts kept, exit 0, at commit `4167c44`** (initiative 01's
close, re-run by the delivery lead).

**Domain purity traps, named because T-12 meets them first.** `tests/domain/test_purity.py` holds
`EXPECTED_MODULES` — a new `domain/` module not listed there fails the suite — and `FORBIDDEN_ROOTS`,
which bars `pathlib`, `os`, `io` and `time` from `domain/`. **L13 and L18 are pasted verbatim into T-12's dispatch. L21 — a committed symlink fixture must point at a real file, or `ruff` exits 2 before any rule runs — goes to T-14 and T-20**, the two tasks that commit one; T-12 writes no fixture.

**Mutation checks** — the assertion that must fail is named before the run, with a surviving control.

| Task | Mutation | Must fail | Must stay green |
|---|---|---|---|
| T-12 | Collapse `MANIFEST_REPAIR` into `UNCHANGED` | the manifest-stale row, **by verdict value** | every other row |
| T-13 | Return an empty manifest for a corrupt file | the corrupt-manifest test | the absent-manifest test — absent is not corrupt |
| T-14 | Add a named exclusion for `synced/` — what R44 forbids | the foreign-tree test, **at repository level** | the loose-foreign-file test, so the mutation cannot pass by making *nothing* foreign appear. **Not** the domain-level verdict test: it cannot redden under a repository mutation, so it is not a control |
| T-14 | Report `is_symlink=False` for every entry | the test driven off the committed symlink, **asserting the flag true** | an ordinary file in the same scan asserting it false — without the pair, "always False" and "correct for ordinary files" are indistinguishable |
| T-15 | Put `PlanInstall` in `application/read/` | no test fails, and that is the finding — **assert the module path**, because `mcp-is-read-only` stays green either way | `lint-imports`, which cannot see this |
| T-16 | Write the manifest **after** the files instead of before | the manifest-exists-before-first-write test | the happy-path apply test, which must still leave a correct manifest |
| T-16 | Skip the backup when the plan has **more than one** entry | the backup-exists test, whose plan has two | the refuse-without-backup test, whose plan has one — so the mutation cannot take its subject away |
| T-16 | Write the conflicted artifact along with the safe ones | the mixed-plan test, **on the conflicted file's bytes** | the all-safe run, which must still write |
| T-17 | Release the lock before the write instead of after | the second-apply test | the single-apply test |
| T-18 | Have uninstall remove the whole artifact directory | the foreign-file-survives test | uninstall's own removal test |
| T-19 | Have `clean --foreign` act before listing | the list-before-acting test | the nothing-manifest-known test |
| T-20 | Follow the symlink instead of refusing | the destination-untouched test | the warning test |
| T-20 | Drop the V11 finding from `AssembledLibrary.findings` | the warning test **at repository level** — the half that went unwired last time | the refusal test |
| T-18 | Have rollback restore only the first path it recorded | the rollback hash-set test, **per file** | uninstall's own test, which does not use the backup |
| T-21 | Have `--resolve target` overwrite instead of repairing the manifest | the target-byte-identical test | the `--resolve library` test |
| T-22 | Return exit 0 when the plan is incomplete | the exit-status test, **on the integer**, driven through Typer's runner | the complete-run test, which must still exit 0 |
| T-22 | Install into target A while target B's manifest is present | the isolation test, on B's manifest bytes | A's own install test |

**Positive controls.** Every assertion of absence carries a sibling proving it can fail.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| A bug here **destroys the user's working harness** — the first initiative that writes outside the repo | Backup before any write, refused apply if the backup cannot be taken, all-or-nothing per invocation, and `~/.claude/` never used as a test target |
| "Install worked" verified against stale state | R31's incident. Acceptance asserts on file content hashes, never on a command's own report |
| A verdict test that passes for the wrong reason | 01's V6 shipped unwired for exactly this. T-14's mutation sits **above** the fake |
| `~/.claude` moves under us mid-run | The sync bucket rewrites itself (L37). The scan is a snapshot; a target changing mid-apply is a stated limitation, not a silent one |
| The conflict path is the least-exercised and the most dangerous | It is the one verdict with two mutation rows |

## 11. Next

Closing this unblocks **03-http-api**, which renders C-9 and C-10 as a drift view. It also gives
initiative 01's F-5 its real-content proof as a side effect of P-2, and retires R34, R38 and R39.

---

## 12. Disputed reviewer findings

| Finding | Position |
|---|---|
| Second cold read, B-1a — *"an installed file the user deleted (`lib=X, man=X, tgt=None`) → **impossible → raise**"* | **Partly disputed.** That triple is `✓ ✗ ✗`, which spec §8.1 defines as `LOCAL_EDIT`, not as impossible; the example is wrong. **The finding itself is right and is fixed:** presence was encoded as "not equal", so a library artifact dropped while manifest and target agreed came out `UPDATE` rather than `PRUNE`. R55 resolves presence before equality and enumerates all five presence cases. Recorded rather than silently corrected, because a reviewer's example being wrong does not make its finding wrong, and the distinction is worth keeping visible. |
