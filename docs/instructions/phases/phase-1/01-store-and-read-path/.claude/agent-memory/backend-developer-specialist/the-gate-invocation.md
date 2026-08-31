---
name: the-gate-invocation
description: the exact charter §5 gate command, its prerequisites, and why the architecture contracts are a subprocess test
metadata:
  type: project
---

```
export PATH="$HOME/.local/bin:$PATH"     # see [[uv-toolchain-bootstrap]]
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Run whole, from `/project/harness-library`. Run `uv run ruff format .` (no `--check`) once over new
files first, or the first attempt dies on formatting before mypy or pytest ever run — and a run that
stops at type-check is **not** green.

**import-linter, verified by mutation at T-1:**

- `layers` is ordered **high → low**; the first entry may import everything below it. `|` between
  siblings makes them *independent* of each other. `application | infrastructure` is deliberate:
  in Mode A infrastructure implements domain protocols and neither may reach into the other. Proved
  by probe — `infrastructure -> application` breaks `layered-architecture`.
- A `domain -> application` import breaks **both** `layered-architecture` and `domain-is-pure`.
  `mcp-is-read-only` stays KEPT, so the three contracts are independent.
- `tests/test_architecture.py` shells out to the **`lint-imports` console script** with `cwd` pinned
  to the repo root. Never `python -m importlinter.cli` — it resolves config relative to cwd and
  behaves differently under pytest's rootdir. Config lives in `pyproject.toml`, never `setup.cfg`.
- The test asserts each contract is reported `KEPT` **by name**, not just exit 0: deleting a contract
  from the config also produces exit 0, so an exit-code-only test would pass a dropped contract.

**`tests` importability:** `pythonpath = ["src", "."]` plus `tests/__init__.py` in every subpackage.
Without the `"."`, the failure names a module that visibly exists on disk.
