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
