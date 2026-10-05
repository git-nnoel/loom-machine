"""Shared scaffolding for the infrastructure suite.

Charter §10: this layer is tested against **real files**, never a fake filesystem. Two kinds of real
files are used, and the distinction is deliberate:

* the **committed fixture library** (`tests/fixtures/library/`), which is prerequisite P-4 and the
  regression suite for every failure charter §8 exists to catch — never deleted;
* trees built under `tmp_path` for the cases the committed tree should not carry: a git repository
  whose commit dates the test owns, and the two rules (V8, V9) whose fixtures would cost the
  committed tree more than they are worth. See `tests/fixtures/README.md`.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loom.infrastructure.timestamps import FixedTimestamps

FIXTURE_LIBRARY = Path(__file__).resolve().parent.parent / "fixtures" / "library"
"""The committed fixture library. See `tests/fixtures/README.md`."""

FIXTURE_TARGET = Path(__file__).resolve().parent.parent / "fixtures" / "target"
"""The committed fixture install target — prerequisite P-3. See `tests/fixtures/README.md`.

A second committed tree rather than a second use of the library one, because a target is shaped
nothing like a library: it holds a foreign tree nobody here authored, a loose `settings.json`, an
editor swap file the library scanner would refuse, and a symlink that resolves out of the target.
Never written to by any test — the writes go to copies under `tmp_path`.
"""

SCANNED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
"""The instant every scan that is *not* about ruling R5 is pinned to."""

FIXED_TIMESTAMPS = FixedTimestamps(SCANNED_AT)
"""R5, held still. Injected so a test about the walk does not depend on the git state of whatever
repository it happens to be running inside, and pays no subprocess for the privilege."""


@pytest.fixture
def fixture_library() -> Path:
    """The committed fixture library's root."""
    assert FIXTURE_LIBRARY.is_dir(), (
        f"the committed fixture library is missing from {FIXTURE_LIBRARY}. Charter §10: it is the "
        "regression suite for the reason this product exists and is never deleted."
    )
    return FIXTURE_LIBRARY


@pytest.fixture
def fixture_target() -> Path:
    """The committed fixture install target's root. Read-only; nothing writes into it."""
    assert FIXTURE_TARGET.is_dir(), (
        f"the committed fixture target is missing from {FIXTURE_TARGET}. Charter §10: a fixture "
        "this suite is written against is never deleted."
    )
    return FIXTURE_TARGET


def git(repository: Path, *arguments: str, when: str | None = None) -> str:
    """Run one git command in `repository`, failing the test loudly if it does not succeed.

    Identity and dates come from the environment rather than from `git config`, so the test owns the
    commit timestamps outright — which is what makes "this came from git and not from mtime" an
    assertion rather than a coincidence. Signing and hooks are disabled because a developer's global
    configuration must not be able to change what this suite proves.
    """
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    if when is not None:
        environment["GIT_AUTHOR_DATE"] = when
        environment["GIT_COMMITTER_DATE"] = when
    completed = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"git {' '.join(arguments)} failed in {repository}:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout


def init_repository(root: Path) -> None:
    """A fresh git work tree at `root`."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-b", "main")


def write(path: Path, text: str) -> Path:
    """Write a text file, creating its parents. Returns the path, for chaining."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_skill(
    library_root: Path, name: str, *, body: str = "Prose.", frontmatter: str | None = None
) -> Path:
    """A valid skill directory under `library_root`. Returns the artifact root.

    Defaults to a well-formed artifact so each test perturbs exactly one thing — the same shape
    `tests/domain/test_assembly.py::raw_skill` uses, one layer down and against real bytes.
    """
    root = library_root / "skills" / name
    header = (
        frontmatter if frontmatter is not None else (f"name: {name}\ndescription: what {name} does")
    )
    write(root / "SKILL.md", f"---\n{header}\n---\n\n{body}\n")
    return root
