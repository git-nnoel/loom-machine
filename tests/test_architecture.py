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
