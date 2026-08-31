# Backend review — Plan 1: Store, Validation, Read Path, MCP

**Reviewer:** backend-developer-specialist
**Date:** 2026-08-31
**Under review:** `docs/plans/2026-08-28-store-and-read-path.md`
**Against:** `docs/specs/2026-08-28-harness-library-design.md` (D1–D8 treated as settled), `backend-system-architecture` Mode A + references `contracts.md`, `testing.md`, `concurrency.md`, `observability.md`, `persistence.md`, `schema-evolution.md`
**Evidence base:** the real `~/.claude/skills/` (6 skills, 632 657 bytes) and `~/.claude/agents/` (2 agents, 35 749 bytes), read this session.

---

## 0. Headline verdict

**The intent is right; the decomposition and roughly a dozen of the locked shapes are not.**

The layering instinct is sound — pure domain, filesystem-as-repository, three thin adapters over one
read surface, a structural import contract instead of a promise. Keep all of that.

Three things must change before a line is written:

1. **The `Artifact` and `ArtifactRepository` shapes will not survive Plan 2.** `files: tuple[str, ...]`
   and `read_file(...) -> str` are the two decisions that force Plan 2 to re-implement scanning and
   hashing on a second code path. Spec §8.1 judges install **per path on three hashes**; Plan 1 computes
   per-file bytes and then throws the per-file digests away. That is `contracts.md` rule 1 — "X mirrors Y"
   is intent, only a shared object is fact — and it is the most expensive mistake available here.
2. **Two rules ship non-functional and green.** V6 has no wiring that can ever populate it (§4, D-14), and
   V3 produces **seven false positives against the real library today** (§4, D-13, evidence below). The
   plan's own acceptance criterion asserts the opposite outcome.
3. **The ordering creates the rework you suspected, and it is worse than Task 5.** Tasks 4 *and* 5 both
   retro-fit Task 3's repository. The root cause is that Task 3 builds an `Artifact` from inputs it then
   discards, so everything downstream has to re-open it. One extra pure type (`RawArtifact`) removes both
   retrofits and moves ~70 % of the behaviour out of `tmp_path` tests into zero-I/O tests.

**Defect count:** 6 blocker · 14 high · 12 medium · 6 low = **38**.
**Task count:** 8 proposed → **9 recommended**, with a different cut (§2.3).
**Contracts to freeze:** 8 (§3).

The ~1 400 lines of code in the plan were, as you say, mine to write. Where I keep a shape I say so
explicitly rather than silently; those are decisions I endorse, not deference.

---

## 1. Layering

### 1.1 The verdict on the three seams you asked about

| Placement | Verdict | Why |
|---|---|---|
| Validation in `domain/` | **Right layer, wrong signature.** | The rules are pure data→data. But `validate_artifact(artifact, frontmatter, body, extraneous_files, known_ids)` takes four arguments only the repository holds, so it is a repository helper wearing a domain coat. Nothing else can call it. Plan 2 needs a pre-install validity gate and Plan 3 needs `POST /validate`; both would have to reconstruct the repository's internals. Fix in §1.2. |
| Type registry in `domain/` | **Right layer, wrong contents.** | Type identity (kind, entry-file naming, required frontmatter keys) is domain vocabulary and belongs there — one object, per `contracts.md`. But `target_template="skills/{name}/"` is Plan 2's install policy with **no consumer in Plan 1** (R18/R19), and a format string will not survive the file-vs-directory distinction Plan 2 needs. `source_dirname` and the target path are the *same fact* — spec §3.5 says the library tree mirrors the install layout exactly. Collapse both into one `directory_name: str` and let Plan 2 join it to a target root. |
| Frontmatter parsing in `infrastructure/` | **Right layer, wrong boundary.** | Wrapping `python-frontmatter` so no other layer imports it is correct. But the plan then hands the *decoded string* across the boundary, and the repository decodes with `errors="replace"` — so the text that produced `title` and `description` is not the text that was hashed. Parse from `bytes`, at the boundary, and return the decode outcome as data. |

### 1.2 The thing that is actually in the wrong place

`FilesystemArtifactRepository._build` is a god-method. It walks, reads, decodes, parses frontmatter,
regex-extracts an H1, stats mtimes, hashes, merges `library.yaml`, and (after Task 5) orchestrates
validation. Only the first three of those are I/O. The rest are pure and are the parts most worth testing,
and the plan traps all of them behind `tmp_path`.

Mode A §2.2 puts external-format → entity transformation in a mapper, and R12 (Mode A) says so
explicitly. Split at the bytes boundary:

```
infrastructure/scanner.py      I/O ONLY: walk, read bytes, stat, classify skipped paths
                               → RawArtifact  (a pure, fully-constructible value)
domain/assembly.py             PURE: RawArtifact + LibraryMetadata + known_ids → Artifact
                               (title, description, hash, size, validity — all of V1..V7)
infrastructure/repository.py   FilesystemArtifactRepository = scanner + assembly, memoised
```

`RawArtifact` is the seam. Everything interesting becomes constructible in a test literal:

```python
@dataclass(frozen=True, slots=True)
class RawArtifact:
    type: ArtifactType
    name: str
    files: Mapping[str, RawFile]        # relpath -> RawFile(sha256, size_bytes, mtime, text|None)
    entry_frontmatter: Mapping[str, object] | None   # None == parse failed
    entry_parse_error: str | None
    entry_body: str | None
    skipped: tuple[SkippedPath, ...]    # dotfiles, vendor dirs, symlinks — feeds V6
```

This is the single highest-leverage structural change in the review. It removes both retrofits (§2),
kills the `errors="replace"` inconsistency, and makes the V6 wiring impossible to forget because
`skipped` is a required constructor argument rather than something `_collect_files` silently drops.

### 1.3 Two other layer notes

- **`domain/metadata.py` is fine, but `LibraryMetadata` is a false guarantee.** `@dataclass(frozen=True)`
  with `dict` fields freezes the binding, not the contents. Use `Mapping` + `MappingProxyType`, or drop
  `frozen=True` and stop implying immutability.
- **There is nowhere for shared presentation DTOs, and Plan 3 needs one.** `mcp/server.py` hand-builds
  artifact dicts inline with `json.dumps`; Plan 3 will hand-build Pydantic DTOs in `api/dtos/`. Two
  serialisations of one entity, drifting from day one — `contracts.md` rule 1 again. They cannot live in
  `api/` (mcp must not import api). Put them in `application/read/dtos.py` and have both adapters use
  them. **This needs a charter line**, because it is a real deviation from the Mode A directory sketch.

---

## 2. Decomposition and task boundaries

### 2.1 What is wrong with the current 8

- **Tasks 4 and 5 are both retro-fits of Task 3.** Task 4 edits `filesystem_repository.py`'s constructor
  and `_build`'s tail; Task 5 rewrites `list_all`, changes `_build`'s return type from `Artifact` to a
  4-tuple, and extracts `_entries` out of `_scan_type`. Two of eight tasks exist to reopen a third. You
  suspected Task 5; Task 4 is the same disease.
- **The architecture contract arrives last.** `import-linter` lands in Task 8. Seven tasks are therefore
  written with no guard, and a layering violation introduced in Task 3 is discovered at the very end. It
  costs nothing in Task 1 and protects everything after it. **Move it to the scaffold.**
- **Task 8 bundles two unrelated deliverables** (the MCP server; the architecture contract) and hides a
  third — the real-library acceptance run — as an untested manual step, whose stated expectation is false
  (§4, D-13).
- **Task 1 and Task 2 are one deliverable split by file.** `ArtifactType` and the type registry are one
  vocabulary; splitting them produces a Task 1 that cannot answer "what is an artifact of this type".
- **Nothing tests the MCP server.** Task 8 tests `call_tool`, a helper the server wraps. Spec §10 asks
  for real JSON-RPC frames. The one integration everything depends on is verified by hand only.

### 2.2 Rule for the recut

Each task ends in a deliverable that (a) can be reviewed as a diff without reading the next task, and
(b) never has its own files reopened by a later task in this plan. Retro-fits are the signal you cut in
the wrong order.

### 2.3 Recommended 9 tasks

| # | Deliverable | Layer | Ends when |
|---|---|---|---|
| **1** | **Scaffold + gate + architecture contract.** `pyproject.toml`, `.gitignore`, empty layer packages, `[tool.importlinter]` contracts, `tests/test_architecture.py`, `tests/__init__.py` and every subpackage `__init__.py`. | — | The one gate command (§7) is green on an empty tree, and `lint-imports` reports the contracts as kept. |
| **2** | **Domain vocabulary.** `ArtifactType`, `ArtifactKind`, `ValidationCode` (enum), `Severity`, `ValidationFinding`, `ArtifactFile`, `Artifact`, `compute_content_hash`, `TypeSpec`/`TYPE_REGISTRY`. Merges old Tasks 1 + 2's domain half. | domain | Every frozen contract in §3.1–§3.2 exists and is unit-tested with zero I/O. |
| **3** | **`RawArtifact` + the pure assembler, including all of V1–V7.** `domain/assembly.py`. Old Task 5's content, **moved ahead of the repository**. | domain | Every rule is tested from a `RawArtifact` literal. No disk. This is the task that removes the rework. |
| **4** | **`library.yaml` reader.** `domain/metadata.py` + `infrastructure/library_yaml.py`, with shape validation and line-numbered failures (§4 D-16). | domain+infra | A malformed, a null-valued, a scalar-where-list, and an absent `library.yaml` each produce the specified outcome. |
| **5** | **The scanner and the repository.** `infrastructure/scanner.py` + `infrastructure/repository.py`, composed from 3 and 4. Includes the `ArtifactRepository` protocol (declared in `domain/` in Task 2 or here — either is fine, but before Task 6). | infra | `tmp_path` fixtures reproduce every §1 failure *including a nested vendor tree inside a skill directory*. Nothing from Tasks 2–4 is edited. |
| **6** | **Read use cases**, including `list_collections` and `get_collection`. | application | Every use case tested against `FakeArtifactRepository`. |
| **7** | **Read CLI** + composition root + library-root resolution that fails loudly on a non-library (§4 D-24). | cli | Typer runner tests, **including one that supplies no `--library`** (§6). |
| **8** | **MCP server**, driven over real JSON-RPC frames, plus a stdout-purity test. | mcp | The four tools are enumerated *from the server*, and `hl mcp` with a bad root emits nothing on stdout. |
| **9** | **Acceptance against the real library**, output recorded in the plan. | — | Recorded, honest output — see §4 D-13 for what it will actually say. |

**Merged:** old 1+2 → new 2. **Split:** old 8 → new 1 (contract) + 8 (server) + 9 (acceptance).
**Reordered:** old 5 → new 3, ahead of the repository. **Dropped:** nothing.
**Net: 8 → 9.**

---

## 3. Contracts to lock before any code is written

Signatures, not descriptions. Anything below that Plan 2 or Plan 3 changes is a rewrite of Plan 1.

### 3.1 `ArtifactFile` — the contract Plan 2 cannot be built without

```python
@dataclass(frozen=True, slots=True)
class ArtifactFile:
    path: str            # POSIX-separated, relative to the artifact root
    sha256: str          # of the file's bytes, alone
    size_bytes: int
    is_text: bool        # decoded as UTF-8 without error
```

**Why this is the most important item in the review.** Spec §8.1 judges install **per path** on three
hashes (L/M/T). Plan 1 reads and hashes every file already; `files: tuple[str, ...]` discards the digests,
so Plan 2 must re-walk and re-hash on a second code path. Two implementations of "what is this file's
hash" agree until one changes the normalisation, and the one that drifts is the one nobody edits. One
object, both callers.

### 3.2 `Artifact`

```python
@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType; name: str
    title: str | None; description: str
    kind: ArtifactKind
    files: tuple[ArtifactFile, ...]          # sorted by path
    content_hash: str                        # sha256 over sorted (path, bytes)
    size_bytes: int                          # sum over files — for --sort size
    updated_at: datetime | None              # local display only; see S1
    frontmatter: Mapping[str, object]        # raw parsed entry frontmatter
    tags: tuple[str, ...]; collections: tuple[str, ...]
    superseded_by: str | None
    findings: tuple[ValidationFinding, ...]
    @property
    def id(self) -> str: ...                 # f"{type.value}/{name}"
    @property
    def is_valid(self) -> bool: ...          # no finding of Severity.ERROR
```

Changes from the plan, each load-bearing:

- `files` carries `ArtifactFile`, not `str` (§3.1).
- `size_bytes` added — `--sort size` currently sorts by file *count* (§4 D-19).
- `frontmatter` added — spec §7.2's detail screen renders it, and the agents carry `model`/`color`/
  `memory` keys that the plan parses and throws away. Re-parsing in Plan 3 is a second code path.
- `errors` → `findings`, and `is_valid` keys off **severity**, not emptiness. Spec §4 makes V6 a warning;
  the plan's `is_valid` returns `False` for a stray `.swp`. (§4 D-3.)

**I endorse the plan's deviation from spec §3.2's `Valid | Invalid(reasons)` sum type.** A findings tuple
plus a derived predicate carries the same information with less machinery. Keep it; update the spec.

### 3.3 `ValidationFinding` — a closed code set, with severity

```python
class ValidationCode(StrEnum):
    MISSING_ENTRY_FILE = "V1"; NAME_MISMATCH = "V2"; DANGLING_REFERENCE = "V3"
    UNRESOLVED_SUPERSESSION = "V4"; MISSING_FRONTMATTER_KEY = "V5"
    EXTRANEOUS_FILE = "V6"; ORPHANED_METADATA_ENTRY = "V7"

class Severity(StrEnum):
    ERROR = "error"; WARNING = "warning"

@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: ValidationCode
    severity: Severity
    message: str                 # for humans; NOT contract
    path: str | None = None      # the offending file, when there is one
```

`code: str` in the plan violates `contracts.md` — a closed set is an enum, so a rename fails at every
emitter instead of silently producing a token nothing handles. Both the CLI and Plan 3's SPA will branch
on these. `path` costs nothing now and changes every construction site later. **V7 is new and
spec-mandated — see §4 D-15.**

### 3.4 `ArtifactRepository`

```python
class ArtifactRepository(Protocol):
    def list_all(self) -> Sequence[Artifact]: ...
    def get(self, artifact_id: str) -> Artifact | None: ...
    def read_bytes(self, artifact_id: str, relative_path: str) -> bytes: ...
    def list_collections(self) -> Sequence[Collection]: ...
```

Three changes, all forced by Plans 2–4:

- **`read_file -> str` becomes `read_bytes -> bytes`.** The library ships a 184 002-byte
  `ctg_brasil_brand_reference.html` (twice — 58 % of the whole library by size). Plan 2 installs bytes,
  Plan 3 streams a zip (spec §7.2). A `str` contract forces a decode-and-re-encode round trip that is
  lossy for anything that is not clean UTF-8. Text is a *view*: put `read_text()` in the application
  layer, where it decodes strictly and raises a typed `BinaryContentError`.
- **`list_collections` added.** Spec §7.2 has a `/collections` route and §7.1 has `--collection`. Plan 1
  parses collections into `LibraryMetadata` and then makes them unreachable from the application layer —
  only the repository holds the metadata. Plan 3 would have to add a method to a frozen protocol.
- **`Sequence`, not `list`** — a `list` return is an invitation to mutate a memoised snapshot.

**Scan semantics must be stated in the protocol's docstring, not left implicit.** The plan's `get()` calls
`list_all()`, which reads and hashes **every byte of the library** to answer one lookup: `hl show` and
each MCP `get_reference` re-read ~670 KB. Lock it as: *one scan per repository instance, memoised; the
result is a point-in-time snapshot; a new instance is a new scan.* That is the honest answer to "what
happens when a file changes mid-scan" (§5.6) and it is what Plan 2's manifest depends on.

### 3.5 Read use-case surface

```python
def list_artifacts(repo, filter: ArtifactFilter | None = None,
                   sort: SortKey = SortKey.NAME) -> Sequence[Artifact]: ...
def get_artifact(repo, artifact_id: str) -> Artifact: ...                    # raises ArtifactNotFound
def get_artifact_text(repo, artifact_id: str, path: str) -> str: ...         # raises ArtifactNotFound,
                                                                             # FileNotInArtifact, BinaryContent
def get_artifact_bytes(repo, artifact_id: str, path: str) -> bytes: ...
def search_artifacts(repo, query: str, *, limit: int = 100,
                     context_lines: int = 1) -> SearchResult: ...
def validate_library(repo) -> ValidationReport: ...
def list_collections(repo) -> Sequence[Collection]: ...

@dataclass(frozen=True, slots=True)
class ArtifactFilter:
    type: ArtifactType | None = None          # enum, not str
    tag: str | None = None
    collection: str | None = None
    invalid_only: bool = False
    include_superseded: bool = True

@dataclass(frozen=True, slots=True)
class SearchResult:
    matches: tuple[SearchMatch, ...]
    truncated: bool                  # limit was hit
    skipped_binary: tuple[str, ...]  # files not searched, named
```

- `SearchResult`, not a bare list: spec §7.3 promises "matches **with context**", and this output crosses
  a JSON-RPC pipe into a context window. An uncapped substring search over 670 KB is a denial of service
  against the model's attention. `truncated` and `skipped_binary` exist because the plan's version
  silently swallows `UnicodeDecodeError` per file — "no match" and "not searched" must be distinguishable.
- `ArtifactFilter.type` is `ArtifactType`, not `str`. `--type skil` must fail, not return zero rows.
- `ValidationReport`, not `list[Artifact]`: the caller needs *N scanned, M invalid* and a place for
  library-level findings (V7) that belong to no single artifact.
- **`include_superseded`** — spec §7.2 demotes superseded artifacts in the list and ranks them below
  successors in search. Both redirect stubs exist today. Decide the flag now; adding it in Plan 3 changes
  the default for MCP clients silently.

**The plan uses module-level functions rather than use-case classes with `execute()`.** That deviates
from Mode A §2.2 and the plan does not declare it. **I endorse the deviation** — these are genuinely thin,
and R19 argues against ceremony with one implementation. But it must be a recorded charter decision,
because R4 (Mode A) specifies `api/dependencies.py` as constructor-injection provider chains, and with
free functions Plan 3's DI shape changes. Charter it (§7).

### 3.6 Error taxonomy — one base, stable codes

```python
class HarnessLibraryError(Exception):
    code: ClassVar[str]
class ArtifactNotFound(HarnessLibraryError):   code = "artifact_not_found"
class FileNotInArtifact(HarnessLibraryError):  code = "file_not_in_artifact"
class PathEscapesArtifact(HarnessLibraryError): code = "path_escapes_artifact"
class BinaryContentError(HarnessLibraryError): code = "binary_content"
class LibraryYamlError(HarnessLibraryError):   code = "library_yaml_invalid"
class NotALibraryError(HarnessLibraryError):   code = "not_a_library"
```

`contracts.md`: errors carry a stable code clients branch on and a message for humans; the message is not
contract. Plan 3 maps `code` → status; the MCP error payload carries `code`. The plan's untyped
`{"error": "not found: skill/ghost"}` forces every client to parse English.

### 3.7 MCP wire payloads

Freeze the four tool payloads as **Pydantic models in `application/read/dtos.py`**, shared with Plan 3's
HTTP responses. Two shapes for one artifact is the drift `contracts.md` opens with. Freeze in particular:

- `list_artifacts` → `{id, name, type, description, tags[], superseded_by|null, file_count, size_bytes,
  valid, findings[{code,severity,message,path}]}`. Note `superseded_by` is **present-and-null**, never
  omitted — `contracts.md` is explicit that omission and null are different wire facts.
- Error result → `{"error": {"code": "...", "message": "..."}}` for every tool, uniformly.
- `search_artifacts` → `{matches[], truncated, skipped_binary[]}`.

### 3.8 The composition root

```python
def resolve_library_root(explicit: Path | None) -> Path: ...  # --library > $HL_LIBRARY > cwd, then verify
def build_repository(root: Path) -> ArtifactRepository: ...
```

`hl serve` (Plan 3) and `hl mcp` must resolve identically. Freeze the precedence and the `$HL_LIBRARY`
name now; changing an env var name after Plan 3 ships breaks every user's MCP client config.

### 3.9 What will *not* survive contact — summary

| Plan 1 shape | Breaks in | How |
|---|---|---|
| `files: tuple[str, ...]` | Plan 2 | §8.1's per-path verdicts need per-file hashes; forces a second scanner |
| `read_file -> str` | Plan 2, Plan 3 | binary install + zip export; the 184 KB HTML asset |
| no `list_collections` | Plan 3 | `/collections` route; protocol is frozen by then |
| no `frontmatter` on `Artifact` | Plan 3 | detail screen renders it; forces a re-parse |
| `ValidationError(code: str)` | Plan 3 | SPA branches on the code; a rename passes silently |
| `is_valid == no errors` | Plan 2 | a `.swp` warning blocks install as "invalid" |
| inline `json.dumps` dicts in mcp | Plan 3 | second serialisation of one entity |
| `{"error": "<english>"}` | Plan 3, MCP clients | no branchable code |
| `target_template` in domain | Plan 2 | format string cannot express file-vs-dir targets |

---

## 4. What the plan gets wrong

Severity: **B** blocker (contract or ships-broken) · **H** high · **M** medium · **L** low.

### Contract defects

| # | Sev | Task | Defect |
|---|:--:|:--:|---|
| D-1 | **B** | 1, 3 | `files: tuple[str, ...]` drops per-file hashes and sizes that the scan already computed. Plan 2 (spec §8.1) needs them per path. §3.1. |
| D-2 | **B** | 3 | `ArtifactRepository.read_file -> str`. Binary/large-asset hostile; Plan 2 copies bytes, Plan 3 zips bytes. §3.4. |
| D-3 | **B** | 1, 5 | `is_valid` is `not self.errors`, so V6 — a **warning** per spec §4 — marks an artifact invalid. A stray `.swp` (the exact §1 observation) would make `agent/backend-developer-specialist` INVALID and, in Plan 2, unfit to install. No severity field exists. §3.3. |
| D-4 | **B** | 1 | `ValidationError.code: str`. `contracts.md`: a closed set is an `Enum`, not `str`. Also missing `path`. §3.3. |
| D-5 | **B** | 4, 6 | Collections are parsed and then unreachable from the application layer. No `list_collections`; spec §7.2 has a `/collections` route. §3.4. |
| D-6 | **B** | 8 | MCP error payload is `{"error": "<english>"}` — no stable code to branch on. Serialisation is hand-built inline, guaranteeing divergence from Plan 3's DTOs. §3.6, §3.7. |

### Rules that ship broken

| # | Sev | Task | Defect |
|---|:--:|:--:|---|
| D-7 | **H** | 3 | `_collect_files` filters `p.name.startswith(".")` on the **file** name, so a nested `.git/` or `node_modules/` **inside a skill directory** is walked and every byte read into the content hash. This is precisely the §1 observation (`node_modules/` propagated into `agents/`) that the design exists to close. The fixture puts the swap file in `agents/` — caught by a *different* filter in `_scan_type` — so the hole is invisible to the suite. |
| D-8 | **H** | 3 | Two different rules for "is this path inside the artifact". `read_file` resolves and checks `is_relative_to`; `_collect_files` does not. A symlink inside an artifact pointing outside is read and hashed by one path and rejected by the other. `contracts.md` rule 1: one decision, one object. |
| D-9 | **H** | 3 | Symlinks are unhandled everywhere. `Path.is_file()` follows them; `rglob("*")` does not descend symlinked directories. The asymmetry means a symlinked *file* silently becomes content while a symlinked *directory* silently disappears. Plan 2 will then materialise the first as a regular file. Decide and encode: skip + report as V6, or follow + record. |
| D-10 | **H** | 3 | mtimes are gathered in a **second** filesystem pass after the read (`(path / rel).stat()`). A file removed between the two raises `FileNotFoundError` and crashes the whole scan — violating spec §9's "never crashes the scan". Capture mtime from the same `stat` that drives the read. |
| D-11 | **H** | 2, 3 | Entry text is produced with `.decode("utf-8", errors="replace")`. The string that yields `title`/`description` is then **not** the bytes that were hashed, silently. A UTF-8 BOM (`﻿---`) additionally defeats python-frontmatter's delimiter detection entirely, producing an artifact with an empty description and a spurious V5 — with no diagnostic. |
| D-12 | **H** | 2 | `parse_frontmatter` catches only `yaml.YAMLError`. Frontmatter that parses to a non-mapping (`---\n- a\n---`) makes `dict(post.metadata)` raise `TypeError`/`ValueError`, uncaught, crashing the scan. Spec §9 requires it to load as `Invalid`. |
| D-13 | **H** | 5, 8 | **V3 produces seven false positives against the real library today.** Verified this session: `developers-orchestration/SKILL.md` cites `references/collaboration.md`, `conflicts.md`, `cost-and-time.md`, `delegation.md`, `plan-formats.md`, `review-and-merge.md`; `frontend-ctg-system-pattern/SKILL.md` cites `references/brand-ctg.md`. **All seven exist — in the successor skill.** Both files are redirect stubs whose entire purpose is prose describing where content moved. V3 as specified cannot tell a citation from a forwarding address. Consequence: Task 8 step 6's stated expectation ("reports nothing as `INVALID`") is **false**, and the plan's "Done when" contradicts it. Fix: V3 does not apply to an artifact with `superseded_by` set; record the exemption in spec §4. |
| D-14 | **H** | 5 | **V6 can never fire.** `_collect_files` discards skipped paths; Task 5 asserts `_build` "returns … the last element lists dotfiles and other skipped entries" but no step produces that list. The only V6 test is the pure unit test, which is *handed* `extraneous_files=(".SKILL.md.swp",)`. V6 ships green and non-functional — the single most damaging failure mode here, because §1's `.swp` and `node_modules` observations are the reason V6 exists. `RawArtifact.skipped` (§1.2) makes this structurally impossible to forget. |
| D-15 | **H** | 4, 5 | **Spec §3.4's rule is not implemented anywhere.** "An entry in `library.yaml` for an artifact that does not exist on disk is a validation error, not a silent no-op." `validate_artifact` is per-artifact, and the plan has no library-level pass. The fixture's own `library.yaml` keys `skill/developers-orchestration`, which is **absent from the fixture tree**, and no test notices. Add **V7**, covering both `artifacts:` keys and `collections[].members`. |
| D-16 | **H** | 4 | `read_library_yaml` does no shape validation on a hard-failure path. `skill/x:` with an empty body (the most common YAML slip) makes `entry` `None` → `AttributeError`, not the line-numbered failure spec §9 promises. `tags: process` (scalar, not list) yields `('p','r','o','c','e','s','s')` silently. |
| D-17 | **H** | 6, 7 | **`hl show` crashes on the plan's own fixture.** `show_command` calls `get_artifact_file(..., entry_filename_for(...))`; for `skill/solution-designer` — the V1 artifact with no `SKILL.md` — the repository raises `FileNotFoundError`, which crosses the application layer untouched (R7 violation: infrastructure exceptions must not leak) and reaches the CLI with no handler. Spec §4's whole point is that an invalid artifact is *shown with its reasons*. Untested. |
| D-18 | **H** | 8 | `TOOL_NAMES` is a hand-written tuple sitting beside `TOOL_SCHEMAS`, and `test_exposes_exactly_the_four_read_tools` asserts on `TOOL_NAMES`. **A fifth tool added to `TOOL_SCHEMAS` and not to `TOOL_NAMES` passes the test that exists to prevent it.** Two lists, one vocabulary — `contracts.md` rule 1, in the one place the plan calls a structural guarantee. Derive names from schemas and assert against what the server's `list_tools()` actually returns. |
| D-19 | **H** | 6 | `--sort size` sorts by `len(a.files)` — file *count*, not size. `test_sorts_by_size_largest_first` asserts the wrong thing under a name that claims otherwise. Spec §7.1 says `size`. Add `Artifact.size_bytes` (§3.2) or rename the key. |
| D-20 | **H** | 8 | The `import-linter` `layers` contract orders `cli > mcp > infrastructure > application > domain`, which makes `infrastructure → application` a *downward*, **permitted** import. In Mode A infrastructure implements domain protocols and must never reach up into use cases. The contract as drafted does not enforce the layering it is named for. Also `ignore_imports = cli.context -> infrastructure.*` is redundant (already downward) and signals the misreading. Correct shape: `cli : mcp` as independent siblings above `application` above `domain`, plus a `forbidden` contract for `infrastructure → application | cli | mcp`. |

### Structural / ordering

| # | Sev | Task | Defect |
|---|:--:|:--:|---|
| D-21 | **H** | 4, 5 | Both tasks retro-fit Task 3. Task 5 changes `_build`'s return type and rewrites `list_all`; Task 4 changes the constructor and `_build`'s tail. Confirmed and worse than suspected. §2.3 reorders. |
| D-22 | **H** | 6, 7, 8 | `from tests.application.fakes import ...` and `from tests.infrastructure.conftest import library_root` require `tests` to be an importable package. `pythonpath = ["src"]` adds only `src`, and no `tests/__init__.py` is created anywhere. **These imports will fail on first run.** Add `tests/__init__.py` (and per-subpackage) in Task 1, plus `pythonpath = ["src", "."]`. Recurring trap — see §8. |
| D-23 | **M** | 3 | `get()` calls `list_all()`, so a single lookup reads and hashes the entire library. `hl show` and every MCP `get_reference` pay ~670 KB. Memoise the scan per instance and document the snapshot semantics (§3.4). |
| D-24 | **M** | 7 | `resolve_library_root` falls back to `Path.cwd()`, and a directory with no `skills/` or `agents/` scans to `[]` and exits **0**. `hl list` in the wrong directory silently reports an empty library — the same "invisible rather than flagged" failure class §1 exists to close. Raise `NotALibraryError` when none of `skills/`, `agents/`, `library.yaml` is present. |
| D-25 | **M** | 7 | `cli/context.py` reads `os.environ.get("HL_LIBRARY")` directly. R1: config is read in exactly one Pydantic Settings class and no other file touches the environment. `pydantic-settings` is not in the dependency set — **stack question for you** (§8). |
| D-26 | **M** | 7 | `build_repository` runs in `@app.callback()`, so `library.yaml` is read for every invocation including `--help`, and a `LibraryYamlError` surfaces as a traceback rather than spec §9's line-numbered hard failure. Build lazily; catch at the command boundary. |
| D-27 | **M** | 6 | `get_artifact_file` calls `get_artifact` (a full scan) purely to pick the right exception, then resolves the path again. Two resolutions, one lookup. |
| D-28 | **M** | 6 | `search_artifacts` swallows `UnicodeDecodeError`/`ValueError` per file and continues, silently skipping the 184 KB HTML asset. "No match" and "not searched" become indistinguishable. §3.5's `skipped_binary` fixes it. |
| D-29 | **M** | 6 | No cap and no context lines on search, against spec §7.3's "matches with the matching line and context". A one-word query over 670 KB returns thousands of rows through a JSON-RPC pipe. |
| D-30 | **M** | 1 | `compute_content_hash(files: dict[str, bytes])` requires the entire library resident in memory, and `_collect_files` obliges on every `list_all()`. Take `Mapping[str, str]` of per-file digests and hash the digest list, or stream per file. |
| D-31 | **M** | 2 | `entry_filename: str | None` uses `None` as a sentinel for "named after the artifact". Two meanings in one field. Prefer an explicit `EntryNaming` discriminator or always compute. |
| D-32 | **M** | 2 | `target_template` and `source_dirname` are the same fact (spec §3.5: the tree mirrors the target exactly) stored twice, and the former has no Plan-1 consumer (R18/R19). Collapse to `directory_name`. |
| D-33 | **M** | 4 | `LibraryMetadata` is `frozen=True` with mutable `dict` fields — a guarantee the type does not provide. |
| D-34 | **L** | 1 | `test_artifact_is_frozen` uses `pytest.raises(Exception)`, which passes on any exception including a typo. `FrozenInstanceError` is the assertion — and dataclass immutability is a language guarantee, not project behaviour. |
| D-35 | **L** | 1 | `test_hash_changes_when_a_path_is_renamed` uses `SKILL.md` vs `SKILL.MD` — two paths that cannot coexist on a case-insensitive filesystem, so it models an unreachable rename. Use `a.md` vs `b.md`. |
| D-36 | **L** | 1 | The hash frames path and content with `\0` separators but no length prefixes. Safe in practice (NUL is not legal in a POSIX path component), but length-prefixing costs nothing and removes the argument permanently. |
| D-37 | **L** | 6 | `test_search_matches_description_and_reports_the_line` asserts on **file content**, not on the description — and `search_artifacts` does not search descriptions at all. The name claims a behaviour the code lacks. The CLI's `test_search_reports_the_matching_line` then passes for the wrong reason: "Integration owner" happens to be inside the frontmatter *bytes*. |
| D-38 | **L** | 8 | `test_import_contracts_hold` shells `python -m importlinter.cli lint`; the supported entry point is the `lint-imports` script, and the run depends on the test process's cwd finding `setup.cfg`. Fragile under `--rootdir` variation. Use `lint-imports` and put the config in `pyproject.toml` under `[tool.importlinter]` — a `setup.cfg` beside a hatchling build backend is also a tooling smell. |

### Plan-level

- **D-39 (H) — the plan's two acceptance criteria contradict each other.** "Done when" requires
  `hl validate` to exit 1 and name the rule for every defect in spec §1; Task 8 step 6 notes those defects
  were already fixed in the real tree and expects no `INVALID`. Both cannot hold. And per D-13 the real
  run will report two INVALID artifacts, for a reason the plan does not anticipate. Task 9 exists to
  record the honest output.
- **D-40 (M) — the gate is under-specified.** `uv run pytest && uv run ruff check . && uv run mypy src`
  omits `ruff format --check`, omits `lint-imports`, and scopes mypy to `src` so the entire test suite is
  unchecked. `testing.md`: the exact command *is* the gate, and a narrower invocation passes where the
  gate would fail. Name one command in the charter (§7) and require every task to run it whole.
- **D-41 (M) — deviations are declared inconsistently.** The plan flags its §3.2 sum-type deviation but
  not the use-case-functions deviation from skill §2.2, nor the `pyyaml` deviation from skill §5. One
  list, in the charter.

---

## 5. What the plan misses entirely

### 5.1 Encoding and binary files
The library is 58 % binary-ish by weight: `ctg_brasil_brand_reference.html`, 184 002 bytes, **duplicated**
in `frontend-ctg-system-pattern/` (at the artifact root, not under `references/`) and in
`frontend-system-pattern/references/`. Needed: hash bytes always; decode only for display and search;
`is_text` per file; a typed `BinaryContentError` rather than a swallowed exception; and an explicit
statement that `read_bytes` is the primitive. Also **BOM handling** (D-11) and a policy for a file that is
valid UTF-8 but not text (a PNG that happens to decode).

### 5.2 Symlinks
Unhandled at every level (D-8, D-9). Decide now, because Plan 2 must know whether to copy the link or the
target, and `hl clean --foreign` must not follow a link out of the target tree. Recommendation: do not
follow; record each as a V6 finding with a distinct message.

### 5.3 Case-insensitive filesystems
Three separate exposures, none addressed: (a) the entry-file lookup — `Skill.md` satisfies the OS but not
`entry_filename_for`; (b) `Artifact.id` and therefore `library.yaml` keys become case-dependent, so a
`library.yaml` authored on macOS may not match on Linux, and D2 says git distributes between machines;
(c) `skills/Foo` and `skills/foo` are two artifacts on Linux and one on macOS. At minimum: normalise the
entry-file comparison, and add a scan-level finding when two artifact names differ only by case.

### 5.4 Very large reference files
`_collect_files` reads every byte of every artifact into a dict on **every** `list_all()`, and `get()`
calls `list_all()`. Today that is 670 KB per lookup; there is no ceiling in the design. Stream-hash per
file and retain only digests + sizes (§3.1 makes this natural). Then `Artifact` construction is O(files)
in memory rather than O(bytes).

### 5.5 Two artifacts declaring the same name
Cross-type is safely namespaced by `<type>/<name>`. Three real cases are unhandled: same name differing
only in case (§5.3); a `skills/<name>/` directory alongside a stray `skills/<name>.md` (the scanner
filters by `is_dir()`/`is_file()` and would silently ignore one); and **duplicate keys in
`library.yaml`**, which `yaml.safe_load` resolves last-wins with no warning. Add a scan-level finding for
each.

### 5.6 A file changing mid-scan
Two distinct failures. (a) The read-then-stat second pass crashes the scan on a deletion (D-10). (b) More
subtly: `content_hash` can mix pre-edit and post-edit bytes across files within one artifact, producing a
hash for a state that **never existed on disk**. Plan 2 writes that hash into the manifest, where it
becomes a permanent phantom that makes every future verdict wrong — and spec §8.1's entire verdict table
is hash equality. Also spec §9's "save rejected on hash mismatch" presumes the hash is trustworthy.
Recommendation: state snapshot semantics in the protocol (§3.4), capture size+mtime in the same `stat`
that precedes each read, re-`stat` after, and emit a `SCAN_UNSTABLE` finding on mismatch rather than
silently publishing a phantom. `concurrency.md`: an operation that cannot be atomic states its
intermediate state and how it is recovered.

### 5.7 Also missing, day one
- **Empty or absent `skills/`** → silent empty success, exit 0 (D-24).
- **`PermissionError`** on an unreadable artifact directory crashes the scan. Spec §9 says the scan never
  crashes; it enumerates only malformed frontmatter.
- **The executable bit.** Every real file is `-rwxrw-rw-`. `content_hash` ignores mode, so Plan 2 cannot
  tell whether a mode difference is drift. Decide now, because the hash definition is being frozen: I
  recommend explicitly excluding mode from the hash and saying so in the spec, with Plan 2 normalising
  modes on install.
- **Git provenance.** Spec §8.4 wants "the library git SHA installed from"; spec §5 lists
  `GitProvenance` in infrastructure. Plan 1 freezes the repository contract with nowhere for it.
  Recommendation: a separate `LibraryProvenance` port, not a method on `ArtifactRepository` — read-only
  MCP has no business holding it.
- **Observability: nothing logs anything.** `observability.md` wants structured logs at boundaries. For
  `hl mcp` specifically, a failure is currently *completely silent*, and **stdout is fatal** (D8). The
  charter must state: logs to stderr, always; one structured line per MCP tool call; never stdout in the
  `mcp` process. There is no test asserting stdout purity, and Typer prints errors to stdout by default —
  a bad `--library` would corrupt the JSON-RPC stream.
- **No MCP integration test at all.** Spec §10 asks for real JSON-RPC frames; Task 8 tests a helper the
  server wraps, and `@server.call_tool()`'s return conventions have changed across SDK versions.

---

## 6. Testing

### 6.1 The strategy is right; the code defeats it
Domain + application against hand-written fakes, infrastructure against `tmp_path`, matches R15/R17 and
`testing.md`'s taxonomy. **Keep it.**

But the plan puts most of the *behaviour* — parsing, titling, hashing, validation orchestration — inside
`FilesystemArtifactRepository`, so the fakes exercise almost nothing and the `tmp_path` tests carry the
load. The `RawArtifact` seam (§1.2) moves that behaviour into pure tests, which is the largest single
testing improvement available and costs one dataclass.

### 6.2 The highest-value missing test
**A skill directory containing a nested `node_modules/` (or `.git/`) tree**, asserting three things in one
test: the vendor files are absent from `Artifact.files`; the `content_hash` equals the hash of the same
artifact without the tree (a positive control, so the test cannot pass by returning nothing); and a V6
**warning** is reported naming the directory, with `is_valid` still `True`.

It earns the top slot because it is the one test that would fail today for **four independent reasons** —
D-7 (the dotfile filter does not exclude nested vendor dirs), D-14 (V6 has no wiring), D-3 (V6 would mark
the artifact invalid), D-19-adjacent (size accounting) — and because it reproduces the exact §1
observation the whole design exists to close. The plan's fixture puts the `.swp` in `agents/`, where a
*different* filter catches it, so the hole is structurally invisible.

**Mutation check to demand of the implementer:** delete the vendor-exclusion predicate in
`infrastructure/scanner.py` and require that named test to fail *by name*; restore by reversing the edit,
not by discarding the tree. Aim it in the scanner, not in a fake — `testing.md`: a mutation inside a
double proves only that the double is a double.

Runners-up, in order: (2) `hl mcp` with an unresolvable `--library` emits **zero bytes on stdout**;
(3) V3 against a redirect stub, asserting the seven real citations do **not** produce findings (D-13);
(4) `hl show` on a V1-invalid artifact prints the findings and exits non-zero instead of raising (D-17).

### 6.3 Tests that assert the wrong thing
- `test_sorts_by_size_largest_first` — asserts file count under a name claiming bytes (D-19).
- `test_search_matches_description_and_reports_the_line` — asserts file content; descriptions are not
  searched (D-37).
- `test_exposes_exactly_the_four_read_tools` — asserts a hand-maintained tuple, not the server's actual
  tool list, so it passes through the exact change it exists to catch (D-18).
- `test_a_dotfile_is_never_an_artifact` — a bare absence assertion (`not any(...)`) that passes if
  `list_all()` returns `[]`. `testing.md` is explicit: pair it with a positive control in the same test.
  (`test_lists_every_artifact_including_the_broken_one` supplies one *elsewhere*, which does not help
  when the fixture is what broke.)

### 6.4 Not worth testing
`test_artifact_is_frozen` (a language guarantee, asserted with `pytest.raises(Exception)`);
`test_build_server_registers_the_tools` (asserts `is not None`); `test_no_tool_name_suggests_a_mutation`
(string-matching over names — `testing.md`: structural tests are defeated by naming, and the import
contract is the real guarantee); `test_registry_covers_every_artifact_type` (tautological against the
dict it reads). The eight single-predicate `ArtifactFilter` tests should be one table test.

### 6.5 The untested default
Every CLI test passes `--library` explicitly, so `resolve_library_root`'s `$HL_LIBRARY`-then-cwd
fallback — **the only path production uses** — is never exercised. `testing.md`, verbatim: a default needs
one test that supplies nothing. Add two: `$HL_LIBRARY` set, and neither set (asserting the loud failure
from D-24).

### 6.6 What the fake cannot see
Record it, so nobody trusts the green: fakes cannot see the vendor-tree walk, symlink behaviour, encoding
and BOM handling, case-insensitivity, mid-scan mutation, permissions, or the MCP SDK's dispatch
conventions. Every one of those is verified against a real filesystem or a real server, or it is
unverified.

---

## 7. What `backend-charter.md` should declare

A section list. One line each on what it must settle.

1. **Architecture mode** — `**Architecture:** Clean Architecture (Mode A)`, in the header line, because
   the skill reads it from exactly there and the default only applies when it is silent.
2. **Layer map and the import contract** — the five packages, the dependency direction, and the statement
   that `import-linter` enforces it as a *test*, with the corrected layering from D-20.
3. **Declared deviations from the skill** — one list with a reason each: use-case *functions* rather than
   classes (§3.5); frozen dataclasses rather than Pydantic in `domain/`; shared presentation DTOs in
   `application/read/dtos.py` rather than `api/dtos/` (because `mcp/` must not import `api/`).
4. **Stack rulings** — the approved dependency set, and explicitly: **`pyyaml` is on the skill's
   NOT-allowed list** (§5) and is used here anyway. Record the carve-out and its reason — the ban targets
   YAML *configuration*; `library.yaml` is user-authored *data* mandated by spec §3.4, and
   `python-frontmatter` vendors PyYAML regardless. Also rule on `pydantic-settings` (D-25) and
   `structlog` (§5.7). Nothing is added later without a ruling recorded here.
5. **The gate command** — one exact string, run whole by every task, never path-scoped. It must include
   `ruff format --check`, `ruff check`, `mypy` over `src` **and** `tests`, `lint-imports`, and `pytest`.
   Note that a run stopping at type-check is not green (D-40).
6. **Frozen contracts, with a change procedure** — the eight in §3, and the rule that changing one is a
   plan-level decision, not a task-level one, because Plans 2–4 build against them.
7. **Identity, hashing and filesystem policy** — `<type>/<name>`; what the content hash covers and what it
   deliberately excludes (file mode, mtime, skipped paths); symlink policy; case-sensitivity policy;
   text-vs-binary policy; scan snapshot semantics. This is the section that answers §5, and every item in
   it is a decision Plan 2 inherits silently if it is not written down.
8. **Validation rule register** — V1–V7 with code, severity, and the observed failure each closes,
   including the V3 redirect-stub exemption (D-13). One table; new rules are added here first.
9. **Error taxonomy** — the base class, the stable codes, and the mapping to CLI exit codes now and HTTP
   status codes in Plan 3. `contracts.md`: a code is added to the contract before it is emitted.
10. **Testing policy** — the layer taxonomy, what each layer is blind to (§6.6), the mutation-check
    requirement, the positive-control rule for absence assertions, and the fixture set that reproduces
    every spec §1 failure (with the note that those fixtures are never deleted).
11. **Logging and stdout discipline** — structured to stderr; one line per MCP tool call; **nothing ever
    on stdout in the `hl mcp` process**, and the test that proves it. This is D8's requirement turned into
    a mechanism instead of a promise.
12. **Concurrency posture** — read-only, no locking, multiple concurrent `hl mcp` processes are safe;
    state explicitly that Plan 2 revisits this because it writes.
13. **Configuration** — the single settings reader, `$HL_LIBRARY`, the resolution precedence, and R1's
    prohibition on any other module touching the environment.
14. **Decisions log** — dated entries; the place a mode change or a stack ruling is recorded.

---

## 8. Disagreements with the spec (yours to take up, not mine to change)

| # | Spec ref | Issue |
|---|---|---|
| **S1** | §3.2 `updated_at` | Defined as max mtime. D2 makes **git** the distribution mechanism, and a clone sets every mtime to clone time — so on the second machine every artifact is "updated now" and `--sort updated` is noise. Either derive it from git, or state it is a local display value and never a cross-machine sort key. |
| **S2** | §3.2 + §4 | The entity has a single `validity` field, but §4 grades V6 as a warning. Without a severity, a stray `.swp` makes an artifact "invalid" and Plan 2 will refuse to install it. Severity belongs in §3.2. |
| **S3** | §4 V3 | **The rule as written is false against the current library** — seven false positives on the two redirect stubs (D-13). It needs an explicit exemption for artifacts with `superseded_by` set. Note the irony: §3.2 argues supersession must be first-class *precisely so* rules can treat these artifacts differently, and then §4 does not. |
| **S4** | §3.2 vs §8.1 | §3.2 defines only a whole-artifact `content_hash`, but §8.1's verdict table judges **per path**. The per-file hashes have to exist; the spec should say so, and should also state whether file mode participates (§5.7). |
| **S5** | §7.3 | `search_artifacts → "matches with the matching line and context"` — "context" is undefined, and there is no cap on a tool whose output crosses a JSON-RPC pipe into a model's context window. Both are wire contract. |
| **S6** | §12.5 vs §7.3/§10 | Search depth is listed as an open question, but §7.3 and §10 both assume reference bodies are searched, and §12.6's scan-cost question depends on the answer. Settle it before Plan 1 freezes the search contract. |
| **S7** | §3.4 vs §4 | §3.4 mandates that a `library.yaml` entry for a nonexistent artifact is a validation error, but §4's table has no rule for it. Add V7 (D-15), covering `collections[].members` too. |
| **S8** | §7.3 | "`mcp/` imports from `application/read` only, and an import-linter contract fails CI if that is ever violated" — the contract the plan drafts does not actually express this, and separately permits `infrastructure → application` (D-20). The spec's guarantee is right; the translation is wrong. |

Two spec **open questions** matter for Plan 1 and are unresolved: **§12.2 (plugin export)** shapes
`ExportArtifact`, which is out of Plan 1's scope but whose repository primitive (`read_bytes`, §3.4) is
being frozen *in* Plan 1; and **§12.5 (search depth)**, which is Plan 1's contract directly. §12.1
(additional targets) and §12.3 (non-Claude harnesses) are Plan 2 concerns and can wait.

---

## 9. Open questions I could not resolve

1. **Search depth** (spec §12.5). Reference bodies included, or entry files and frontmatter only? It
   changes the `search_artifacts` contract, the scan cost, and whether the 184 KB HTML asset is in or out.
   I recommend: entry files + all `.md` references, never binary, `skipped_binary` reported. Needs your
   ruling before Task 6.
2. **Superseded artifacts in the default listing.** Spec §7.2 says "demoted" for the UI and §7.3 gives
   MCP no such statement. Does `list_artifacts` with an empty filter include them, and does MCP rank them
   below successors? `include_superseded` (§3.5) needs a default.
3. **Symlink policy** (§5.2) — skip-and-report, or follow-and-materialise? Plan 2 cannot be written
   without the answer, and the hash definition depends on it.
4. **File mode in the content hash** (§5.7) — every real file is `-rwxrw-rw-`. In or out? I recommend out,
   with Plan 2 normalising, but it is a spec decision.
5. **`pydantic-settings` and `structlog`** — both are in the skill's baseline and neither is in the plan's
   dependency set. R1 (single config reader) and `observability.md` both want them. **Stack ruling
   required; I have not assumed one.**
6. **`pyyaml`** — required by spec §3.4, prohibited by skill §5. I believe the carve-out is correct
   (data, not config) but the ruling is yours to make and record (§7 item 4).
7. **CLI output as contract.** `hl list`'s columnar output is asserted by substring in the tests and will
   be scraped by users. Is it contract? If so it needs a `--json` mode locked now, since Plan 3's SPA and
   any scripting user will otherwise parse the human format.

---

## 10. Traps for the next agent on this project — **recurring**

1. **`tests` is not importable as a package.** `pythonpath = ["src"]` plus `from tests.application.fakes
   import ...` fails immediately, and the error names a module that visibly exists on disk, which sends
   you looking in the wrong place. Create `tests/__init__.py` and one per subpackage **in the scaffold
   task**, and set `pythonpath = ["src", "."]`. (D-22)
2. **The gate must be one command, run whole.** A path-scoped `pytest tests/domain` passes while the gate
   fails — every task in the plan invokes exactly that narrower form. Fix the command in the charter and
   run it whole every time. (D-40)
3. **`import-linter`'s layer order is a trap that reads as correct.** Listing `infrastructure` above
   `application` silently *permits* the inward-violating import you meant to forbid. The contract looks
   right and enforces the opposite. Verify by deliberately adding a violating import and watching
   `lint-imports` fail — a contract nobody has seen fail is a contract that does not run. (D-20)
4. **`~/.claude/` is a target layout, not a library layout.** Task 7 step 6 points `hl --library ~/.claude`
   at it as a smoke test. It happens to work because both use `skills/` and `agents/`, but there is no
   `library.yaml`, so tags, collections and supersession all read as empty, and the run tells you far less
   than it appears to. Build a real fixture library in the repo for acceptance.
5. **The two redirect stubs will fail V3 and it will look like your bug.** Seven findings, all naming
   reference files that plainly exist — in a *different* skill's directory. Expect it, and check D-13
   before debugging the regex. (D-13)
6. **`hl mcp` dies silently on any stdout write**, including Typer's own error output on a bad flag. There
   is no test for this and the failure mode is an MCP client that reports a malformed JSON-RPC stream with
   no clue why. Write the stdout-purity test before the server.
7. **`python -m importlinter.cli` is not the supported entry point** and its cwd-dependence makes it fail
   differently under `pytest --rootdir`. Use the `lint-imports` script and put the config in
   `pyproject.toml`, not `setup.cfg`. (D-38)
