"""The layer boundaries of charter §2, enforced as a test rather than as a lint step.

A violation must fail the suite, not merely a separate lint job that someone can forget to
run. This module therefore drives the same `lint-imports` console script the gate drives.

Two invocation details are load-bearing:

* the **console script** is used, never ``python -m importlinter.cli`` — the module entry
  point resolves its configuration relative to the current working directory and so behaves
  differently under pytest's rootdir than it does on the command line;
* ``cwd`` is pinned to the repository root, so pytest's rootdir cannot change the outcome.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CONTRACT_NAMES = (
    "layered-architecture",
    "mcp-is-read-only",
    "domain-is-pure",
)


def _run_lint_imports() -> subprocess.CompletedProcess[str]:
    """Run the `lint-imports` console script from the repository root."""
    script = Path(sys.executable).parent / "lint-imports"
    if not script.exists():  # pragma: no cover - environment guard
        pytest.fail(
            f"the `lint-imports` console script is not installed next to {sys.executable}; "
            "the architecture contracts cannot be checked"
        )
    return subprocess.run(
        [str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def lint_imports_result() -> subprocess.CompletedProcess[str]:
    return _run_lint_imports()


def test_all_import_contracts_are_kept(
    lint_imports_result: subprocess.CompletedProcess[str],
) -> None:
    """No layer boundary in charter §2 is crossed."""
    assert lint_imports_result.returncode == 0, (
        "import-linter reported a broken architecture contract:\n"
        f"{lint_imports_result.stdout}\n{lint_imports_result.stderr}"
    )


@pytest.mark.parametrize("contract_name", CONTRACT_NAMES)
def test_contract_is_configured_and_kept(
    contract_name: str,
    lint_imports_result: subprocess.CompletedProcess[str],
) -> None:
    """Each named contract is present in the configuration and reported KEPT.

    Asserting on exit code alone is not enough: deleting a contract from `pyproject.toml`
    also produces exit 0. Naming each contract here means a silently dropped contract fails
    the suite instead of passing it.
    """
    report = lint_imports_result.stdout
    assert f"{contract_name} KEPT" in report, (
        f"contract {contract_name!r} was not reported as KEPT. Full report:\n{report}"
    )


# ------------------------------------------------------------------------------------------------
# Which package a use case is *defined* in — the guard `lint-imports` cannot be
# ------------------------------------------------------------------------------------------------

WRITE_PACKAGE = "harness_library.application.write"
READ_PACKAGE = "harness_library.application.read"

WRITE_USE_CASES = (
    "apply_install",
    "clean_foreign",
    "compare_versions",
    "plan_install",
    "prune_target",
    "resolve_conflict",
    "rollback_install",
    "uninstall_artifact",
)
"""Every use case `application/write/` exports. A new one is added here.

The `mcp-is-read-only` contract forbids `mcp/` from reaching this package, which is the mechanism
behind "an MCP session cannot mutate the user's harness". What the contract cannot tell is whether
a *given* use case is in it: move one into `application/read/` and `mypy`, `ruff` and
`lint-imports` all stay green while the guarantee quietly stops covering it. Naming them here is
the only thing that fails.
"""

WRITE_TYPES = (
    "ApplyResult",
    "CleanResult",
    "ComparisonResult",
    "PruneResult",
    "ResolveResult",
    "RollbackResult",
    "UninstallResult",
    "foreign_entries",
    "pruned_entries",
)
"""Every non-use-case name `application/write/` exports — seven result types and two selectors.

Listed separately from the use cases so the definition-site guard above keeps meaning "a use case
is where the contract can see it" rather than quietly widening to any exported name, and listed
**at all** so that the exports-exactly test below still covers the whole package surface. A name
that is neither a use case nor named here is what fails.

`pruned_entries` and `foreign_entries` are here rather than above because neither is a use case:
each is one comprehension over a plan's verdicts, and they are exported because two callers share
`pruned_entries` (T-19) and because the definition-site guard should cover them too — a selector
that drifted into `application/read/` would be the first half of the use case following it.
"""

READ_USE_CASES = (
    "diff_against_target",
    "export_collection",
    "list_artifacts",
    "search_artifacts",
    "validate_library",
)
"""A sample of `application/read/`'s surface, including T-15's drift report and T-21's export.

`diff_against_target` in particular must stay on the read side: it is what `mcp/` reaches, and a
read use case that drifted into `write/` would break the contract loudly — which is the opposite
failure and the one that does not need a test. This assertion's job is to make the pair symmetric,
so the write-side one cannot be read as an arbitrary rule about one function.

**`export_collection` is here because nothing else can see where it lives** (F-16, R45). Spec §5
puts it on the read side; an export defined in `application/write/` would keep `mypy`, `ruff` and
`lint-imports` green while being unreachable from the one adapter that should have it, which is
the same blindness T-15's mutation demonstrated from the other direction.
"""


@pytest.mark.parametrize("name", WRITE_USE_CASES)
def test_every_write_use_case_is_defined_in_the_write_package(name: str) -> None:
    """A write use case lives in `application/write/`, not merely re-exported from it.

    `__module__` is the definition site, so a function defined in `application/read/` and imported
    into `application/write/__init__.py` fails here — which is exactly the shape the mistake
    takes, because that arrangement keeps every other gate green.
    """
    write_package = importlib.import_module(WRITE_PACKAGE)
    function = getattr(write_package, name)

    assert function.__module__.startswith(f"{WRITE_PACKAGE}."), (
        f"{name} is exported from {WRITE_PACKAGE} but defined in {function.__module__}. "
        "The mcp-is-read-only contract forbids a module path, not a re-export: a write use case "
        "defined under application/read is reachable from the MCP server and no import contract "
        "will say so."
    )


@pytest.mark.parametrize("name", READ_USE_CASES)
def test_every_read_use_case_is_defined_in_the_read_package(name: str) -> None:
    """The symmetric half. `mcp/` imports this package; nothing defined here may sit in `write/`."""
    read_package = importlib.import_module(READ_PACKAGE)
    function = getattr(read_package, name)

    assert function.__module__.startswith(f"{READ_PACKAGE}."), (
        f"{name} is exported from {READ_PACKAGE} but defined in {function.__module__}."
    )


@pytest.mark.parametrize("name", WRITE_TYPES)
def test_every_write_type_is_defined_in_the_write_package(name: str) -> None:
    """The same definition-site check for the package's non-use-case exports.

    A result type is not reachable-from-`mcp/` in the way a use case is, but it is defined in the
    same module as the function that builds it, and a type that drifted into `application/read/`
    would be the first half of the use case following it.
    """
    write_package = importlib.import_module(WRITE_PACKAGE)
    exported = getattr(write_package, name)

    assert exported.__module__.startswith(f"{WRITE_PACKAGE}."), (
        f"{name} is exported from {WRITE_PACKAGE} but defined in {exported.__module__}."
    )


def test_the_write_package_exports_exactly_the_names_named_here() -> None:
    """Discovery is not coverage. A write use case that was never added to `WRITE_USE_CASES`
    would simply not be parametrised, and the guard above would pass having checked nothing
    about it."""
    write_package = importlib.import_module(WRITE_PACKAGE)

    assert sorted(write_package.__all__) == sorted(WRITE_USE_CASES + WRITE_TYPES)
