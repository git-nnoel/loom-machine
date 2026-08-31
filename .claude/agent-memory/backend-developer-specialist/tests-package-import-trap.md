---
name: tests-package-import-trap
description: Plan 1's test files import `tests.application.fakes`, which fails unless tests/ is a real package and the repo root is on pythonpath
metadata:
  type: project
---

Cross-test imports of the form `from tests.application.fakes import ...` and
`from tests.infrastructure.conftest import library_root` are used throughout the Plan 1 test suite. They
fail with `ModuleNotFoundError` under the planned `[tool.pytest.ini_options] pythonpath = ["src"]`, because
only `src` is added and `tests/` has no `__init__.py`.

**Why:** the error names a module that visibly exists on disk, which sends you hunting in the wrong place.

**How to apply:** in the scaffold task create `tests/__init__.py` plus one per subpackage, and set
`pythonpath = ["src", "."]`. Verify by running the full gate, not a single test file.
