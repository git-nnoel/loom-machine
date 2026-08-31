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
