"""Shared scaffolding for the CLI's **write** suite (T-22).

Charter §10 tests an adapter through Typer's own runner, so every module that imports this one
goes through argument parsing, the callback, the composition root, a real filesystem and the exit
status — the parts that exist only at this layer. Nothing below it is re-asserted: every verdict,
every record ordering and every refusal was decided and proven in T-12…T-21, and a second suite
asserting them here would fail for reasons that have nothing to do with the CLI.

**This module collects evidence and renders no verdict** (L29). It copies fixtures, it hashes
directories and it invokes the app; the assertions are in the test modules, where a reader can
see what is being claimed.

Two guards are worth naming, because both protect something outside this repository.

**`sandbox_home` is autouse for this whole package.** `default_state_root()` is
`~/.local/state/loom` and `default_target_root()` is `~/.claude`, so a test that
forgot `--target`, or any command at all, would reach into the developer's own machine. Pointing
`$HOME` at `tmp_path` means the *real* code path runs — the same `Path.home()` a user gets —
while everything it produces lands in the sandbox. Charter §10 forbids writing to `~/.claude/`
outright and the plan asserts it by content hash (L37); this makes the mistake impossible rather
than detectable.

**`digests` never follows a symlink.** Ruling R6 is the rule the whole product is built on, and a
hash function that resolved a link would report a target as unchanged while the file it pointed
at had been rewritten — which is precisely the assertion these tests exist to make.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from loom.cli.main import app

FIXTURE_LIBRARY = Path(__file__).resolve().parents[2] / "fixtures" / "library"
"""The committed fixture library — lesson L6: `~/.claude/` is a target layout, not a library."""

FIXTURE_TARGET = Path(__file__).resolve().parents[2] / "fixtures" / "target"
"""The committed fixture install target, prerequisite P-3. Copied, never written to."""

TARGET_SYMLINK = "skills/delivery-lead/references/elsewhere.md"
"""The committed link resolving **outside** the target root. Foreign, and never followed."""

SYNCED_MARKER = "skills/synced/.bucket-7c1f9a2e"
SYNCED_SKILL = "skills/synced/7c1f9a2e_4b0d3f61/remote-helper/SKILL.md"
"""Claude Code's own sync bucket, two directories deep. Ruling R44 gives it no exclusion."""

SETTINGS = "settings.json"
"""A foreign loose file at the target root, under no artifact root at all (R60)."""


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `$HOME` at `tmp_path`, so the default state root and the default target are there.

    Autouse in every module that imports it. See the module docstring: this is what makes it
    impossible for a test in this suite to touch the developer's real `~/.claude/` or their real
    `~/.local/state/loom`, rather than merely unlikely.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LOOM_LIBRARY", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    return home


@pytest.fixture
def state_root(sandbox_home: Path) -> Path:
    """Where the manifests, the backups and the sentinel land. **Derived, never asserted into.**

    Computed the same way `manifest_store.default_state_root()` computes it, from the sandboxed
    home, so a test that reads a manifest back off disk reads the one the command really wrote.
    """
    return sandbox_home / ".local" / "state" / "loom-machine"


@pytest.fixture
def runner() -> CliRunner:
    """Typer's runner (L26 — **not** Click's `Result`). Click 8.5 keeps stdout and stderr apart."""
    return CliRunner()


@pytest.fixture
def fixture_target(tmp_path: Path) -> Path:
    """A writable copy of the committed fixture target, with its link's destination beside it.

    `symlinks=True`, so the committed link is copied as a link rather than as its contents — the
    whole point of it. Its destination is four levels up from `references/`, which lands beside
    the copied target, so the file it names really exists here.
    """
    root = tmp_path / "target"
    shutil.copytree(FIXTURE_TARGET, root, symlinks=True)
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "target-escape.md").write_bytes(b"# a file outside the target entirely\n")
    assert (root / TARGET_SYMLINK).is_symlink()
    return root


@pytest.fixture
def empty_target(tmp_path: Path) -> Path:
    """A target directory that exists and holds nothing. What a first install runs against."""
    root = tmp_path / "fresh-target"
    root.mkdir()
    return root


def library_with(tmp_path: Path, name: str = "library", **skills: str) -> Path:
    """A purpose-built library holding one valid skill per keyword argument.

    Built rather than copied when a test needs a **complete** plan: the committed fixture library
    reproduces every failure charter §8 names, so an install of it is incomplete by design and
    can never be the control for "a run that exits 0".
    """
    root = tmp_path / name
    for skill, body in skills.items():
        write(
            root / "skills" / skill / "SKILL.md",
            f"---\nname: {skill}\ndescription: what {skill} does\n---\n\n{body}\n",
        )
    return root


def write(path: Path, text: str) -> Path:
    """Write a text file, creating its parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def digests(root: Path) -> dict[str, str]:
    """Every path under `root`, target-relative, to a digest of what is there.

    A **symlink is recorded as its destination**, never as the bytes it points at (R6). Following
    one would make this function answer "unchanged" about a target whose link had been replaced,
    or about one whose link's destination had been rewritten from outside — and those are two of
    the failures every assertion in this suite is trying to catch.

    Directories appear as entries of their own, so a test can also see that an emptied artifact
    root is still there.
    """
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            found[relative] = f"-> {os.readlink(path)}"
        elif path.is_dir():
            found[relative] = "<directory>"
        else:
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def run(runner: CliRunner, library: Path | None, *arguments: str) -> Result:
    """Invoke `loom`, optionally against a library. Returns the `Result`; asserts nothing."""
    root = [] if library is None else ["--library", str(library)]
    return runner.invoke(app, [*root, *arguments])
