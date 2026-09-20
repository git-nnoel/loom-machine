# Harness Library — Design

**Date:** 2026-08-28
**Status:** Draft, pending review
**Mode:** Idea (this conversation) + Code (direct reads of `~/.claude/` and `/DATA/temp2/`)

Claims carry provenance tags. `[OBS]` = stated by the user, or read directly from disk this session.
`[DER]` = derived from something observed. `[INF]` = a reasoned default, not confirmed.
`[GAP]` = not established; do not invent. An untagged claim is ordinary prose, not an assertion of fact.

---

## 1. Summary

A local-first library that holds the skills and agents you author, presents them in a browsable
web UI, and installs them into `~/.claude/` (or any other harness target) reversibly. A read-only
MCP server exposes the same content to any LLM session, including clients that have no concept of
skills.

The library is the source of truth. Installed copies are derived and disposable. `[OBS]`

### The problem, concretely

The current workflow is a manual `cp -a` between directories. Observed consequences this session,
all from real files: `[OBS]`

- Two skills (`delivery-lead`, `solution-designer`) existed as directories with an empty
  `references/` and **no `SKILL.md`**. They silently never loaded. Nothing reported this.
- `frontend-ctg-system-pattern/SKILL.md` documented its own install path as
  `~/.claude/skills/frontend-system-pattern/` — a different skill's directory.
- The older `backend-system-architecture` cited reference files into a directory that was empty.
- A `cp -a` replacement destroyed `~/.claude/agents/.backend-developer-specialist.md.swp`. It
  survived only because a manual backup was taken first.
- The same copy propagated an unrelated `node_modules/` tree (containing squatted placeholder
  `claude` / `claude-code` npm packages) into the agents directory, where it had no purpose.

Each of these is a class of failure the design closes, not an incident to be more careful about.

---

## 2. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Library is canonical.** `~/.claude/**` is an install target, derived and overwritable. | One source of truth; no two-way sync, no conflict-resolution UI in the common path. `[OBS]` |
| D2 | **Local-first; git distributes.** MCP over stdio. No network service, no auth, no uptime. | Other machines are clones that pull. Removes TLS, authn/authz, and hosting from scope entirely. `[OBS]` |
| D3 | **Skills and agents now; artifact model is type-extensible.** | YAGNI on types, not on shape. Commands, hooks, and output styles register later without a data migration. `[OBS]` |
| D4 | **Local web UI + CLI.** | Sorting, navigating, comparing and downloading want a real interface; the CLI keeps it scriptable and is the complete surface. `[OBS]` |
| D5 | **Python (FastAPI) + React/TypeScript.** | `backend-system-architecture` (Mode A, Clean Architecture) and `frontend-system-pattern` (Mode A, SPA-layered) both govern; the existing specialist agents can build it. `[OBS]` |
| D6 | **MCP is read-only.** Four tools: list, search, get artifact, get reference. | A session can consume the library but cannot write to canon. Enforced structurally — see §7.3. `[OBS]` |
| D7 | **Filesystem-native store; no database.** | The library tree *is* the data. Git diffs are real content diffs, `$EDITOR` still works, and install is a copy because layout already matches the target. `[OBS]` |
| D8 | **Separate processes:** `hl serve` (web) and `hl mcp` (stdio, client-spawned). | stdio MCP owns stdout exclusively; a web log line in the same process corrupts the JSON-RPC stream. `[DER]` |

---

## 3. Data model

### 3.1 Identity

An artifact is addressed by `<type>/<name>`: `skill/delivery-lead`,
`agent/backend-developer-specialist`. The name is the directory name or the filename stem, so
identity is derivable from the tree. There is no stored id that can drift from the filesystem. `[INF]`

### 3.2 Entity

Domain layer. No filesystem access, no framework imports.

```
ArtifactFile
  path           str             relative to the artifact root
  sha256         str             this file's own digest
  size           int             bytes
  is_text        bool            searchable and diffable, or opaque

Artifact
  id             str             "skill/delivery-lead"
  type           ArtifactType    skill | agent
  name           str             slug; matches directory or file stem
  title          str | None      first H1 in the entry file
  description    str             frontmatter `description`
  frontmatter    dict            the parsed block, kept for display
  kind           directory | file
  files          tuple[ArtifactFile, ...]
  content_hash   str             sha256 over sorted (path, bytes)
  updated_at     datetime        last commit touching these paths; mtime fallback
  is_dirty       bool            uncommitted changes present
  tags           tuple[str, ...]               from library.yaml
  collections    tuple[str, ...]               from library.yaml
  superseded_by  str | None                    artifact id
  findings       tuple[ValidationFinding, ...]

ValidationFinding
  code           ValidationCode  closed enum: V1..V7
  severity       ERROR | WARNING
  message        str
  path           str | None      the file it concerns, when applicable
```

**Per-file hashes are load-bearing, not a convenience.** `[DER]` §8.1 judges install **per path** on
three hashes. A whole-artifact `content_hash` alone forces Plan 2 to re-implement scanning and hashing
on a second code path, and the two would drift.

**`updated_at` derives from git, not mtime.** `[OBS: ruling R5]` D2 makes `git clone` the distribution
mechanism, and a clone rewrites every mtime to clone time — so mtime-based sorting is meaningless on
every machine except the one that authored the artifact. The value is the last commit touching the
artifact's paths, falling back to max mtime when the library is not a repository or the artifact has
uncommitted changes, in which case `is_dirty` is set.

**Findings carry severity.** `[DER]` §4 grades V6 a warning, so validity cannot be a single boolean: a
stray `.swp` file must not make an artifact uninstallable. `is_valid` means "no finding of severity
ERROR", and Plan 2 refuses to install only on ERROR.

**`superseded_by` is first-class, not a tag.** `[OBS]` Two of the six current skills are already
redirect stubs — `developers-orchestration` → `delivery-lead` and `frontend-ctg-system-pattern` →
`frontend-system-pattern`. Both must stay installed so that plans and records citing the old names
still resolve, and both say so in their own body text. A tag would be advisory; a typed field lets
the list view demote them, the search rank them below their successors, and `hl validate` verify
the target exists.

### 3.3 Type registry

The single place a new artifact type is added. `[INF]`

```
skill:  kind=directory  entry=SKILL.md     target=~/.claude/skills/<name>/
agent:  kind=file       entry=<name>.md    target=~/.claude/agents/<name>.md

both:   required frontmatter keys: name, description
```

### 3.4 `library.yaml`

Holds only what the artifact files cannot express. Everything else is parsed from the artifacts,
so there is no second copy to fall out of date. `[INF]`

```yaml
artifacts:
  skill/delivery-lead:
    tags: [orchestration, process]
    collections: [ctg-delivery]
  skill/developers-orchestration:
    superseded_by: skill/delivery-lead
  skill/frontend-ctg-system-pattern:
    superseded_by: skill/frontend-system-pattern

collections:
  ctg-delivery:
    title: CTG delivery system
    description: The full spec-to-delivery chain.
    members:
      - skill/solution-designer
      - skill/delivery-lead
      - skill/backend-system-architecture
      - skill/frontend-system-pattern
      - agent/backend-developer-specialist
      - agent/frontend-developer-specialist
```

An entry in `library.yaml` for an artifact that does not exist on disk is a validation error, not a
silent no-op. `[INF]`

### 3.5 Repository layout

```
harness-library/
  skills/<name>/SKILL.md, references/*.md, <assets>
  agents/<name>.md
  library.yaml
  docs/specs/
  backend/  frontend/
```

The `skills/` and `agents/` directories mirror the install layout exactly. `[DER from D7]`

---

## 4. Validation

Every rule below exists because the corresponding failure was observed on disk this session. `[OBS]`

| Rule | Failure caught |
|---|---|
| `V1` A skill directory must contain `SKILL.md` | `delivery-lead/`, `solution-designer/` — directories with only an empty `references/`; never loaded, never reported |
| `V2` Frontmatter `name` must equal directory/file name | `frontend-ctg-system-pattern` documenting its own path as another skill's directory |
| `V3` Every `references/…` path cited in body text must exist **under that artifact**. **Directory-kind artifacts only** — a single-file artifact cannot own a `references/` folder, so a citation in one is prose about another artifact's files (DEC-9 / R32) | The old `backend-system-architecture`, citing into an empty `references/`. The scope clause was added after the rule fired 15 times on the real library with **zero** true positives |
| `V4` `superseded_by` must resolve to an existing artifact | A redirect pointing at a skill that was since renamed again |
| `V5` Required frontmatter keys present and non-empty | A skill that loads but cannot be matched by description |
| `V6` Files under an artifact root that are not declared content are reported as extraneous | The `.swp` file; the `node_modules/` tree; any symlink (ruling R6) |
| `V7` Every `library.yaml` entry, and every `collections[].members` id, must resolve to an artifact on disk | A rename that updates the tree but not the metadata, leaving a collection quietly one member short |
| `V8` Two artifacts of one type whose names differ only by case | A case-insensitive install target silently merging two skills into one |
| `V9` A duplicate key in `library.yaml` | Last-wins silently discarding the first block's tags |
| `V10` The entry document's frontmatter does not parse | A single unquoted colon making a working skill report every required key as missing |

`V1`–`V5`, `V7`, `V8`, `V9` and `V10` are `ERROR`. `V6` is `WARNING` — it reports, never deletes, and never blocks install.

**V10 suppresses V2, V3 and V5.** `[OBS]` When the frontmatter block did not parse, nothing is known
about what it declares — so reporting a missing key, a name disagreement, or a lost `superseded_by`
exemption are all claims the tool cannot support. V3 is included because its exemption depends on
`superseded_by`, which comes from frontmatter when no `library.yaml` declares it: without the
suppression, one unquoted colon in a redirect stub floods V3 with exactly the findings the exemption
exists to prevent, burying the one true cause among them.

**V3 exempts artifacts with `superseded_by` set.** `[OBS]` A redirect stub's entire purpose is to say
where its content went, which means citing the successor's reference paths as prose. Verified against
the real library: the rule as originally written produces **exactly seven false positives** — six from
`developers-orchestration`'s "Was → Now" table and one from `frontend-ctg-system-pattern` citing
`references/brand-ctg.md`. Both artifacts are behaving exactly as intended. This is the irony §3.2 was
written to avoid: supersession is first-class *so that* rules can treat these artifacts differently.

An invalid artifact is **shown in the list with its reasons**, never omitted. `[INF]` Omission is how
the current failure mode hides: the two broken skills were invisible rather than flagged.

---

## 5. Architecture

Clean Architecture, per `backend-system-architecture` Mode A. Dependencies point inward.

```
domain/          Artifact, ArtifactType, ValidationError, InstallPlan, PlanAction
                 ArtifactRepository (protocol), TargetRepository (protocol)
                 pure; no I/O, no framework

application/
  read/          ListArtifacts, GetArtifact, GetArtifactFile, SearchArtifacts,
                 ValidateLibrary, DiffAgainstTarget, ExportArtifact
  write/         CreateArtifact, UpdateArtifactFile, DeleteArtifact,
                 PlanInstall, ApplyInstall, Rollback, CleanForeign

infrastructure/  FilesystemArtifactRepository, FilesystemTargetRepository,
                 LibraryYamlReader, BackupStore, ManifestStore, GitProvenance

api/             FastAPI routers, DTOs, dependency providers
cli/             Typer commands
mcp/             stdio MCP server  — imports application/read ONLY
```

No use-case logic lives in an adapter. `api/`, `cli/`, and `mcp/` are three entry points over one
application layer. `[INF]`

---

## 6. Data flow

```
                    ┌──────────────────────────────────────┐
   filesystem  ───► │ FilesystemArtifactRepository         │
   library.yaml ──► │  parse frontmatter, hash, merge meta │
                    └───────────────┬──────────────────────┘
                                    │  domain.Artifact
                    ┌───────────────▼──────────────────────┐
                    │ application/read  +  application/write│
                    └───┬───────────────┬──────────────┬────┘
                        │               │              │
                  api/ (FastAPI)   cli/ (Typer)   mcp/ (stdio)
                        │                              │
                  React SPA                     any MCP client
```

Install reads a second repository — the **target** (`~/.claude/`) — and the **manifest**, then
produces an `InstallPlan` (§8). Nothing writes to a target without a plan. `[INF]`

---

## 7. Consumers

### 7.1 CLI (Typer)

The complete surface. The UI does nothing the CLI cannot. `[OBS]`

```
hl list [--type T] [--tag T] [--collection C] [--invalid] [--sort name|updated|size]
hl show <id> [--files] [--refs]
hl search <query>
hl new <type> <name>
hl edit <id>                       → $EDITOR
hl validate
hl export <id|--collection C> [-o PATH]
hl install [<id>… | --collection C | --all] [--target PATH] [--dry-run] [--prune]
hl diff [--target PATH]
hl uninstall <id> [--target PATH]
hl rollback [--to TIMESTAMP]
hl clean --foreign [--target PATH]
hl serve [--port 8760] [--open]
hl mcp                             → stdio; spawned by the client, not by you
```

### 7.2 HTTP API + React SPA

FastAPI serves JSON; the SPA consumes that same API, so there is no UI-only capability. `[INF]`

| Route | Screen |
|---|---|
| `/` | List: name, type, tags, file count, updated, validity. Filter and sort. Superseded artifacts demoted. |
| `/a/:type/:name` | Detail: file tree, rendered markdown, references pane, frontmatter, validity reasons |
| `/a/:type/:name/edit` | In-page editor (CodeMirror), save → `PUT` |
| `/collections` | Collections and their members |
| `/install` | Plan grouped by verdict; conflicts expanded; Apply gated on resolution |

Download: `GET /api/artifacts/{id}/export` → zip. `[OBS]`

Frontend follows `frontend-system-pattern` Mode A: Vite + React Router, React Query for server
state, one typed HTTP client, Zod-validated responses, no global-state library. `[DER from D5]`

### 7.3 MCP server (stdio, read-only)

```
list_artifacts(type?, tag?)   → id, name, type, description, tags, superseded_by
search_artifacts(query)       → matches: id, path, line number, the line,
                                 one line of context either side; capped at
                                 200 matches with `truncated: bool`; entry file
                                 and .md references only. Each unsearched file
                                 is reported in `skipped`, carrying a reason
                                 that is *not a markdown reference* — never
                                 "binary": the bundled 184 KB HTML asset is
                                 valid UTF-8 and is still not searched (R4, R25)
get_artifact(id)              → entry file text + file listing
get_reference(id, path)       → one reference file
```

`get_reference` is a first-class tool rather than a mode of `get_artifact` because the skills are
reference-heavy: `backend-system-architecture` is 718 lines *before* its seven references. A session
that needs one reference should not pay for the whole skill. `[DER]` `[OBS on line count]`

**The read-only guarantee is structural.** `mcp/` imports from `application/read` only, and an
`import-linter` contract fails CI if that is ever violated. A write tool cannot be added by
accident. `[INF]`

---

## 8. Install, backup, drift

### 8.1 Plan → review → apply

The plan is always computed, `--dry-run` only stops before apply. Each path is judged on three
hashes: library, manifest (what was last installed), and target (what is on disk now). `[INF]`

Write `L` for the library hash, `M` for the manifest hash, `T` for the target hash. The three
columns are pairwise equality, so a row is read as "library equals manifest? manifest equals
target? library equals target?".

| L=M | M=T | L=T | Verdict | Behaviour |
|:--:|:--:|:--:|---|---|
| ✓ | ✓ | ✓ | `UNCHANGED` | skip |
| ✗ | ✓ | ✗ | `UPDATE` | target is what we installed; library moved ahead. Write. |
| ✓ | ✗ | ✗ | `LOCAL-EDIT` | library and manifest agree; target edited out-of-band. Prompt. |
| ✗ | ✗ | ✓ | `UNCHANGED` + manifest repair | library and target already agree; only the manifest is stale. Rewrite the manifest, touch no files. |
| ✗ | ✗ | ✗ | `CONFLICT` | both moved independently; requires explicit resolution |
| ✓ | ✓ | ✗ | *impossible* | violates transitivity — raise, never guess |
| ✓ | ✗ | ✓ | *impossible* | as above |
| ✗ | ✓ | ✓ | *impossible* | as above |

The `UNCHANGED + manifest repair` row is the state left behind when the same content arrives by
another path — a `git pull` on a second machine that already had the files, or a manual copy like
the one performed by hand this session. Treating it as `CONFLICT` would demand a decision where
there is no actual disagreement. `[INF]`

Presence and absence are judged separately from content:

| Verdict | Condition | Behaviour |
|---|---|---|
| `CREATE` | in library, absent from manifest and target | write |
| `PRUNE` | in manifest, gone from library | deleted only with `--prune` |
| `FOREIGN` | in target, unknown to library and manifest | never touched; reported |

`LOCAL-EDIT` and `CONFLICT` are precisely the states a manual `cp -a` cannot see. `[DER]`

### 8.2 Foreign files are never touched

The rule that changes the observed outcome. `[DER from §1]`

```
$ hl install --all --dry-run
  skill/backend-system-architecture   UPDATE   8 files
  skill/delivery-lead                 CREATE   7 files
  skill/developers-orchestration      UPDATE   1 file    (→ redirect stub)
  agent/backend-developer-specialist  UPDATE   1 file

  FOREIGN, left in place (2):
    ~/.claude/agents/.backend-developer-specialist.md.swp
    ~/.claude/agents/node_modules/   (+ package.json, package-lock.json)
```

The swap file survives. The `node_modules` cruft is reported rather than silently carried into
canon. Removing either is a deliberate `hl clean --foreign`, which lists before it acts.

### 8.3 Backups

`~/.local/state/harness-library/backups/<timestamp>/` — outside both the library and the target, so
neither a `git clean` nor a target wipe destroys them. Only paths the plan will write are backed up.
`hl rollback [--to TIMESTAMP]` restores. `[INF]`

### 8.4 Manifest

`~/.local/state/harness-library/manifests/<sha256 of target path>.json` — outside `~/.claude/`, so
installing never adds a file the harness itself must ignore. `[INF]`

Per artifact: id, content hash, every file written with its own hash, timestamp, the backup
directory created, and **the library git SHA installed from** — so "which version is on this
machine" has an exact answer once git is distributing to a second machine. `[INF]`

### 8.5 Conflict resolution

Choose-a-side per file, plus "open both in `$EDITOR`". **No three-way merge UI.** `[OBS]` For prose
files a half-good merge tool produces plausible-looking damage; handing you both versions does not.

---

## 9. Error handling

| Condition | Behaviour |
|---|---|
| Malformed frontmatter | Artifact loads as `Invalid`, listed with the parse error. Never crashes the scan. |
| `library.yaml` unparseable | Hard failure with line number. Metadata is not guessable. `[INF]` |
| `library.yaml` references a missing artifact | Validation error, not a silent skip. |
| Target path unwritable | Plan computed and shown; apply refuses before writing anything. |
| Apply fails partway | Restore from the backup taken in the same operation, then report. Installs are all-or-nothing per invocation. `[INF]` |
| Backup cannot be written | Apply refuses. No unbacked write, ever. `[INF]` |
| MCP: unknown artifact id | MCP error result, not an exception across the pipe. |
| Web: artifact edited on disk while open in editor | Save is rejected on hash mismatch; the UI offers reload or overwrite. `[INF]` |

---

## 10. Testing

Per `backend-system-architecture` Mode A: use-case unit tests against hand-written fakes; the
filesystem is real only in integration tests, against `tmp_path`.

**Domain (pure, no I/O).** Hash stability across reorderings; `Artifact` construction; the three-way
verdict function as a table test over all eight hash combinations, including the impossible ones,
which must raise rather than guess. `[INF]`

**Application (fakes).** `FakeArtifactRepository` and `FakeTargetRepository` in-memory. Every use
case tested without touching disk. `PlanInstall` is the highest-value target: each verdict, and
`--prune` and `--dry-run` as independent axes.

**Infrastructure (real filesystem, `tmp_path`).** Fixture libraries built to reproduce each observed
failure: a skill directory with no `SKILL.md`; a frontmatter name that disagrees with its directory;
a body citing a missing reference; a stray `.swp`; a nested `node_modules`. These are regression
tests for §1, and they are the ones that must never be deleted. `[DER]`

**Install safety — the tests that matter most.** `[INF]`
- Apply with an injected mid-write failure leaves the target byte-identical to its pre-apply state.
- Apply never writes a path absent from the plan. Asserted by a write-recording target fake.
- A `FOREIGN` path is byte-identical after apply. Asserted directly on the `.swp` fixture.
- Rollback restores a target to its exact prior hash set.
- Refusal when a backup cannot be written — simulated by a read-only backup directory.

**Adapters.** FastAPI via `TestClient` against fake use cases. CLI via Typer's runner. MCP by
driving the stdio server with real JSON-RPC frames and asserting the tool list is exactly the four
read tools. The `import-linter` contract (§7.3) runs in CI as a test, not as a lint step, so a
violation fails the suite. `[INF]`

**Frontend.** Per `frontend-system-pattern`: contract mocks validated against the same Zod schemas
the client uses, so a backend shape change breaks the mock rather than passing green.

**Not covered by tests, deliberately:** the rendered appearance of the UI, and MCP behaviour inside
a real Claude Code session. Both are verified by hand once, and recorded. `[GAP]`

---

## 11. Non-goals

- Multi-user, auth, or a hosted service. Closed by D2.
- Two-way sync from `~/.claude/` back to the library. Closed by D1. Out-of-band edits are *detected*
  (`LOCAL-EDIT`) and surfaced, never auto-merged.
- Write access via MCP. Closed by D6.
- A three-way merge UI. §8.5.
- Publishing to a public registry or marketplace. `[GAP]` — not discussed.
- Editing `settings.json` / hooks / MCP configs. Deferred by D3; these need merge semantics rather
  than file copy, which is a materially different install story.

---

## 12. Open questions

1. **Additional targets.** The design allows `--target PATH` for project-level `.claude/`
   directories. Is that needed at v1, or is `~/.claude/` the only target? `[GAP]`
2. **Plugin export.** Claude Code's plugin format bundles skills and agents. Should a collection
   export as an installable plugin rather than a plain zip? This affects the `ExportArtifact`
   shape. `[GAP]`
3. **Non-Claude harness targets.** D2 says "other LLM sessions through different systems". MCP
   covers reading. Is *installing* into a non-Claude harness (different directory conventions) in
   scope, or does MCP fully cover that case? `[GAP]`
7. ~~**Symlink policy.**~~ **RESOLVED 2026-08-28 — ruling R6.** Skipped, reported as a V6
   warning, excluded from the hash, never installed. `[OBS]`

8. ~~**File mode in the content hash.**~~ **RESOLVED 2026-08-28 — ruling R9.** Excluded; Plan 2
   normalises on install. `[OBS]`

4. **Editing references in the web UI.** The editor is specced for any file in an artifact. Confirm
   that includes `references/*.md`, not just the entry file. `[INF: assumed yes]`
5. ~~**Search depth.**~~ **RESOLVED 2026-08-28 — ruling R4.** Entry file plus every `.md`
   reference; binary never searched and each skip reported. `[OBS]`
6. ~~**Scan performance.**~~ **RESOLVED 2026-09-01 — measured at T-9.** The scan is **17 ms** over the
   real library. The estimate was right about the scan and wrong about what a user waits for: importing
   the CLI cost **1811 ms**, of which 1277 ms was an MCP SDK no read command touches. Fixed in T-10 —
   now 534 ms. No cache is warranted. `[OBS]`
   ~~Estimated imperceptible at ~750KB across eight artifacts, but **unmeasured**.~~ Time it once the store exists; if it registers, add
   an mtime-keyed cache — not a merged process. `[INF]`

---

## 13. Next step

`superpowers:writing-plans` to produce the implementation plan. This document does not contain
phases, task breakdowns, or a delivery order — those belong to `delivery-lead` and the
implementation plan, not to the spec.


---

## 14. Amendments

Corrections to this document after its first draft. Each names what changed the answer.

| Date | Section | Change | Cause |
|---|---|---|---|
| 2026-08-28 | §3.2 | Added `ArtifactFile` with per-file `sha256`; `files` now carries it | Backend review S4 — §8.1 judges install per path, so per-file digests must exist or Plan 2 builds a second scanner |
| 2026-08-28 | §3.2 | `updated_at` redefined from max mtime to last-commit date, with `is_dirty` | Backend review S1 — a `git clone` rewrites every mtime, and D2 makes clones the normal case. Ruling R5 |
| 2026-08-28 | §3.2 | `validity` sum type replaced by `findings` carrying `ValidationFinding(code, severity, message, path)` | Backend review S2 — §4 grades V6 a warning, so a stray `.swp` would otherwise block install |
| 2026-08-28 | §3.2 | Added `frontmatter` to the entity | Backend review — Plan 3's detail screen renders it; without it the SPA re-parses |
| 2026-08-28 | §4 | V3 now exempts artifacts with `superseded_by` set | Backend review S3 — verified: seven false positives on the two redirect stubs, both behaving correctly |
| 2026-08-28 | §4 | Added V7 for unresolvable `library.yaml` and collection-member ids | Backend review S7 — §3.4 mandated this outcome but §4 had no rule for it |
| 2026-08-28 | §4 | Severities stated explicitly per rule | Backend review S2 |
| 2026-08-28 | §7.3 | `search_artifacts` result shape, 200-match cap, `truncated`, `skipped_binary` | Backend review S5 — "context" was undefined and an uncapped result crosses a pipe into a model's context window |
| 2026-08-28 | §12 | Questions 5 (search depth), symlinks and file mode struck as resolved | Rulings R4, R6, R9 |

| 2026-09-20 | §4 | V8, V9 and V10 added to the register; severities stated | Rulings R19, R20, R33 — all three shipped in initiative 01 and the spec still listed V1–V7 |
| 2026-09-20 | §4 | V3 scoped to directory-kind artifacts | DEC-9 / R32 — the rule fired 15 times on the real library with **zero** true positives; references belong to the skill that owns them |
| 2026-09-20 | §4 | V10 suppresses V2, V3 and V5 | R33, widened to V3 on 2026-09-20 — the exemption depends on frontmatter, so one unquoted colon would otherwise flood V3 |
| 2026-09-20 | §7.3 | `skipped_binary` replaced by `skipped` with a reason that is never "binary" | R25 / R27 — the 184 KB HTML asset is valid UTF-8 and still unsearched; the reason is *not a markdown reference* |
| 2026-09-20 | §12.6 | Scan performance struck as resolved; real numbers recorded | Measured at T-9: 17 ms scan against a 1811 ms import, now 534 ms |
| 2026-09-20 | — | These five amendments were owed from 2026-08-28 and were found missing by a `phase-reviewer` cold read, not by the delivery lead | The instruction tree had moved ahead of the spec in six places while the spec remained precedence 1 |

**Not yet applied.** Review item S8 — the import-linter contract drafted in Plan 1 does not express
§7.3's guarantee and separately permits `infrastructure → application`. §7.3's *statement* is correct;
the defect is in the plan's translation of it, and is fixed there rather than here.
