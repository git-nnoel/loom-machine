# T-1 backend task plan — scaffold, gate, architecture contracts

Written before the first edit. Task: phase-1 / initiative 01-store-and-read-path / T-1.

## Understanding

Create the project from nothing: packaging, the single gate command, the five empty layer packages,
the tests tree, and the three `import-linter` contracts wired as a **test** rather than a lint step.
No entity, no use case, no adapter. Every later task in the initiative is written under this guard.

## Reconnaissance findings (before editing)

- Repo is documentation only. Python 3.12.3 on PATH.
- **`uv` is not installed** and the charter §5 gate is expressed as `uv run …`. Network reaches PyPI,
  so `uv` is installable as a *toolchain* (not a project dependency, not a charter §4 stack change).
  Flag to the delivery lead.
- No virtualenv exists; `pytest` is not importable from system Python.

## Approach

1. **`pyproject.toml`** — `[project]` with exactly the charter §4 runtime set
   (`typer`, `pydantic`, `pydantic-settings`, `python-frontmatter`, `pyyaml`, `mcp`, `structlog`);
   dev group with exactly `pytest`, `ruff`, `mypy`, `import-linter`. Nothing else.
   `requires-python >= 3.12`. `hatchling` build backend over the `src/` layout so `uv run` installs
   the project editable. **No `[project.scripts]` entry yet** — `hl` would point at a `cli/main.py`
   that T-7 has not written, and a dangling entry point breaks the install.
2. **`.gitignore`** — caches, `.venv`, build artefacts. `uv.lock` is *not* ignored.
3. **Layer packages** under `src/harness_library/`: `domain/`, `application/` (with `read/` and
   `write/`), `infrastructure/`, `cli/`, `mcp/`. Each with `__init__.py`.
   `application/write/` is created empty on purpose: the `mcp-is-read-only` contract needs a real
   module to forbid, and initiative 02 fills it.
4. **Tests tree** — `tests/__init__.py` and one per subpackage (**L1**). Pytest
   `pythonpath = ["src", "."]`, so `tests` is importable.
5. **Three contracts** in `pyproject.toml` (**L4** — config lives here, never `setup.cfg`):
   - `layered-architecture` (`layers`, ordered **high → low**):
     `cli | mcp` → `application | infrastructure` → `domain`.
     `application` and `infrastructure` are *independent siblings* (`|`), not stacked: in Mode A
     infrastructure implements domain protocols and neither adapter layer may reach the other.
     **L3** — this ordering reads plausibly in either direction, so it is proved by mutation, not
     by inspection.
   - `mcp-is-read-only` (`forbidden`): `harness_library.mcp` ↛ `harness_library.application.write`.
   - `domain-is-pure` (`forbidden`): `harness_library.domain` ↛ every other layer.
6. **`tests/test_architecture.py`** — invokes the **`lint-imports` console script** (**L4**, never
   `python -m importlinter.cli`) as a subprocess with an explicit `cwd` of the repo root, so the
   pytest rootdir cannot change the outcome. Asserts exit 0 *and* that each of the three contracts
   is reported KEPT by name, so a contract silently dropped from the config fails the suite.

## Verification

Gate, run whole (charter §5, plan §9), never path-scoped (**L2**), formatter first:

```
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

## Mutation check — assertion named in advance

Add `from harness_library import application` inside a module in `harness_library.domain`.

**Must fail — both:** `lint-imports` reports `domain-is-pure` BROKEN, **and**
`tests/test_architecture.py` fails. One firing without the other means the contract is not wired as
a test and the guard is theatre.

**Independence check:** `layered-architecture` will also break (a domain→application import violates
it by construction; that is the layers contract doing its job, not a leak). The check that must stay
green throughout is `mcp-is-read-only`. Both broken and restored outputs are quoted in the report.

## Out of scope

No entity, no use case, no adapter, no CLI/MCP entry point, no commit.

---

# T-2 backend task plan — domain vocabulary

Written before the first edit. Task: phase-1 / initiative 01-store-and-read-path / T-2.
Layer: `domain/` only. Contracts realised: **C-1**, **C-2**, **C-3** (and **C-4** declared, not implemented).

## Understanding

Freeze the vocabulary every later task consumes: the two closed enums that name what an artifact *is*,
the closed validation register, the two record types (`ArtifactFile`, `Artifact`), the content hash, the
type registry, and the `library.yaml` domain types moved here by DEC-8. Frozen dataclasses, not Pydantic
(charter §3): this layer imports nothing from the project and nothing from a framework. No filesystem,
no clock, no network — the values are *derived* by T-5, only *typed* here.

## Approach — file by file

| File | Holds | Why separate |
|---|---|---|
| `domain/identity.py` | `ArtifactType`, `make_artifact_id`, `parse_artifact_id` | identity is `<type>/<name>` (charter §7) and is parsed back out of `library.yaml` keys by T-3's V7; one implementation of the split, not two |
| `domain/validation.py` | `Severity`, `ValidationCode` (closed, V1–V7), `ValidationFinding` (**C-3**) | the register is charter §8's table turned into code |
| `domain/hashing.py` | `hash_bytes`, `content_hash`, `content_hash_of_files` | charter §7's hash rule, in one place |
| `domain/artifact.py` | `ArtifactKind`, `ArtifactFile` (**C-1**), `Artifact` (**C-2**) | the records |
| `domain/registry.py` | `TypeSpec`, `ARTIFACT_TYPE_SPECS`, `spec_for`, `spec_for_directory` | the single place a new artifact type is added |
| `domain/metadata.py` | `ArtifactMetadata`, `Collection`, `LibraryMetadata` | DEC-8: here rather than in T-4, so T-3 ∥ T-4 |
| `domain/repository.py` | `ArtifactRepository` protocol (**C-4**) | declared with the vocabulary so T-5 implements a frozen signature rather than inventing one |

`domain/__init__.py` is left as T-1 wrote it. Re-exporting the whole vocabulary there would create a
second list that drifts from the modules; consumers import from the module that owns the type.

## Decisions taken inside the task

1. **Severity is derived from the code, and the field is checked against it.** C-3 freezes `severity`
   as a field on the finding, and 04's SPA reads it there — so the field stays. But charter §8 fixes
   the severity *per code*, and two places holding one decision drift. `ValidationCode.severity`
   is the single source; `ValidationFinding.__post_init__` rejects a finding whose `severity`
   contradicts its `code`, and `ValidationFinding.for_code(...)` is the constructor that cannot get it
   wrong. A test asserts the register matches charter §8 code by code.
2. **`is_valid` is `no finding of severity ERROR`** — charter §8, verbatim. A V6 WARNING never makes an
   artifact invalid; that is the whole reason `Severity` exists.
3. **The content hash has exactly one implementation.** `content_hash_of_digests((path, sha256hex), …)`
   sorts and frames; `content_hash((path, bytes), …)` and `content_hash_of_files(ArtifactFile, …)`
   both delegate to it. Two hashing routines would agree until they didn't. Entries are
   length-prefixed so no path/content boundary is ambiguous — the hash is rename-sensitive by
   construction. Mode, mtime and skipped paths are never fed in (**R9**, charter §7).
4. **`updated_at` must be timezone-aware**, enforced in `__post_init__`. R5 gives it two derivations
   (git commit date, or max mtime with `is_dirty` set) and both are expressible as one aware
   `datetime`; a naive value from one path and an aware value from the other would raise inside T-6's
   sort, far from the cause.
5. **`frontmatter` is stored as a `MappingProxyType`**, wrapped on construction, so "frozen" is true of
   the mapping too and not only of the reference to it.
6. **Paths.** `Artifact.path` is the artifact root relative to the library root (`skills/<name>`, or
   `agents/<name>.md` for a file artifact). `ArtifactFile.path` is relative to that root — for a file
   artifact the single entry is its own basename. `TypeSpec` owns both derivations.
7. **Failures here raise `ValueError`**, never a project exception. The error taxonomy is C-6 and
   charter §9 says a code is added to the contract before it is emitted; these are programming errors
   in the callers, not user-facing conditions.

## Verification

The gate, whole, from the repo root (charter §5, plan §9), formatter first, never path-scoped (**L2**):

```
export PATH="$HOME/.local/bin:$PATH"   # L9
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

`domain-is-pure` must stay KEPT; the whole layer imports only the standard library.

## Mutation check — assertion named in advance

Reverse the sort of the content-hash input (`sorted(...)` → `sorted(..., reverse=True)` in
`content_hash_of_digests`).

**Must fail:** `tests/domain/test_hashing.py::test_content_hash_is_stable_across_insertion_order`.
That test pins a **golden digest** as well as asserting order-independence, and the golden is what
makes the mutation observable: a reversed sort is still deterministic and still order-independent, so
an equality-only test would sail straight through it. The two assertions are one claim — the hash does
not move.

**Independence:** no other test may go red. Rename-sensitivity, content-sensitivity and the
`content_hash_of_files` agreement test all survive, because they compare two digests computed under
the same ordering rule.

**Second guard, stated for the record:** if `is_valid` were redefined as "no findings at all",
`tests/domain/test_artifact.py::test_warning_finding_does_not_make_an_artifact_invalid` fails. It
carries its own positive control (an ERROR finding in the same test does invalidate), per charter §10.

## Out of scope

No validation *logic* (every rule V1–V7 is T-3's), no reader, no scanner, no repository
implementation, no use case, no adapter. No dependency change. No commit.

---

# T-3 backend task plan — `RawArtifact` and the pure assembler (V1–V7)

Written before the first edit. Task: phase-1 / initiative 01-store-and-read-path / T-3.
Layer: `domain/` only. Runs concurrently with T-4 (`infrastructure/library_yaml.py`); no shared file.

## Understanding

Every validation rule in charter §8 becomes a pure function over a value, ahead of the repository.
The scanner (T-5) will hand the assembler a `RawArtifact` — what it found on disk — and get a finished
`Artifact` back. No rule may live in infrastructure, and no test of a rule may touch a disk. This is
DEC-1: the superseded plan built the repository first and reopened it twice to retrofit validation.

## The seam

| File | Holds |
|---|---|
| `domain/raw.py` | `SkipReason`, `SkippedPath`, `RawEntry`, `RawArtifact` — the scanner's output value |
| `domain/assembly.py` | `assemble_artifact`, `assemble_library`, `AssembledLibrary` — every rule V1–V7 |

`RawArtifact` carries: `type`, `name`, `files: tuple[ArtifactFile, ...]` (C-1 reused — the scanner has
already hashed and sized each file, so the assembler needs no bytes), `skipped: tuple[SkippedPath, ...]`,
`entry: RawEntry | None` (the parsed frontmatter and body of the entry document, `None` when there is
none), `updated_at` and `is_dirty` (R5, derived by the scanner, passed through).

`kind`, `path` and the entry's own path are **derived from the registry**, never carried on the raw
value — a second source of truth for the disk layout is how a scanner and a validator drift.

## Rule placement — and why V4 joins V7 above the artifact

Six rules are decidable from one artifact: **V1, V2, V3, V5, V6**. `assemble_artifact(raw, metadata)`
implements those.

**V4 and V7 both need the whole library in view** — "resolves to nothing" is a statement about the set of
ids that exist. The task brief singles out V7; V4 has the identical information need, so both live in
`assemble_library(raws, metadata) -> AssembledLibrary`, which assembles every artifact and then resolves
ids against the set it just built. V4 is *about* an artifact, so it is appended to that artifact's
findings; V7 is about `library.yaml`, so it lands in `AssembledLibrary.findings`.

## Decisions taken inside the task

1. **Skipped paths arrive; they are never discovered.** R6 — the assembler turns each `SkippedPath` into
   one V6 WARNING. It never touches a filesystem to find one. `SkipReason` is closed
   (`SYMLINK`, `EDITOR_SWAP`, `VENDOR_TREE`, `OTHER`) and shapes the message only.
2. **V1 is "the entry document is absent"**, generalised from charter §8's "a skill directory with no
   `SKILL.md`" so the rule is total over the type registry rather than hard-coding one type's filename.
3. **V5 is suppressed when V1 fired.** A missing `SKILL.md` means every required key is missing; emitting
   V1 plus one V5 per key reports one fault as three. The suppression carries a positive control.
4. **V2 is suppressed when the `name` key is missing or empty** — that is V5's fault, not a disagreement.
5. **V3's exemption reads `superseded_by` from `library.yaml` first, then from the entry's frontmatter.**
   The exemption is a property of *being a redirect stub*; a library with no `library.yaml` must still get
   it, or V3 floods (L5 — seven findings on the real library). `Artifact.superseded_by` is populated from
   the same resolution, so V3, V4 and R8's ranking all read one value. **Flagged to the delivery lead**:
   T-2's `ArtifactMetadata` documents `library.yaml` as the source and is silent on frontmatter.
6. **Citations are extracted from the entry body only**, deduplicated, and reported in first-appearance
   order — one finding per distinct missing path, so a stub repeating a path does not inflate the count.
7. **R8 holds:** nothing here drops an artifact. `assemble_library` returns every input, superseded or not.
8. **Severity is never passed by hand** — `ValidationFinding.for_code` throughout (R13).

## Not implemented, and why

Charter §7 says two artifact names differing only by case are "a V-error", but the §8 register has no
code for it and charter §9 forbids emitting a code before it is in the contract. **Not emitted; reported
to the delivery lead as an open question.**

## Verification

The gate, whole, from the repo root, formatter first, never path-scoped (**L2**):

```
export PATH="$HOME/.local/bin:$PATH"   # L9
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

`domain-is-pure` stays KEPT and `tests/domain/test_purity.py` covers the two new modules — it discovers
them by `pkgutil`, and gains an explicit assertion that both are in the discovered set so a module that
never imports cannot be silently uncovered (**L13**).

## Mutation check — assertions named in advance

Delete the `superseded_by` exemption from V3.

**Must fail:** `tests/domain/test_assembly.py::test_redirect_stubs_produce_seven_v3_findings_without_the_exemption`
— the two-stub fixture, reporting **seven**.
**Must stay green:** `tests/domain/test_assembly.py::test_a_missing_reference_on_a_live_artifact_is_a_v3_error`
— a genuine V3 on a non-superseded artifact. Both going red would mean the exemption is implemented as
"skip V3 entirely" for the wrong set of artifacts.

**How seven is made deterministic** (L12): the fixture mirrors the real library's *two* stubs. Stub A's
body cites six distinct missing `references/*.md` paths (one of them twice, to prove deduplication);
stub B's cites one. Each stub's missing-path list is pinned as a **golden literal** and its count asserted
separately (6 and 1); seven is then the asserted sum of two pinned parts, not a number that happened to
come out right.

## Out of scope

No reader, no scanner, no repository, no use case, no adapter, no file I/O. Nothing under
`infrastructure/` (T-4's territory this wave). No dependency change. No commit.

---

# T-4 backend task plan — the `library.yaml` reader

Written before the first edit. Task: phase-1 / initiative 01-store-and-read-path / T-4.
Layer: `infrastructure/` only. Produces **C-2**'s neighbours from T-2 (`LibraryMetadata`); opens **C-6**.
Runs concurrently with T-3 (`domain/assembly.py`); shares no file with it except this plan.

## Understanding

`library.yaml` is the only place a user's hand-authored metadata enters the system. The reader turns it
into the `LibraryMetadata` T-2 froze, and its whole job is to make a typo *loud and located* instead of
turning it into a silent wrong answer. Four behaviours, four tests: absent file is empty metadata;
malformed YAML raises with a **line number**; a null-valued key has a decided, defended outcome; a scalar
where a list is expected is diagnosed rather than coerced or crashed on.

**The seam.** Shape only. Whether `skill/delivery-lead` exists on disk is V7 and belongs to T-3, which
sees the whole library at once. A `LibraryMetadata` naming an artifact that does not exist is *correct*
output from this reader. The reader likewise does not check that a key parses as `<type>/<name>` —
`parse_artifact_id` returns `None` for exactly that case so T-3 can report it as V7.

## Approach — file by file

| File | Holds | Why separate |
|---|---|---|
| `infrastructure/errors.py` | `ErrorCode` (StrEnum, closed), `HarnessLibraryError` (base), `LibraryYamlError` | charter §9 / **C-6**: one base exception, stable string codes, a code added to the contract before it is emitted. This is the taxonomy's first entry. |
| `infrastructure/_yaml_document.py` | quarantined PyYAML use; a typed node model (`YamlScalar`/`YamlSequence`/`YamlMapping`) carrying 1-based line and column; `compose_document()` | PyYAML ships no type hints, so its surface is `Any`. Confining it to one module keeps the rest of the layer strictly typed instead of spraying `cast` through the reader. |
| `infrastructure/library_yaml.py` | `LIBRARY_YAML_FILENAME`, `read_library_metadata(library_root)` | the reader itself, written entirely against the typed node model |
| `tests/infrastructure/test_library_yaml.py` | real files under `tmp_path` (charter §10) | infrastructure is tested against a real filesystem, never a fake |

## Decisions taken inside the task

1. **`yaml.compose(..., Loader=yaml.SafeLoader)`, not `yaml.safe_load`.** R1's stated concern is a loader
   that can construct arbitrary Python objects from a file that arrives out of a user's repository.
   `compose` constructs *nothing* — it stops at the node tree — so it is strictly safer than `safe_load`,
   not a relaxation. It is also the only way to keep the **line number** for a *shape* error: `safe_load`
   discards every position, so `tags: process` could be diagnosed but never located, and a diagnosis with
   no location is half of what this task exists to deliver. A test pins the safety property by feeding the
   reader a `!!python/object/apply:os.system` tag and asserting it is rejected, not executed.
   **Flagged to the delivery lead** as a reading of R1, not a departure from it.
2. **One error code, `LIBRARY_YAML_INVALID`, covering both syntax and shape.** Not `…_MALFORMED`:
   "malformed" reads as syntax-only, which would force a second code the moment `tags: process` is
   diagnosed, and the first name would then be wrong. Nothing downstream branches differently between a
   colon in the wrong place and a scalar where a list belongs — both are "your `library.yaml` is not
   usable, here is the line" and both map to one CLI exit code and one HTTP status in 03. Per
   `contracts.md`, a distinction no caller acts on does not go in a contract.
3. **A null-valued key is the empty form of its type — accepted, not an error.** `tags:` → `()`,
   `superseded_by:` → `None`, `artifacts:` → no artifacts, an entry `skill/foo:` → the empty declaration.
   YAML's only idiom for "nothing here" *is* a bare key; rejecting it would fail a file whose meaning is
   unambiguous, and this product exists to remove silent wrong answers, not to add gratuitous hard ones.
   The distinction from absent is preserved where it could bite: null is never coerced into a *non-empty*
   value — `tags:` yields an empty tuple, never a one-element tuple holding `None`.
4. **An unknown key is an error, at every level.** `tag:` for `tags:`, `member:` for `members:`,
   `artifact:` for `artifacts:` — silently ignoring these is precisely how a user's tags vanish with no
   explanation. "Is this key well-formed" is the shape question this reader owns.
5. **Errors carry `path`, `line` and `column` as fields**, not only inside the message. `line`/`column`
   are `int | None`, present-and-null, null only when the failure has no position at all (an unreadable
   or non-UTF-8 file). Every parse and shape failure sets them.

## Verification

The gate, whole, from the repo root, formatter first, never path-scoped (**L2**), `docs/` clean (**L8/R11**):

```
export PATH="$HOME/.local/bin:$PATH"   # L9
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

## Mutation check — assertions named in advance

Make the malformed-YAML path return `LibraryMetadata.empty()` instead of raising.

**Must fail:** `tests/infrastructure/test_library_yaml.py::test_malformed_yaml_raises_with_the_line_number`.
**Must stay green:** `tests/infrastructure/test_library_yaml.py::test_absent_file_is_empty_metadata`.
If both go red the reader is conflating "no file" with "bad file", which is the confusion the task exists
to prevent.

## Out of scope

No scanner, no repository, no use case, no adapter, no validation rule (V1–V7 are T-3/T-5). Nothing under
`domain/`. No dependency change, no `pyproject.toml` edit, no commit.

---

# T-4b backend task plan — errors to `domain/`, V8 and V9

**Scope:** three corrections closing findings raised by the authors of T-3 and T-4. No scanner, no
repository, no use case, no adapter — T-5's territory is untouched.

## Understanding

1. `infrastructure/errors.py` moves to `domain/errors.py`. T-4's author flagged it: `application/`
   and `infrastructure/` are independent siblings under `layered-architecture`, so an
   application-layer error cannot inherit a base that lives in `infrastructure/`. Doing the move
   before a second `ErrorCode` exists is why it is first (R17).
2. **V8** — two artifacts of one type whose names differ only by case. Charter §7 asserted the rule
   and §8 had no code for it, so T-3 correctly refused to invent one. §8 now carries it (R19).
3. **V9** — a duplicate key in `library.yaml`. Today it is silently last-wins (R20).

## The one real obstacle in correction 1, and how it is resolved

`LibraryYamlError` carries `path: Path`, and `pathlib` is in `tests/domain/test_purity.py`'s
`FORBIDDEN_ROOTS`. Moving the module unchanged fails that guard — correctly, because the guard is
what keeps `domain/` from acquiring a filesystem.

Three ways out were weighed:

* import `Path` under `if TYPE_CHECKING:` — routes around the guard, and teaches the next agent that
  the guard is optional. Rejected.
* drop `pathlib` from `FORBIDDEN_ROOTS` — weakens a mechanism to fit one field. Rejected.
* **`LibraryYamlError.path` becomes `str`.** Taken. The field is the user-facing *location of the
  fault*; `_render` already reduced it to `str(path)`, and no consumer does anything else with it.
  The field stays present-and-absolute; only its Python type narrows. `path`, `line` and `column`
  remain fields as well as message text.

This changes one existing assertion — see "Existing tests changed" below.

## Where V8 is decided, and how it is attached

Library level, in `assemble_library`, beside V4 and V7: "these two names collide" is a statement
about the set of names that exist and cannot be decided from one artifact. Artifacts are grouped by
`(type, name.casefold())`; a group holding more than one *distinct* name is a collision.

The finding is attached **to every artifact in the group**, the way V4 is attached, not to the
library. A user reading the report on `skill/Delivery-Lead` must be able to see what it collides
with, so each finding names the whole colliding set, sorted, so two scans report identically. It is
not a library-level finding because — unlike V7 — there *are* artifacts to hang it on, and hanging it
only on the library would make `hl show skill/Delivery-Lead` silent about the fault.

Different types do not collide: `skill/foo` and `agent/foo` are distinct artifacts living in
distinct directories, and the grouping key carries the type for exactly that reason.

## Where V9 is raised — a finding, not a raise

**V9 is a finding, emitted by the assembler at library level, not a `LibraryYamlError` from the
reader.** The reader *observes* the duplication and records it; it does not decide severity.

The defence, in order of weight:

1. Charter §8 is the register of *findings*, and `is_valid` is defined there as "no finding of
   severity ERROR". A rule that lives in that table and can never appear in a report has no way to
   make `is_valid` false. R13 (`for_code`) points the same way.
2. **V7 is the precedent.** A `library.yaml` id that resolves to nothing is a fault of the document,
   and it is a finding. A duplicate key is a fault of the same document. Treating one as a finding
   and the other as a fatal raise puts a distinction in the contract that no caller acts on.
3. The reader's raise-seam is for documents that are *unusable* — cannot be parsed, or a value whose
   meaning cannot be determined. A duplicate key is fully parsed and fully understood: both blocks
   are visible. It does not meet that bar.
4. `hl validate` is the consumer. A raise reports the duplicate and nothing else about the library;
   a finding reports it alongside every other fault and still exits non-zero, because V9 is an ERROR.

This mirrors **V6's** existing shape exactly: the scanner records `SkippedPath` values, the assembler
turns each into a finding. Here the reader records `DuplicateKey` values and the assembler turns each
into a V9. Observation in `infrastructure/`, severity and wording in `domain/`.

The retained value stays last-wins and is now documented as such. Neither block can be preferred on
merit — first-wins discards the second block's tags exactly as last-wins discards the first — so the
answer is not a better merge but a loud ERROR saying the document is wrong. Nothing downstream should
trust a merge from a library that is not `is_valid`.

**Breadth:** the rule fires on *any* duplicate key in the document, which is what charter §8's
headline says ("a duplicate key in `library.yaml`"); artifact ids and collection keys are its two
named instances. A duplicated `tags:` inside one entry loses data the same way and would otherwise be
a hole in a rule whose whole purpose is to close that hole. One recursive pass over the composed node
tree, run *after* interpretation so a genuinely unusable document still raises exactly as before.

## Approach — file by file

* `src/harness_library/domain/errors.py` — moved from `infrastructure/`, `path` narrowed to `str`,
  placement note replaced with why it lives here.
* `src/harness_library/infrastructure/errors.py` — deleted.
* `src/harness_library/infrastructure/_yaml_document.py`, `library_yaml.py` — import from
  `domain.errors`; convert the path at each raise site.
* `src/harness_library/domain/validation.py` — `V8`, `V9` members and their register rows.
* `src/harness_library/domain/metadata.py` — `DuplicateKey`, and `LibraryMetadata.duplicate_keys`.
* `src/harness_library/infrastructure/library_yaml.py` — collect duplicates from the node tree.
* `src/harness_library/domain/assembly.py` — `_apply_v8` and `_check_v9`.
* `tests/domain/test_purity.py` — `errors` added to `EXPECTED_MODULES` (**L13**).

## Existing tests changed

* `tests/infrastructure/test_library_yaml.py::test_malformed_yaml_raises_with_the_line_number` and
  `::test_the_error_is_a_harness_library_error_with_a_stable_code` — `path` compared as `str`. What
  is no longer guaranteed: that the error carries a `Path` object. The absolute location it names,
  and its presence in `str(error)`, are still asserted.
* `tests/domain/test_assembly.py::test_every_finding_takes_its_severity_from_the_register` — asserts
  every code in `ValidationCode` is reachable from this layer, so its scenario gains a case collision
  and a duplicate key. Weakening it to "V1–V7" instead would have been the wrong repair.
* `tests/domain/test_validation.py` — `CHARTER_SECTION_8` gains the two rows.

## Verification

The gate, whole, from the repo root, formatter first, never path-scoped (**L2**), `docs/` clean
(**L8/R11**):

```
export PATH="$HOME/.local/bin:$PATH"   # L9
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

## Mutation checks — assertions named in advance

**(a) Neuter V8.** Make the collision grouping key case-*sensitive*, so no group ever holds two
distinct names.
**Must fail:** `tests/domain/test_assembly.py::test_two_names_differing_only_by_case_are_a_v8_error`.
**Must stay green:** `tests/domain/test_assembly.py::test_the_same_name_under_two_types_is_not_a_collision`
— `skill/foo` and `agent/foo` are distinct artifacts and must remain so.

**(b) Restore V9 to last-wins.** Stop collecting duplicate keys in the reader.
**Must fail:** `tests/infrastructure/test_library_yaml.py::test_an_artifact_id_declared_twice_is_recorded_as_a_duplicate`.
**Must stay green:** `tests/infrastructure/test_library_yaml.py::test_a_key_declared_once_records_no_duplicate`
— a single occurrence is still read correctly and reports nothing.

## Out of scope

No scanner, no repository, no use case, no adapter. No dependency change, no `pyproject.toml` edit,
no commit. Nothing under `docs/` except this section.

---

# T-5 backend task plan — the scanner, the repository, and the fixture library

Written before the first edit. Task: phase-1 / initiative 01-store-and-read-path / T-5.
Layer: `infrastructure/` only, plus `tests/**`. Depends on T-3 (assembler) and T-4 (reader), both
landed. Nothing under `domain/` is touched — if this task wants to, the seam is wrong (DEC-1).

## Understanding

Everything above this task is provably correct against literals and provably blind to the disk. T-3's
own test module says so: it cannot prove the scanner *records* a symlink as skipped, only that a
recorded skip becomes a V6 warning. T-5 is where every one of those assumptions meets a real
filesystem. The deliverable is three things — a scanner that produces `RawArtifact` values, a
repository that composes scanner + reader + `assemble_library` behind contract C-4, and a **committed
fixture library** (P-4) that reproduces every failure charter §8 exists to catch.

## The seam

| File | Holds |
|---|---|
| `infrastructure/timestamps.py` | Ruling R5. `Timestamp`, the `ArtifactTimestamps` protocol, `GitTimestamps`, `FixedTimestamps` |
| `infrastructure/scanner.py` | `scan_library(root) -> tuple[RawArtifact, ...]` — the walk, the skip decisions, hashing, entry parsing |
| `infrastructure/repository.py` | `FilesystemArtifactRepository` — contract C-4 over a held snapshot |
| `tests/fixtures/library/**` | The committed fixture library (P-4). Never deleted — charter §10 |

`subprocess` lives in `timestamps.py` and nowhere else. This is the module lesson L13 predicted would
be written into `domain/` next to the field it fills; it is not, and `tests/domain/test_purity.py` is
left exactly as it is, still arming `subprocess` in `FORBIDDEN_ROOTS`.

## R5, concretely

`GitTimestamps` is constructed once per scan and asks git two questions up front, not per artifact:

1. `git -C <root> rev-parse --show-toplevel --show-prefix` — is this a work tree, and where does the
   library root sit inside it. A non-zero exit (no repository, or no `git`) means **every** artifact
   takes the mtime path.
2. `git -C <root> status --porcelain -z -uall -- .` — the set of paths with uncommitted changes, once.
   `-z` because `core.quotePath` mangles non-ASCII names in the default format, and rename records
   carry a second path field that the parser consumes explicitly.

Then per artifact: dirty (by path prefix) → mtime, `is_dirty=True`. Otherwise
`git log -1 --format=%cI -- :(literal)<path>`; empty output → mtime, `is_dirty=True`. The pathspec is
the **artifact root**, so "the last commit touching the artifact's paths" is one question, and
`:(literal)` stops a name containing a glob character from being read as a pattern.

`is_dirty` is set on **both** fallback paths, which is what `Artifact.is_dirty`'s docstring already
promises: it means "`updated_at` came from mtime rather than from git".

mtime fallback = max mtime over the artifact's **scanned files**, or the artifact root's own mtime
when it has none (a V1 directory has no files, and git cannot track an empty directory either).

## Skip decisions (R6 and charter §8)

Checked in this order, because `is_dir()` and `is_file()` follow links and `is_symlink()` does not:

| Test | `SkipReason` |
|---|---|
| `is_symlink()` | `SYMLINK`, detail = the raw `readlink` target. **Never followed, never hashed** |
| directory named `node_modules`, `.venv`, `venv`, `vendor` | `VENDOR_TREE`, and not descended |
| directory named `.git` | `OTHER` — a nested repository is not a vendor tree, and `OTHER` exists so a scanner never has to choose between silence and a domain change |
| `*.swp` `*.swo` `*.swn` `*~` `.#*` `#*#` | `EDITOR_SWAP` |
| not a regular file (fifo, socket, device) | `OTHER` |
| unreadable (`OSError`) | `OTHER`, detail = the errno string |

Children are sorted by name at every level, so `files` and `skipped` are deterministic and two scans
of one library produce the same report — the ordering discipline V7, V8 and V9 already follow.

`is_text` is decided per file (charter §7): a NUL byte or a failed UTF-8 decode makes it binary.
Binary is stored, hashed and readable; it is never searched, which is T-6's concern.

## Decisions taken inside the task

1. **The snapshot is taken once and held.** C-4 calls `list_all()` a point-in-time snapshot and
   charter §12 says concurrent processes each hold their own. Re-scanning per call would let `get()`
   disagree with `list_all()` inside one CLI run, and would re-run git per call. A new repository is
   a new snapshot.
2. **`read_bytes` validates in three stages, shape first.** Absolute path, or any `..` component →
   `ValueError`, before anything touches the disk. Then membership in the snapshot's file set →
   `FileNotFoundError`. Then a resolved-containment check and a symlink refusal as defence in depth.
   Shape is checked first so the traversal test is aimed at the traversal guard and not at the
   membership check that would incidentally also reject it.
3. **No new `ErrorCode`.** Charter §9 forbids emitting a code that is not in the contract, and
   `domain/errors.py` is out of bounds for this task. Unknown id, unknown path and a traversal
   attempt therefore raise plain `KeyError` / `FileNotFoundError` / `ValueError`. **Flagged** — T-7
   maps errors to exit codes and will want a ruling.
4. **A malformed frontmatter block is not a raise.** The entry document exists, so V1 would be a lie;
   there is no code for "unparseable frontmatter"; so the entry is carried with an empty frontmatter
   mapping and the whole text as body, which fires V5 for every required key. **Flagged.**
5. **A symlinked artifact *root* is not followed and not scanned.** R6 says never followed. Emitting
   a `RawArtifact` for it would fire V1 — a false ERROR against a symlinked skill that loads
   perfectly — and inventing that semantics is not a task-level call. Behaviour is pinned by a test
   so it is visible rather than accidental. **Flagged as an open question.**
6. **`library_findings()` is additive, not a change to C-4.** V7 and V9 land in
   `AssembledLibrary.findings` and would otherwise be unreachable from the read path, so F-4 could
   never report them. C-4's five methods are untouched. **Flagged.**

## The fixture library, and what is deliberately not in it

`tests/fixtures/library/` holds every case in the task brief: a skill with no `SKILL.md` (V1), a
frontmatter name disagreeing with its directory (V2), a body citing a missing reference (V3), **two**
redirect stubs whose citations must not fire V3 (6 + 1 = the seven of L5), an editor swap file, a
nested `node_modules`, a symlink escaping the artifact root, a binary PNG that is not valid UTF-8,
and a `library.yaml` exercising tags, collections and supersession — including one entry and one
collection member that resolve to nothing (V7) and one `superseded_by` that does not resolve (V4).

**V8 and V9 are proven against real files under `tmp_path`, not in the committed fixture.** Neither is
in the brief's fixture list, and each carries a cost the committed tree should not: V8 needs two
directories differing only by case, which **cannot be checked out on a case-insensitive filesystem**
at all; V9 needs a duplicated key in the one `library.yaml` whose tag and collection behaviour the
rest of the suite reads as a golden literal. `tmp_path` files are real files, so the guarantee is the
same and the repository stays cloneable on macOS.

**Fixture timestamps are never asserted.** The fixture lives inside this repository, so it is dirty
while uncommitted and clean once the delivery lead commits it — `updated_at` and `is_dirty` on it
would flip at the commit boundary. Fixture tests assert only that `updated_at` is timezone-aware. R5
itself is proven in a purpose-built repository under `tmp_path` where the test owns the commit dates.

## Verification

The gate, whole, from the repo root, formatter first, never path-scoped (**L2**, **L9**):

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

`git status --porcelain docs/` must show only this section (**L8** — `ruff format` rewrites Markdown
code fences and names no files when it does; `docs/` is in ruff's `extend-exclude`, which is the
mechanism, but it is confirmed rather than assumed).

## Mutation check — assertion named in advance

Stop the scanner recording skipped paths: drop each decision on the floor instead of appending a
`SkippedPath`.

**Must fail:** `tests/infrastructure/test_repository.py::test_a_real_symlink_becomes_a_v6_warning_on_the_assembled_artifact`
— a real symlink, in a real directory, read through the repository. This sits **above** the fake: it
is driven from the committed fixture tree, not from a hand-built `SkippedPath` list, which is the
exact gap that let the superseded plan ship V6 unwired.
**Must stay green:** `tests/domain/test_assembly.py::test_a_symlink_is_reported_as_a_v6_warning_and_never_blocks`
— T-3's literal-driven test, which is correctly blind to the scanner and must remain so.

## Out of scope

No use case, no CLI, no MCP server. Nothing under `domain/` — including `tests/domain/test_purity.py`,
whose expected list does not change because no domain module is added. No dependency change, no
`pyproject.toml` or `uv.lock` edit. No write outside the repository, and nothing under `~/.claude/`.
No commit.

---

# T-6 backend task plan — the read use cases, collections, and the C-7 DTOs

Written before the first edit. Task: phase-1 / initiative 01-store-and-read-path / T-6.

## Understanding

Deliver `application/read/`: seven use-case **functions** over contract C-4, and the Pydantic
payloads (contract C-7) that the CLI's `--json`, the MCP server and initiative 03's HTTP API all
render from. This is the last layer where a behaviour is decided — T-7 and T-8 render and nothing
more — so filtering, every ordering including ruling R8's ranking, the search cap and ruling R24's
error translation all land here rather than above.

## The seam

`application/` may not import `infrastructure/`, so the repository arrives as the `ArtifactRepository`
protocol and every test runs against a hand-written fake with zero disk access.

**What this layer is blind to, stated once (charter §10).** The fake cannot prove that a real scan
records a symlink, that `updated_at` came from git rather than mtime, that `library.yaml` parses, or
that a real binary file fails to decode. All four are proven at the infrastructure level against real
files (T-5). What this layer decides, and therefore what these tests can prove, is: which artifacts a
filter admits, what order they come back in, what is searched and what is skipped, which findings
reach a report, and which builtin becomes which error code.

## The one change below this layer, and why

`domain/repository.py` did not declare `library_findings()`. Ruling R23 and plan §6 both make it part
of contract C-4 — the delivery lead amended C-4 in the record at `f1102cb` — but the protocol file
still carried T-5's five methods, because T-5 correctly added the method to its implementation only
and left amending the contract to the delivery lead. The amendment had been made; the code had not
caught up. Adding the method here transcribes an existing ruling rather than making a new one, and
without it the validate use case cannot reach V7 or V9 at all under `mypy --strict`. **Flagged in the
report.** One existing test changed as a direct consequence — see below.

## Approach — file by file

| File | Holds |
|---|---|
| `read/queries.py` | `SortKey`, `ArtifactFilter` — what a caller *asks* for. Frozen dataclasses: constructed in Python by an adapter, not parsed from an untrusted document |
| `read/dtos.py` | Contract C-7 — what a caller gets *back*. Pydantic, frozen, `extra="forbid"` |
| `read/_access.py` | Ruling R24 in one place: the repository's builtins become the taxonomy |
| `read/artifacts.py` | `list_artifacts`, `get_artifact`, `get_artifact_file`, plus the shared `select_artifacts` and `sort_artifacts` |
| `read/search.py` | `search_artifacts`, rulings R4 and R25, the cap |
| `read/validation.py` | `validate_library`, rulings R22 and R23 |
| `read/collections.py` | `list_collections`, `get_collection` |
| `read/__init__.py` | Re-exports the whole surface, so an adapter imports one module path |

## Decisions taken inside the task

1. **`UnicodeDecodeError` is caught before `ValueError`, and it is load-bearing.** The former is a
   subclass of the latter, so the obvious handler order reports every binary file as a malformed
   path — the wrong code, the wrong HTTP status in initiative 03, and a diagnosis aimed at the
   caller's request rather than at the file. Stated in `_access.py` rather than left to be
   rediscovered; no type checker catches the reordering.
2. **Ruling R8 is the *primary* sort key, above the requested one.** A superseded artifact ranks
   below every live artifact under `name`, `updated` and `size` alike. Sorting only by the requested
   key would interleave a retired artifact among current ones under `--sort size`, which is the
   presentation R8 rejects. Every key ends in the artifact id, so the order is total.
3. **`R25` is satisfied structurally, not by wording.** `is_searchable` reads the *path* and nothing
   else, and runs before anything is read. A non-markdown file therefore cannot be reported as
   undecodable whatever its bytes are, so the 184 KB HTML asset can only ever carry
   `not_a_markdown_reference`. A second reason, `unreadable_as_text`, exists for a `.md` reference
   whose bytes contradict the scan — reachable only past the path test, which is what keeps it from
   becoming the "binary" reason R25 rejects. **Flagged**: C-5 named this field `skipped_binary`;
   R25 supersedes that wording, and the field is `skipped`.
4. **An unknown collection key raises; an unknown tag does not.** A collection key is *declared* in
   `library.yaml`, so an unrecognised one is a mistake and charter §13's fail-loudly posture applies.
   A tag is free-form, so an unused one is indistinguishable from a misspelt one.
5. **`get_artifact` never raises on the artifact's own defects.** A skill with no `SKILL.md`, and an
   entry document that does not decode, both come back with `entry_text` null and their findings
   attached. Feature F-2 exists for exactly that case.
6. **A path outside the snapshot is handed back to the repository to classify.** T-5 checks shape
   before membership deliberately, so a traversal attempt is `INVALID_FILE_PATH` and a typo is
   `FILE_NOT_FOUND`. Restating that rule here would be a second opinion that drifts.
7. **The validation report lists only artifacts carrying findings**, with `artifact_count` covering
   everything checked. That is what makes "this rule does not fire on a clean artifact" an assertion
   a test can make.
8. **Six new `ErrorCode` members**, each added to `domain/errors.py` with its class in the same edit,
   before any of them was emitted (charter §9): `ARTIFACT_NOT_FOUND`, `FILE_NOT_FOUND`,
   `INVALID_FILE_PATH`, `FILE_NOT_TEXT`, `COLLECTION_NOT_FOUND`, `INVALID_QUERY`.

## Existing tests changed

`tests/domain/test_repository.py` — its `FakeRepository` gained `library_findings()`, because the
protocol it is asserted to satisfy now declares it. Nothing is no longer guaranteed: the sibling
positive control (`ReadTextOnlyRepository` must *not* satisfy the protocol) is untouched and still
passes, so the `isinstance` assertion is still capable of failing. No test was deleted or weakened.

## Verification

The gate, whole, from the repository root, formatter first, never path-scoped (**L2**, **L9**):

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

`git status --porcelain docs/` must show only this section (**L8**).

## Mutation checks — assertions named in advance

**(a) Remove the search result cap.**
Must fail: `tests/application/test_search.py::test_a_result_set_above_the_cap_is_truncated`.
Must stay green:
`tests/application/test_search.py::test_an_under_cap_search_returns_every_match_and_is_not_truncated`
— the cap must bound a large answer without clipping a small one.

**(b) Make `validate_library` ignore `library_findings()`.**
Must fail:
`tests/application/test_validation.py::test_a_library_level_v7_reaches_the_report_and_makes_the_library_invalid`.
This is ruling R23's whole point: V7 and V9 exist only at library level, and a report that cannot
reach them leaves two rows of charter §8 unable to fail anything.

## Out of scope

No CLI, no MCP server, no HTTP concern, no composition root. Nothing under `infrastructure/`, and
nothing under `domain/` beyond `errors.py` and the one protocol method above. No dependency change,
no `pyproject.toml` or `uv.lock` edit. No write outside the repository, nothing under `~/.claude/`.
No commit.
