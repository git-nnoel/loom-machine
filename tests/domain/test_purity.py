"""The domain layer is pure — charter §2 and the skill's boundary rule B3.

`import-linter`'s `domain-is-pure` contract covers imports of *this project's* other layers. It
says nothing about the standard library, so a `pathlib` or `subprocess` import inside `domain/`
would pass it silently. That is exactly the leak worth guarding: R5 derives `updated_at` from
git, and the tempting place to put that subprocess is next to the field it fills.

This test inspects what each module actually bound at import time rather than parsing its source, so
an import hidden behind an alias or a re-export is still caught.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import pytest

import harness_library.domain

FORBIDDEN_ROOTS = frozenset(
    {
        "asyncio",
        "email",
        "fastapi",
        "frontmatter",
        "glob",
        "http",
        "io",
        "os",
        "pathlib",
        "pydantic",
        "requests",
        "shutil",
        "socket",
        "sqlite3",
        "structlog",
        "subprocess",
        "tempfile",
        "time",
        "typer",
        "urllib",
        "yaml",
    }
)


EXPECTED_MODULES = frozenset(
    {
        "artifact",
        "assembly",
        "errors",
        "hashing",
        "identity",
        "install_plan",
        "metadata",
        "raw",
        "registry",
        "repository",
        "validation",
    }
)
"""Every module the domain layer is known to hold.

Discovery alone is not coverage: a module that failed to import, or that was never added, would
simply not appear in the parametrisation and the suite would stay green having checked nothing about
it. This list makes "the new modules are covered" an assertion instead of an assumption. Adding a
domain module means adding it here — which is the point.
"""


def _domain_modules() -> list[ModuleType]:
    modules = [
        importlib.import_module(info.name)
        for info in pkgutil.iter_modules(
            harness_library.domain.__path__, f"{harness_library.domain.__name__}."
        )
    ]
    assert modules, "positive control: no domain modules were discovered, so nothing was checked"
    discovered = {module.__name__.rpartition(".")[2] for module in modules}
    assert discovered == EXPECTED_MODULES, (
        f"the purity guard covers {sorted(discovered)}; "
        f"EXPECTED_MODULES names {sorted(EXPECTED_MODULES)}. A domain module missing from the "
        "discovered set is a module nothing checked."
    )
    return modules


def _origin_root(value: object) -> str | None:
    if isinstance(value, ModuleType):
        return value.__name__.partition(".")[0]
    origin = getattr(value, "__module__", None)
    if isinstance(origin, str):
        return origin.partition(".")[0]
    return None


@pytest.mark.parametrize("module", _domain_modules(), ids=lambda m: m.__name__)
def test_no_domain_module_reaches_the_outside_world(module: ModuleType) -> None:
    leaked = sorted(
        {
            name
            for name, value in vars(module).items()
            if not name.startswith("__") and _origin_root(value) in FORBIDDEN_ROOTS
        }
    )
    assert leaked == [], (
        f"{module.__name__} binds {leaked}, which reaches outside the pure core. "
        "The domain layer performs no I/O and holds no framework; move it to infrastructure."
    )


def test_the_guard_can_fail() -> None:
    """Positive control for the assertion above: a module that *does* import a forbidden root is
    reported. Without this, a broken `_origin_root` would make every module look clean."""
    import pathlib

    assert _origin_root(pathlib.Path) in FORBIDDEN_ROOTS
    assert _origin_root(pathlib) in FORBIDDEN_ROOTS
