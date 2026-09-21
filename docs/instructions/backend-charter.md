# Backend charter — Harness Library

**Architecture:** Clean Architecture (Mode A)
**Stack:** Python 3.12+ · Typer · Pydantic · FastAPI (from initiative 03)
**Owner:** delivery lead · **Last updated:** 2026-08-28

Standing conventions for every backend dispatch on this project. Read in full before your first edit.
Where this charter and `backend-system-architecture` disagree, §3 names the deviation and its reason;
everything not listed there follows the skill.

## 1. Architecture mode

Clean Architecture, Mode A. Four inward-facing layers. The default only applies when a charter is
silent — this one is not silent, so do not infer a mode from the code's shape.

## 2. Layer map and the import contract

```
cli/  mcp/  api/        adapters — no use-case logic, ever
      application/      read/ and write/, split as packages
      domain/           entities, protocols, pure rules — imports nothing from the project
      infrastructure/   implements domain protocols
```

`import-linter` enforces direction and runs **as a test**, not as a lint step, so a violation fails the
suite. Three contracts: layer direction, `mcp/` may not import `application.write`, and `domain/` may
not import any other layer.

**The `layers` list is ordered high-to-low and is a known trap** — an order that reads as correct can
permit the exact violation it appears to forbid. Prove each contract by introducing a violating import
and watching `lint-imports` fail. A contract nobody has seen fail is a contract that does not run.

## 3. Declared deviations from `backend-system-architecture`

| Deviation | Reason |
|---|---|
| Use-case **functions**, not classes | Every read use case is one pure call over a repository; a class per operation would be a constructor and a `__call__` around a function. Revisit if one grows state. |
| Frozen dataclasses in `domain/`, not Pydantic | `domain/` must import nothing. Pydantic is used at the adapter boundary, where validation belongs. |
| Shared presentation DTOs in `application/read/dtos.py`, not `api/dtos/` | `mcp/` must not import `api/`. One serialisation of an entity, reachable from every adapter. |

## 4. Stack rulings

Approved set: `typer`, `pydantic`, `pydantic-settings`, `python-frontmatter`, `pyyaml`, `mcp`,
`structlog`. Dev: `pytest`, `ruff`, `mypy`, `import-linter`.

- **`pyyaml` is on the skill's NOT-allowed list and is used here anyway** — ruling R1. The prohibition
  targets YAML *configuration*; `library.yaml` is user-authored *data* mandated by spec §3.4, and
  `python-frontmatter` vendors PyYAML regardless. Application configuration uses `pydantic-settings`.
- **`pydantic-settings`** — ruling R2, house baseline, single environment reader.
- **`structlog`** — ruling R3, **stderr only**, see §11.

Nothing is added, removed or version-bumped without a ruling recorded in the initiative record. If a
task appears to need one, stop and report.

## 5. The gate

One command. Run whole, every time. A path-scoped subset is not the gate, and a run that stops at
type-check is not green.

```
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

## 6. Frozen contracts

C-1 … C-8, defined in the initiative plan §6. Changing one is a **plan-level** decision, not a
task-level one, because initiatives 02–04 build against them. A task that needs a contract changed
stops and reports.

## 7. Identity, hashing and filesystem policy

- Identity is `<type>/<name>`, derived from the tree. No stored ids.
- `content_hash` covers sorted `(relative path, bytes)`. It **excludes** file mode (R9), mtime, and any
  skipped path. Per-file `sha256` exists on every `ArtifactFile` — initiative 02 judges install per path.
- **Symlinks are skipped and reported** as a V6 warning (R6). Never followed, never hashed, never
  installed. A link resolving outside the artifact root is how a copy writes outside its target.
- **Case:** artifact names are compared case-sensitively; two artifacts whose names differ only by case
  are a V-error, not a silent overwrite, because the target filesystem may disagree with this one.
- **Text vs binary:** `is_text` is decided per file and drives searchability. Binary is stored, hashed,
  exported and installed — never searched or diffed.
- **Scan snapshot:** one `list_all()` is a point-in-time snapshot. A file changing mid-scan yields a
  torn read, which is acceptable for a read-only single-user tool; initiative 02 revisits this because
  it writes.

## 8. Validation rule register

| Code | Severity | Closes |
|---|---|---|
| V1 | ERROR | A skill directory with no `SKILL.md` — observed twice; both loaded silently as nothing |
| V2 | ERROR | Frontmatter `name` disagreeing with the directory name |
| V3 | ERROR | A cited `references/…` path that the artifact does not contain. **Applies only to DIRECTORY-kind artifacts** (ruling R32): references belong to the skill that owns them, and a single-file artifact can never own a `references/` folder, so a citation in one is prose about another artifact's files. **Exempt when `superseded_by` is set** — a redirect stub cites its successor's paths as prose |
| V4 | ERROR | `superseded_by` that does not resolve |
| V5 | ERROR | Missing or empty required frontmatter key |
| V6 | **WARNING** | Extraneous file under an artifact root — swap files, vendor trees, symlinks. Reported, never deleted, never blocks install |
| V7 | ERROR | A `library.yaml` entry or `collections[].members` id that resolves to nothing |
| V8 | ERROR | Two artifacts of one type whose names differ only by case. §7 promised this rule and §8 did not define it; a specialist correctly refused to invent a code rather than emit one outside the contract. Decided at the library level, like V4 and V7 |
| V9 | ERROR | A duplicate key in `library.yaml` — the same artifact id or collection key declared twice. Last-wins silently discards the first block's tags, which is the precise silent-data-loss failure this product exists to eliminate |
| V10 | ERROR | The entry document's frontmatter does not parse. Reports the parser's own message with line and column, and **suppresses the V2, V3 and V5 cascade** behind it (V3 added by ruling R37, built in T-11) — a file whose frontmatter failed to load otherwise reports every required key as missing, which is false and unactionable (R33). **V3 is included** because its `superseded_by` exemption reads frontmatter when no `library.yaml` declares supersession: without the suppression one unquoted colon in a redirect stub floods V3 with exactly the findings the exemption prevents (R37) |

| V11 | **WARNING** | An artifact root that is a symlink: not followed, not scanned, and therefore silently absent from the library. Reported so the omission is visible. Install additionally **refuses** to write that artifact (R46). **Pending initiative 02** |

New rules are added to this table first. `is_valid` means **no finding of severity ERROR**.

## 9. Error taxonomy

One base exception, stable string codes, never an English string as the branchable value. Codes map to
CLI exit codes now and to HTTP status codes in initiative 03. **A code is added to the contract before
it is emitted.**

## 10. Testing policy

- `domain/` and `application/` — hand-written fakes, zero I/O. `infrastructure/` — real files under
  `tmp_path`. Adapters — Typer's runner and real JSON-RPC frames.
- **What each layer is blind to must be stated**, and a fake cannot prove a real filesystem behaviour.
- **Every absence assertion carries a positive control** — a test asserting "X does not appear" is
  worthless unless a sibling proves the assertion can fail.
- **Mutation check per task**, with the assertion that must fail **named before the run**.
- The fixture set reproduces every failure in spec §1. **Those fixtures are never deleted** — they are
  the regression suite for the reason this product exists.

## 11. Logging and stdout discipline

Structured logging to **stderr**, always. One line per MCP tool call.

**Nothing may write to stdout in the `hl mcp` process** — not a log line, not a warning, not Typer's own
error output on a bad flag. stdout is the JSON-RPC channel. A single stray byte kills the client
connection and surfaces as a malformed stream with no diagnosable cause. The stdout-purity test is an
acceptance criterion, not a nicety. This is D8 turned into a mechanism instead of a promise.

## 12. Concurrency posture

**Reads:** no locking. Multiple concurrent `hl mcp` processes are safe — each holds its own snapshot.

**Writes (initiative 02, ruling R50):** a **single-writer advisory lock** — an `O_EXCL` sentinel beside
the manifest, held for the duration of an apply, released on exit, stale-broken by pid check. A second
apply against a held lock exits `LOCK_HELD = 10` without writing. **Built in T-17.**

**Every write use case takes a `WriteLock` as a required keyword-only parameter** (C-16, R82) — a
write path that simply does not take one keeps every gate green while sitting outside this section.

**Reads take no lock** (R85). `hl diff` can therefore describe a target an install is midway through
writing. Stated, not fixed: locking reads would serialise the one operation that is always safe.

**The state root is local-only** (R84). The staleness check reads the local process table, so a state
root on a shared filesystem would make it meaningless in both directions; `hostname` is recorded in
the sentinel for a human and is deliberately not part of the decision.

## 13. Configuration

One settings object is the sole reader of the environment; no other module calls `os.environ`.
Library-root precedence: `--library` flag → `$HL_LIBRARY` → current directory. Resolution **fails loudly**
on a directory that is not a library, rather than silently returning an empty list.

## 14. Decisions log

| Date | Decision |
|---|---|
| 2026-08-28 | Charter opened. Mode A. Rulings R1–R9 recorded in the initiative record. |
| 2026-09-01 | §8 gains V8 (R19), V9 (R20) and V10 (R33). V3 scoped to directory-kind artifacts (R32 / DEC-9). |
| 2026-09-20 | §8's V10 row extends the suppression to V3 (R37). Built in T-11 on 2026-09-21; the register stated the rule before the code emitted it, per §9. |
| 2026-09-21 | §8 gains V11, a symlinked artifact root (R46). **Pending initiative 02**, which owns both halves: the scan warning and the install refusal. |
| 2026-09-21 | §12's write posture decided: a single-writer advisory lock (R50), **built in T-17**. C-16, R82–R85 record the seam, the error posture, the locality assumption and the read exemption. |
