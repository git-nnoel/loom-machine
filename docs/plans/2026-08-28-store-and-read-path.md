# Harness Library — Plan 1: Store, Validation, Read Path, MCP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A filesystem-backed artifact store that reads skills and agents from the library tree, validates them, and exposes them through a read-only CLI and a read-only stdio MCP server.

**Architecture:** Clean Architecture, Mode A. A pure `domain/` layer defines the `Artifact` entity and an `ArtifactRepository` protocol. `infrastructure/` implements that protocol against the filesystem — no database; the library tree is the data. `application/read/` holds use cases. `cli/` and `mcp/` are two thin adapters over those use cases and contain no logic of their own.

**Tech Stack:** Python 3.12, uv, Typer, python-frontmatter, PyYAML, the `mcp` SDK, pytest, ruff, mypy, import-linter.

**Spec:** `docs/specs/2026-08-28-harness-library-design.md`

## Global Constraints

- Python 3.12 or newer. `[spec D5]`
- Clean Architecture Mode A. Dependencies point inward: `domain` imports nothing from the project; `application` imports only `domain`; `infrastructure` and adapters import `application` and `domain`. `[spec §5]`
- `domain/` is pure: no filesystem, no network, no framework imports, no `datetime.now()`. `[spec §5]`
- `mcp/` imports from `application.read` only. Never `application.write`. Enforced by an import-linter contract that runs as a test. `[spec §7.3]`
- Artifact identity is `<type>/<name>`, derived from the tree. No stored ids. `[spec §3.1]`
- **Deviation from spec §3.2, deliberate:** the spec writes validity as a sum type
  `Valid | Invalid(reasons)`. This plan implements it as `errors: tuple[ValidationError, ...]`
  plus an `is_valid` property. Same information, no sum-type machinery, and it keeps `Artifact`
  a single frozen dataclass. Update the spec to match once this lands.
- `content_hash` is sha256 over sorted `(relative_path, bytes)` pairs. `[spec §3.2]`
- An invalid artifact is listed with its reasons, never omitted. `[spec §4]`
- Nothing in this plan writes to `~/.claude/` or to any install target. Install is Plan 2.
- Test layering: `domain` and `application` tests use hand-written fakes and never touch disk. `infrastructure` tests use real files under pytest's `tmp_path`. `[spec §10]`

---

### Task 1: Project scaffold and the pure domain entity

**Files:**
- Create: `pyproject.toml`
- Create: `src/harness_library/__init__.py`
- Create: `src/harness_library/domain/__init__.py`
- Create: `src/harness_library/domain/artifact.py`
- Create: `tests/domain/test_artifact.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `ArtifactType` (str enum: `SKILL="skill"`, `AGENT="agent"`), `ArtifactKind` (str enum: `DIRECTORY="directory"`, `FILE="file"`), `ValidationError(code: str, message: str)`, `Artifact` frozen dataclass, `compute_content_hash(files: dict[str, bytes]) -> str`, `Artifact.id -> str`, `Artifact.is_valid -> bool`.

- [ ] **Step 1: Create the project scaffold**

`pyproject.toml`:

```toml
[project]
name = "harness-library"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "python-frontmatter>=1.1",
    "pyyaml>=6.0",
    "mcp>=1.2",
]

[project.scripts]
hl = "harness_library.cli.main:app"

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.6", "mypy>=1.11", "import-linter>=2.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/harness_library"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
```

`.gitignore`:

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
```

Then run `uv sync` and create empty `src/harness_library/__init__.py` and `src/harness_library/domain/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/domain/test_artifact.py`:

```python
import pytest

from harness_library.domain.artifact import (
    Artifact,
    ArtifactKind,
    ArtifactType,
    ValidationError,
    compute_content_hash,
)


def test_id_is_type_slash_name():
    a = _artifact(type=ArtifactType.SKILL, name="delivery-lead")
    assert a.id == "skill/delivery-lead"


def test_hash_is_stable_across_insertion_order():
    first = compute_content_hash({"SKILL.md": b"body", "references/a.md": b"ref"})
    second = compute_content_hash({"references/a.md": b"ref", "SKILL.md": b"body"})
    assert first == second


def test_hash_changes_when_content_changes():
    before = compute_content_hash({"SKILL.md": b"body"})
    after = compute_content_hash({"SKILL.md": b"body!"})
    assert before != after


def test_hash_changes_when_a_path_is_renamed():
    before = compute_content_hash({"SKILL.md": b"body"})
    after = compute_content_hash({"SKILL.MD": b"body"})
    assert before != after


def test_artifact_with_no_errors_is_valid():
    assert _artifact().is_valid is True


def test_artifact_with_errors_is_invalid():
    a = _artifact(errors=[ValidationError("V1", "missing SKILL.md")])
    assert a.is_valid is False


def test_artifact_is_frozen():
    with pytest.raises(Exception):
        _artifact().name = "other"  # type: ignore[misc]


def _artifact(**overrides):
    defaults = dict(
        type=ArtifactType.SKILL,
        name="delivery-lead",
        title="Delivery Lead",
        description="Integration owner.",
        kind=ArtifactKind.DIRECTORY,
        files=("SKILL.md",),
        content_hash="abc",
        updated_at=None,
        tags=(),
        collections=(),
        superseded_by=None,
        errors=(),
    )
    defaults.update(overrides)
    if "errors" in overrides:
        defaults["errors"] = tuple(overrides["errors"])
    return Artifact(**defaults)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/domain/test_artifact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_library.domain.artifact'`

- [ ] **Step 4: Write the minimal implementation**

`src/harness_library/domain/artifact.py`:

```python
"""The Artifact entity. Pure: no I/O, no framework, no clock."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ArtifactType(StrEnum):
    SKILL = "skill"
    AGENT = "agent"


class ArtifactKind(StrEnum):
    DIRECTORY = "directory"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class ValidationError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType
    name: str
    title: str | None
    description: str
    kind: ArtifactKind
    files: tuple[str, ...]
    content_hash: str
    updated_at: datetime | None
    tags: tuple[str, ...]
    collections: tuple[str, ...]
    superseded_by: str | None
    errors: tuple[ValidationError, ...]

    @property
    def id(self) -> str:
        return f"{self.type.value}/{self.name}"

    @property
    def is_valid(self) -> bool:
        return not self.errors


def compute_content_hash(files: dict[str, bytes]) -> str:
    """sha256 over sorted (relative path, bytes). Order-independent, rename-sensitive."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[path])
        digest.update(b"\0")
    return digest.hexdigest()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/domain/test_artifact.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/harness_library tests/domain
git commit -m "feat(domain): add Artifact entity and content hashing"
```

---

### Task 2: Type registry and frontmatter parsing

**Files:**
- Create: `src/harness_library/domain/types.py`
- Create: `src/harness_library/infrastructure/__init__.py`
- Create: `src/harness_library/infrastructure/frontmatter_parser.py`
- Create: `tests/domain/test_types.py`
- Create: `tests/infrastructure/test_frontmatter_parser.py`

**Interfaces:**
- Consumes: `ArtifactType`, `ArtifactKind` from Task 1.
- Produces: `TypeSpec(type, kind, entry_filename, target_template, required_keys)`, `TYPE_REGISTRY: dict[ArtifactType, TypeSpec]`, `spec_for(t: ArtifactType) -> TypeSpec`, `entry_filename_for(t, name) -> str`, and `parse_frontmatter(text: str) -> tuple[dict[str, object], str]` returning `(metadata, body)`.

- [ ] **Step 1: Write the failing tests**

`tests/domain/test_types.py`:

```python
from harness_library.domain.artifact import ArtifactKind, ArtifactType
from harness_library.domain.types import TYPE_REGISTRY, entry_filename_for, spec_for


def test_registry_covers_every_artifact_type():
    assert set(TYPE_REGISTRY) == set(ArtifactType)


def test_skill_is_a_directory_with_a_fixed_entry_file():
    spec = spec_for(ArtifactType.SKILL)
    assert spec.kind is ArtifactKind.DIRECTORY
    assert entry_filename_for(ArtifactType.SKILL, "delivery-lead") == "SKILL.md"


def test_agent_is_a_file_named_after_the_artifact():
    spec = spec_for(ArtifactType.AGENT)
    assert spec.kind is ArtifactKind.FILE
    assert entry_filename_for(ArtifactType.AGENT, "backend-developer-specialist") == (
        "backend-developer-specialist.md"
    )


def test_every_type_requires_name_and_description():
    for spec in TYPE_REGISTRY.values():
        assert "name" in spec.required_keys
        assert "description" in spec.required_keys
```

`tests/infrastructure/test_frontmatter_parser.py`:

```python
import pytest

from harness_library.infrastructure.frontmatter_parser import (
    FrontmatterError,
    parse_frontmatter,
)

DOC = """---
name: delivery-lead
description: Integration owner.
---

# Delivery Lead

Body text.
"""


def test_returns_metadata_and_body():
    meta, body = parse_frontmatter(DOC)
    assert meta["name"] == "delivery-lead"
    assert meta["description"] == "Integration owner."
    assert body.lstrip().startswith("# Delivery Lead")


def test_missing_frontmatter_yields_empty_metadata():
    meta, body = parse_frontmatter("# Just a heading\n")
    assert meta == {}
    assert "Just a heading" in body


def test_malformed_yaml_raises_frontmatter_error():
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nname: [unclosed\n---\nbody\n")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/domain/test_types.py tests/infrastructure/test_frontmatter_parser.py -v`
Expected: FAIL — `ModuleNotFoundError` for both new modules.

- [ ] **Step 3: Write the minimal implementation**

`src/harness_library/domain/types.py`:

```python
"""The single place a new artifact type is registered."""

from __future__ import annotations

from dataclasses import dataclass

from harness_library.domain.artifact import ArtifactKind, ArtifactType


@dataclass(frozen=True, slots=True)
class TypeSpec:
    type: ArtifactType
    kind: ArtifactKind
    entry_filename: str | None  # None means "named after the artifact"
    source_dirname: str
    target_template: str
    required_keys: tuple[str, ...]


TYPE_REGISTRY: dict[ArtifactType, TypeSpec] = {
    ArtifactType.SKILL: TypeSpec(
        type=ArtifactType.SKILL,
        kind=ArtifactKind.DIRECTORY,
        entry_filename="SKILL.md",
        source_dirname="skills",
        target_template="skills/{name}/",
        required_keys=("name", "description"),
    ),
    ArtifactType.AGENT: TypeSpec(
        type=ArtifactType.AGENT,
        kind=ArtifactKind.FILE,
        entry_filename=None,
        source_dirname="agents",
        target_template="agents/{name}.md",
        required_keys=("name", "description"),
    ),
}


def spec_for(artifact_type: ArtifactType) -> TypeSpec:
    return TYPE_REGISTRY[artifact_type]


def entry_filename_for(artifact_type: ArtifactType, name: str) -> str:
    spec = spec_for(artifact_type)
    return spec.entry_filename if spec.entry_filename else f"{name}.md"
```

`src/harness_library/infrastructure/frontmatter_parser.py`:

```python
"""Frontmatter parsing. Wraps python-frontmatter so the rest of the code never sees it."""

from __future__ import annotations

import frontmatter
import yaml


class FrontmatterError(ValueError):
    """Raised when a document has frontmatter delimiters but unparseable YAML."""


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    try:
        post = frontmatter.loads(text)
    except yaml.YAMLError as exc:
        raise FrontmatterError(str(exc)) from exc
    return dict(post.metadata), post.content
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/domain/test_types.py tests/infrastructure/test_frontmatter_parser.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/harness_library tests
git commit -m "feat: add type registry and frontmatter parsing"
```

---

### Task 3: Filesystem scan — the repository

**Files:**
- Create: `src/harness_library/domain/repository.py`
- Create: `src/harness_library/infrastructure/filesystem_repository.py`
- Create: `tests/infrastructure/conftest.py`
- Create: `tests/infrastructure/test_filesystem_repository.py`

**Interfaces:**
- Consumes: `Artifact`, `ArtifactType`, `compute_content_hash` (Task 1); `TYPE_REGISTRY`, `entry_filename_for`, `parse_frontmatter` (Task 2).
- Produces: `ArtifactRepository` protocol with `list_all() -> list[Artifact]` and `get(artifact_id: str) -> Artifact | None` and `read_file(artifact_id: str, relative_path: str) -> str`; `FilesystemArtifactRepository(root: Path)` implementing it; pytest fixture `library_root` building a realistic tree.

- [ ] **Step 1: Write the shared fixture**

`tests/infrastructure/conftest.py`:

```python
from pathlib import Path

import pytest

SKILL_DOC = """---
name: delivery-lead
description: Integration owner across backend and frontend.
---

# Delivery Lead

See `references/delegation.md` for the delegation criteria.
"""

AGENT_DOC = """---
name: backend-developer-specialist
description: Implements backend tasks delegated by an orchestrator.
---

# Backend Developer Specialist

Body.
"""


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    """A library tree that mirrors the real one, including its known defects."""
    skills = tmp_path / "skills"
    agents = tmp_path / "agents"

    good = skills / "delivery-lead"
    (good / "references").mkdir(parents=True)
    (good / "SKILL.md").write_text(SKILL_DOC)
    (good / "references" / "delegation.md").write_text("# Delegation\n")

    # V1 defect: a skill directory with no SKILL.md, only an empty references/.
    (skills / "solution-designer" / "references").mkdir(parents=True)

    agents.mkdir()
    (agents / "backend-developer-specialist.md").write_text(AGENT_DOC)

    # V6 defect: an editor swap file that must never be treated as an artifact.
    (agents / ".backend-developer-specialist.md.swp").write_bytes(b"\x00swap")

    return tmp_path
```

- [ ] **Step 2: Write the failing test**

`tests/infrastructure/test_filesystem_repository.py`:

```python
from pathlib import Path

from harness_library.domain.artifact import ArtifactKind, ArtifactType
from harness_library.infrastructure.filesystem_repository import (
    FilesystemArtifactRepository,
)


def test_lists_every_artifact_including_the_broken_one(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    ids = {a.id for a in repo.list_all()}
    assert ids == {
        "skill/delivery-lead",
        "skill/solution-designer",
        "agent/backend-developer-specialist",
    }


def test_a_dotfile_is_never_an_artifact(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    ids = {a.id for a in repo.list_all()}
    assert not any(i.startswith("agent/.") for i in ids)


def test_reads_frontmatter_and_title(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    a = repo.get("skill/delivery-lead")
    assert a is not None
    assert a.description == "Integration owner across backend and frontend."
    assert a.title == "Delivery Lead"
    assert a.kind is ArtifactKind.DIRECTORY
    assert a.type is ArtifactType.SKILL


def test_collects_every_file_in_a_directory_artifact(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    a = repo.get("skill/delivery-lead")
    assert a is not None
    assert set(a.files) == {"SKILL.md", "references/delegation.md"}


def test_a_file_artifact_has_exactly_one_file(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    a = repo.get("agent/backend-developer-specialist")
    assert a is not None
    assert a.files == ("backend-developer-specialist.md",)


def test_hash_changes_when_a_reference_changes(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    before = repo.get("skill/delivery-lead").content_hash  # type: ignore[union-attr]
    (library_root / "skills" / "delivery-lead" / "references" / "delegation.md").write_text("x")
    after = FilesystemArtifactRepository(library_root).get(
        "skill/delivery-lead"
    ).content_hash  # type: ignore[union-attr]
    assert before != after


def test_get_returns_none_for_an_unknown_id(library_root: Path):
    assert FilesystemArtifactRepository(library_root).get("skill/nope") is None


def test_read_file_returns_a_reference_body(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    assert repo.read_file("skill/delivery-lead", "references/delegation.md") == "# Delegation\n"


def test_read_file_rejects_traversal(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    try:
        repo.read_file("skill/delivery-lead", "../../etc/passwd")
    except ValueError:
        return
    raise AssertionError("expected ValueError for a path escaping the artifact root")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_filesystem_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_library.infrastructure.filesystem_repository'`

- [ ] **Step 4: Write the repository protocol**

`src/harness_library/domain/repository.py`:

```python
"""Repository protocols. Domain declares what it needs; infrastructure supplies it."""

from __future__ import annotations

from typing import Protocol

from harness_library.domain.artifact import Artifact


class ArtifactRepository(Protocol):
    def list_all(self) -> list[Artifact]: ...

    def get(self, artifact_id: str) -> Artifact | None: ...

    def read_file(self, artifact_id: str, relative_path: str) -> str: ...
```

- [ ] **Step 5: Write the filesystem implementation**

`src/harness_library/infrastructure/filesystem_repository.py`:

```python
"""Reads the library tree. The tree is the database."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from harness_library.domain.artifact import (
    Artifact,
    ArtifactKind,
    ArtifactType,
    compute_content_hash,
)
from harness_library.domain.types import TYPE_REGISTRY, entry_filename_for, spec_for
from harness_library.infrastructure.frontmatter_parser import (
    FrontmatterError,
    parse_frontmatter,
)

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class FilesystemArtifactRepository:
    def __init__(self, root: Path) -> None:
        self._root = root

    def list_all(self) -> list[Artifact]:
        artifacts = [
            artifact
            for artifact_type in TYPE_REGISTRY
            for artifact in self._scan_type(artifact_type)
        ]
        return sorted(artifacts, key=lambda a: a.id)

    def get(self, artifact_id: str) -> Artifact | None:
        return next((a for a in self.list_all() if a.id == artifact_id), None)

    def read_file(self, artifact_id: str, relative_path: str) -> str:
        root = self._artifact_root(artifact_id)
        resolved = (root / relative_path).resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ValueError(f"path escapes the artifact root: {relative_path}")
        return resolved.read_text(encoding="utf-8")

    # -- internals -------------------------------------------------------

    def _artifact_root(self, artifact_id: str) -> Path:
        type_value, _, name = artifact_id.partition("/")
        spec = spec_for(ArtifactType(type_value))
        base = self._root / spec.source_dirname
        return base / name if spec.kind is ArtifactKind.DIRECTORY else base

    def _scan_type(self, artifact_type: ArtifactType) -> list[Artifact]:
        spec = spec_for(artifact_type)
        base = self._root / spec.source_dirname
        if not base.is_dir():
            return []
        if spec.kind is ArtifactKind.DIRECTORY:
            entries = [p for p in sorted(base.iterdir()) if p.is_dir()]
        else:
            entries = [p for p in sorted(base.iterdir()) if p.is_file() and p.suffix == ".md"]
        return [self._build(artifact_type, p) for p in entries if not p.name.startswith(".")]

    def _build(self, artifact_type: ArtifactType, path: Path) -> Artifact:
        spec = spec_for(artifact_type)
        name = path.name if spec.kind is ArtifactKind.DIRECTORY else path.stem
        files = self._collect_files(path, spec.kind)
        entry = entry_filename_for(artifact_type, name)
        entry_text = files.get(entry, b"").decode("utf-8", errors="replace")

        try:
            meta, body = parse_frontmatter(entry_text)
        except FrontmatterError:
            meta, body = {}, entry_text

        heading = _H1.search(body)
        mtimes = [
            (path / rel).stat().st_mtime if spec.kind is ArtifactKind.DIRECTORY else path.stat().st_mtime
            for rel in files
        ]

        return Artifact(
            type=artifact_type,
            name=name,
            title=heading.group(1) if heading else None,
            description=str(meta.get("description", "")),
            kind=spec.kind,
            files=tuple(sorted(files)),
            content_hash=compute_content_hash(files),
            updated_at=datetime.fromtimestamp(max(mtimes), tz=UTC) if mtimes else None,
            tags=(),
            collections=(),
            superseded_by=None,
            errors=(),
        )

    @staticmethod
    def _collect_files(path: Path, kind: ArtifactKind) -> dict[str, bytes]:
        if kind is ArtifactKind.FILE:
            return {path.name: path.read_bytes()}
        return {
            str(p.relative_to(path)): p.read_bytes()
            for p in sorted(path.rglob("*"))
            if p.is_file() and not p.name.startswith(".")
        }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_filesystem_repository.py -v`
Expected: PASS, 9 tests. The `skill/solution-designer` entry appears with an empty description — it is listed, not omitted, which Task 5 turns into a reported error.

- [ ] **Step 7: Commit**

```bash
git add src/harness_library tests
git commit -m "feat(infrastructure): scan the library tree into Artifacts"
```

---

### Task 4: library.yaml — tags, collections, supersession

**Files:**
- Create: `src/harness_library/domain/metadata.py`
- Create: `src/harness_library/infrastructure/library_yaml.py`
- Modify: `src/harness_library/infrastructure/filesystem_repository.py`
- Create: `tests/infrastructure/test_library_yaml.py`
- Modify: `tests/infrastructure/conftest.py`

**Interfaces:**
- Consumes: `Artifact` (Task 1), `FilesystemArtifactRepository` (Task 3).
- Produces: `ArtifactMetadata(tags, collections, superseded_by)`, `Collection(key, title, description, members)`, `LibraryMetadata(artifacts: dict[str, ArtifactMetadata], collections: dict[str, Collection])`, `LibraryYamlError`, `read_library_yaml(path: Path) -> LibraryMetadata`. `FilesystemArtifactRepository.__init__` gains `metadata: LibraryMetadata | None = None` and applies it while building.

- [ ] **Step 1: Extend the fixture with a library.yaml**

Append to `tests/infrastructure/conftest.py`, inside `library_root` before `return tmp_path`:

```python
    (tmp_path / "library.yaml").write_text(
        "artifacts:\n"
        "  skill/delivery-lead:\n"
        "    tags: [orchestration, process]\n"
        "    collections: [ctg-delivery]\n"
        "  skill/developers-orchestration:\n"
        "    superseded_by: skill/delivery-lead\n"
        "collections:\n"
        "  ctg-delivery:\n"
        "    title: CTG delivery system\n"
        "    description: The full spec-to-delivery chain.\n"
        "    members: [skill/delivery-lead]\n"
    )
```

- [ ] **Step 2: Write the failing test**

`tests/infrastructure/test_library_yaml.py`:

```python
from pathlib import Path

import pytest

from harness_library.infrastructure.filesystem_repository import (
    FilesystemArtifactRepository,
)
from harness_library.infrastructure.library_yaml import (
    LibraryYamlError,
    read_library_yaml,
)


def test_reads_tags_and_collections(library_root: Path):
    meta = read_library_yaml(library_root / "library.yaml")
    entry = meta.artifacts["skill/delivery-lead"]
    assert entry.tags == ("orchestration", "process")
    assert entry.collections == ("ctg-delivery",)


def test_reads_supersession(library_root: Path):
    meta = read_library_yaml(library_root / "library.yaml")
    assert meta.artifacts["skill/developers-orchestration"].superseded_by == "skill/delivery-lead"


def test_reads_collection_definitions(library_root: Path):
    meta = read_library_yaml(library_root / "library.yaml")
    assert meta.collections["ctg-delivery"].title == "CTG delivery system"
    assert meta.collections["ctg-delivery"].members == ("skill/delivery-lead",)


def test_a_missing_file_is_empty_metadata_not_an_error(tmp_path: Path):
    meta = read_library_yaml(tmp_path / "absent.yaml")
    assert meta.artifacts == {}
    assert meta.collections == {}


def test_unparseable_yaml_raises(tmp_path: Path):
    bad = tmp_path / "library.yaml"
    bad.write_text("artifacts:\n  - [unclosed\n")
    with pytest.raises(LibraryYamlError):
        read_library_yaml(bad)


def test_repository_applies_metadata_to_artifacts(library_root: Path):
    meta = read_library_yaml(library_root / "library.yaml")
    repo = FilesystemArtifactRepository(library_root, metadata=meta)
    a = repo.get("skill/delivery-lead")
    assert a is not None
    assert a.tags == ("orchestration", "process")
    assert a.collections == ("ctg-delivery",)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_library_yaml.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_library.infrastructure.library_yaml'`

- [ ] **Step 4: Write the metadata domain types**

`src/harness_library/domain/metadata.py`:

```python
"""Metadata the artifact files cannot express themselves."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    tags: tuple[str, ...] = ()
    collections: tuple[str, ...] = ()
    superseded_by: str | None = None


@dataclass(frozen=True, slots=True)
class Collection:
    key: str
    title: str
    description: str
    members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LibraryMetadata:
    artifacts: dict[str, ArtifactMetadata] = field(default_factory=dict)
    collections: dict[str, Collection] = field(default_factory=dict)

    def for_artifact(self, artifact_id: str) -> ArtifactMetadata:
        return self.artifacts.get(artifact_id, ArtifactMetadata())
```

- [ ] **Step 5: Write the reader**

`src/harness_library/infrastructure/library_yaml.py`:

```python
"""Reads library.yaml into LibraryMetadata."""

from __future__ import annotations

from pathlib import Path

import yaml

from harness_library.domain.metadata import ArtifactMetadata, Collection, LibraryMetadata


class LibraryYamlError(ValueError):
    """Raised when library.yaml exists but cannot be read. Metadata is not guessable."""


def read_library_yaml(path: Path) -> LibraryMetadata:
    if not path.is_file():
        return LibraryMetadata()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise LibraryYamlError(f"{path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise LibraryYamlError(f"{path}: expected a mapping at the top level")

    artifacts = {
        artifact_id: ArtifactMetadata(
            tags=tuple(entry.get("tags", ())),
            collections=tuple(entry.get("collections", ())),
            superseded_by=entry.get("superseded_by"),
        )
        for artifact_id, entry in (raw.get("artifacts") or {}).items()
    }

    collections = {
        key: Collection(
            key=key,
            title=entry.get("title", key),
            description=entry.get("description", ""),
            members=tuple(entry.get("members", ())),
        )
        for key, entry in (raw.get("collections") or {}).items()
    }

    return LibraryMetadata(artifacts=artifacts, collections=collections)
```

- [ ] **Step 6: Apply metadata in the repository**

In `filesystem_repository.py`, add the import `from harness_library.domain.metadata import LibraryMetadata`, then change `__init__` and the tail of `_build`:

```python
    def __init__(self, root: Path, metadata: LibraryMetadata | None = None) -> None:
        self._root = root
        self._metadata = metadata or LibraryMetadata()
```

Replace the `tags=()`, `collections=()`, `superseded_by=None` lines in the returned `Artifact` with:

```python
            tags=self._metadata.for_artifact(f"{artifact_type.value}/{name}").tags,
            collections=self._metadata.for_artifact(f"{artifact_type.value}/{name}").collections,
            superseded_by=self._metadata.for_artifact(
                f"{artifact_type.value}/{name}"
            ).superseded_by,
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS, all tests including Task 3's, which still pass because `metadata` defaults to empty.

- [ ] **Step 8: Commit**

```bash
git add src/harness_library tests
git commit -m "feat: read tags, collections and supersession from library.yaml"
```

---

### Task 5: Validation rules V1–V6

**Files:**
- Create: `src/harness_library/domain/validation.py`
- Modify: `src/harness_library/infrastructure/filesystem_repository.py`
- Create: `tests/domain/test_validation.py`

**Interfaces:**
- Consumes: `Artifact`, `ValidationError` (Task 1); `spec_for`, `entry_filename_for` (Task 2); `LibraryMetadata` (Task 4).
- Produces: `validate_artifact(artifact, frontmatter, body, extraneous_files, known_ids) -> tuple[ValidationError, ...]`. The repository calls it and populates `Artifact.errors`.

- [ ] **Step 1: Write the failing test**

`tests/domain/test_validation.py`:

```python
from harness_library.domain.artifact import Artifact, ArtifactKind, ArtifactType
from harness_library.domain.validation import validate_artifact


def _artifact(**overrides) -> Artifact:
    defaults = dict(
        type=ArtifactType.SKILL,
        name="delivery-lead",
        title="Delivery Lead",
        description="Integration owner.",
        kind=ArtifactKind.DIRECTORY,
        files=("SKILL.md",),
        content_hash="abc",
        updated_at=None,
        tags=(),
        collections=(),
        superseded_by=None,
        errors=(),
    )
    defaults.update(overrides)
    return Artifact(**defaults)


def _codes(**kwargs) -> set[str]:
    return {e.code for e in validate_artifact(**kwargs)}


def _call(**overrides) -> dict:
    base = dict(
        artifact=_artifact(),
        frontmatter={"name": "delivery-lead", "description": "Integration owner."},
        body="# Delivery Lead\n",
        extraneous_files=(),
        known_ids={"skill/delivery-lead"},
    )
    base.update(overrides)
    return base


def test_v1_skill_directory_without_entry_file():
    codes = _codes(**_call(artifact=_artifact(files=("references/x.md",))))
    assert "V1" in codes


def test_v2_frontmatter_name_disagrees_with_directory_name():
    codes = _codes(**_call(frontmatter={"name": "frontend-system-pattern", "description": "d"}))
    assert "V2" in codes


def test_v3_body_cites_a_reference_that_does_not_exist():
    codes = _codes(**_call(body="See `references/delegation.md` for detail.\n"))
    assert "V3" in codes


def test_v3_passes_when_the_cited_reference_exists():
    codes = _codes(
        **_call(
            artifact=_artifact(files=("SKILL.md", "references/delegation.md")),
            body="See `references/delegation.md`.\n",
        )
    )
    assert "V3" not in codes


def test_v4_superseded_by_points_at_a_missing_artifact():
    codes = _codes(**_call(artifact=_artifact(superseded_by="skill/ghost")))
    assert "V4" in codes


def test_v5_missing_required_frontmatter_key():
    codes = _codes(**_call(frontmatter={"name": "delivery-lead"}))
    assert "V5" in codes


def test_v5_empty_required_value_counts_as_missing():
    codes = _codes(**_call(frontmatter={"name": "delivery-lead", "description": "  "}))
    assert "V5" in codes


def test_v6_extraneous_files_are_reported():
    codes = _codes(**_call(extraneous_files=(".SKILL.md.swp",)))
    assert "V6" in codes


def test_a_clean_artifact_has_no_errors():
    assert validate_artifact(**_call()) == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/domain/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_library.domain.validation'`

- [ ] **Step 3: Write the implementation**

`src/harness_library/domain/validation.py`:

```python
"""Validation rules. Each rule exists because the failure was observed on disk.

See docs/specs/2026-08-28-harness-library-design.md §4.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from harness_library.domain.artifact import Artifact, ValidationError
from harness_library.domain.types import entry_filename_for, spec_for

_REFERENCE_CITATION = re.compile(r"(?:^|[\s`(\[])(references/[\w./-]+\.md)")


def validate_artifact(
    artifact: Artifact,
    frontmatter: dict[str, object],
    body: str,
    extraneous_files: Iterable[str],
    known_ids: set[str],
) -> tuple[ValidationError, ...]:
    errors: list[ValidationError] = []
    entry = entry_filename_for(artifact.type, artifact.name)

    # V1 — the entry file must exist.
    if entry not in artifact.files:
        errors.append(ValidationError("V1", f"missing entry file {entry}"))

    # V2 — frontmatter name must match the name derived from the tree.
    declared = frontmatter.get("name")
    if declared is not None and str(declared) != artifact.name:
        errors.append(
            ValidationError("V2", f"frontmatter name {declared!r} != directory name {artifact.name!r}")
        )

    # V3 — every cited reference path must exist.
    present = set(artifact.files)
    for cited in sorted(set(_REFERENCE_CITATION.findall(body))):
        if cited not in present:
            errors.append(ValidationError("V3", f"cited reference does not exist: {cited}"))

    # V4 — supersession must resolve.
    if artifact.superseded_by and artifact.superseded_by not in known_ids:
        errors.append(
            ValidationError("V4", f"superseded_by does not resolve: {artifact.superseded_by}")
        )

    # V5 — required frontmatter keys present and non-empty.
    for key in spec_for(artifact.type).required_keys:
        value = frontmatter.get(key)
        if value is None or not str(value).strip():
            errors.append(ValidationError("V5", f"missing or empty frontmatter key: {key}"))

    # V6 — extraneous files are reported, never removed.
    for path in sorted(extraneous_files):
        errors.append(ValidationError("V6", f"extraneous file in artifact: {path}"))

    return tuple(errors)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/domain/test_validation.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Wire validation into the repository**

`list_all` must build every artifact first so that `known_ids` is complete, then validate. Replace `list_all` and the tail of `_build`:

```python
    def list_all(self) -> list[Artifact]:
        built = [
            self._build(artifact_type, path)
            for artifact_type in TYPE_REGISTRY
            for path in self._entries(artifact_type)
        ]
        known_ids = {a.id for a, _, _, _ in built}
        validated = [
            replace(
                artifact,
                errors=validate_artifact(artifact, meta, body, extraneous, known_ids),
            )
            for artifact, meta, body, extraneous in built
        ]
        return sorted(validated, key=lambda a: a.id)
```

`_build` now returns `tuple[Artifact, dict[str, object], str, tuple[str, ...]]`, where the last element lists dotfiles and other skipped entries found under the artifact root. Add `from dataclasses import replace` and `from harness_library.domain.validation import validate_artifact` to the imports, and extract the entry-listing loop from `_scan_type` into `_entries(artifact_type) -> list[Path]`.

- [ ] **Step 6: Add the repository-level regression test**

Append to `tests/infrastructure/test_filesystem_repository.py`:

```python
def test_the_broken_skill_is_listed_with_its_reason(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    broken = repo.get("skill/solution-designer")
    assert broken is not None, "an invalid artifact must be listed, never omitted"
    assert broken.is_valid is False
    assert "V1" in {e.code for e in broken.errors}


def test_the_good_skill_is_valid(library_root: Path):
    repo = FilesystemArtifactRepository(library_root)
    good = repo.get("skill/delivery-lead")
    assert good is not None
    assert good.is_valid is True, [e.message for e in good.errors]
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/harness_library tests
git commit -m "feat(domain): add validation rules V1-V6"
```

---

### Task 6: Read use cases

**Files:**
- Create: `src/harness_library/application/__init__.py`
- Create: `src/harness_library/application/read/__init__.py`
- Create: `src/harness_library/application/read/use_cases.py`
- Create: `tests/application/fakes.py`
- Create: `tests/application/test_read_use_cases.py`

**Interfaces:**
- Consumes: `Artifact` (Task 1), `ArtifactRepository` (Task 3), `LibraryMetadata` (Task 4).
- Produces: `ArtifactFilter(type, tag, collection, invalid_only)`, `SortKey` enum (`NAME`, `UPDATED`, `SIZE`), `SearchMatch(artifact_id, path, line_number, line)`, and the callables `list_artifacts(repo, filter, sort) -> list[Artifact]`, `get_artifact(repo, id) -> Artifact`, `get_artifact_file(repo, id, path) -> str`, `search_artifacts(repo, query) -> list[SearchMatch]`, `validate_library(repo) -> list[Artifact]`. `ArtifactNotFoundError` is raised by the two `get_*` callables.

- [ ] **Step 1: Write the fake repository**

`tests/application/fakes.py`:

```python
from __future__ import annotations

from harness_library.domain.artifact import Artifact, ArtifactKind, ArtifactType


def make_artifact(
    artifact_id: str = "skill/delivery-lead",
    *,
    tags: tuple[str, ...] = (),
    collections: tuple[str, ...] = (),
    errors: tuple = (),
    files: tuple[str, ...] = ("SKILL.md",),
    updated_at=None,
) -> Artifact:
    type_value, _, name = artifact_id.partition("/")
    artifact_type = ArtifactType(type_value)
    return Artifact(
        type=artifact_type,
        name=name,
        title=name.replace("-", " ").title(),
        description=f"Description of {name}.",
        kind=ArtifactKind.DIRECTORY
        if artifact_type is ArtifactType.SKILL
        else ArtifactKind.FILE,
        files=files,
        content_hash="hash-" + name,
        updated_at=updated_at,
        tags=tags,
        collections=collections,
        superseded_by=None,
        errors=errors,
    )


class FakeArtifactRepository:
    """In-memory ArtifactRepository. No disk, no tmp_path."""

    def __init__(self, artifacts: list[Artifact], contents: dict[tuple[str, str], str] | None = None):
        self._artifacts = artifacts
        self._contents = contents or {}

    def list_all(self) -> list[Artifact]:
        return list(self._artifacts)

    def get(self, artifact_id: str) -> Artifact | None:
        return next((a for a in self._artifacts if a.id == artifact_id), None)

    def read_file(self, artifact_id: str, relative_path: str) -> str:
        try:
            return self._contents[(artifact_id, relative_path)]
        except KeyError as exc:
            raise FileNotFoundError(relative_path) from exc
```

- [ ] **Step 2: Write the failing test**

`tests/application/test_read_use_cases.py`:

```python
from datetime import UTC, datetime

import pytest

from harness_library.application.read.use_cases import (
    ArtifactFilter,
    ArtifactNotFoundError,
    SortKey,
    get_artifact,
    get_artifact_file,
    list_artifacts,
    search_artifacts,
    validate_library,
)
from harness_library.domain.artifact import ValidationError
from tests.application.fakes import FakeArtifactRepository, make_artifact


def test_lists_everything_with_an_empty_filter():
    repo = FakeArtifactRepository([make_artifact("skill/a"), make_artifact("agent/b")])
    assert len(list_artifacts(repo, ArtifactFilter())) == 2


def test_filters_by_type():
    repo = FakeArtifactRepository([make_artifact("skill/a"), make_artifact("agent/b")])
    result = list_artifacts(repo, ArtifactFilter(type="skill"))
    assert [a.id for a in result] == ["skill/a"]


def test_filters_by_tag():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a", tags=("process",)), make_artifact("skill/b")]
    )
    assert [a.id for a in list_artifacts(repo, ArtifactFilter(tag="process"))] == ["skill/a"]


def test_filters_by_collection():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a", collections=("ctg",)), make_artifact("skill/b")]
    )
    assert [a.id for a in list_artifacts(repo, ArtifactFilter(collection="ctg"))] == ["skill/a"]


def test_filters_to_invalid_only():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a", errors=(ValidationError("V1", "x"),)), make_artifact("skill/b")]
    )
    assert [a.id for a in list_artifacts(repo, ArtifactFilter(invalid_only=True))] == ["skill/a"]


def test_sorts_by_name():
    repo = FakeArtifactRepository([make_artifact("skill/z"), make_artifact("skill/a")])
    assert [a.name for a in list_artifacts(repo, ArtifactFilter(), SortKey.NAME)] == ["a", "z"]


def test_sorts_by_updated_most_recent_first():
    old = make_artifact("skill/old", updated_at=datetime(2020, 1, 1, tzinfo=UTC))
    new = make_artifact("skill/new", updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    repo = FakeArtifactRepository([old, new])
    assert [a.name for a in list_artifacts(repo, ArtifactFilter(), SortKey.UPDATED)] == [
        "new",
        "old",
    ]


def test_sorts_by_size_largest_first():
    small = make_artifact("skill/small", files=("SKILL.md",))
    large = make_artifact("skill/large", files=("SKILL.md", "references/a.md", "references/b.md"))
    repo = FakeArtifactRepository([small, large])
    assert [a.name for a in list_artifacts(repo, ArtifactFilter(), SortKey.SIZE)] == [
        "large",
        "small",
    ]


def test_get_artifact_returns_it():
    repo = FakeArtifactRepository([make_artifact("skill/a")])
    assert get_artifact(repo, "skill/a").id == "skill/a"


def test_get_artifact_raises_for_unknown_id():
    with pytest.raises(ArtifactNotFoundError):
        get_artifact(FakeArtifactRepository([]), "skill/ghost")


def test_get_artifact_file_returns_contents():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a")], {("skill/a", "references/x.md"): "# X\n"}
    )
    assert get_artifact_file(repo, "skill/a", "references/x.md") == "# X\n"


def test_get_artifact_file_raises_for_unknown_artifact():
    with pytest.raises(ArtifactNotFoundError):
        get_artifact_file(FakeArtifactRepository([]), "skill/ghost", "SKILL.md")


def test_search_matches_description_and_reports_the_line():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a")], {("skill/a", "SKILL.md"): "line one\nfindme here\n"}
    )
    matches = search_artifacts(repo, "findme")
    assert any(m.line_number == 2 and "findme" in m.line for m in matches)


def test_search_is_case_insensitive():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a")], {("skill/a", "SKILL.md"): "FindMe\n"}
    )
    assert search_artifacts(repo, "findme")


def test_search_covers_reference_bodies_not_just_the_entry_file():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a", files=("SKILL.md", "references/deep.md"))],
        {("skill/a", "SKILL.md"): "nothing\n", ("skill/a", "references/deep.md"): "needle\n"},
    )
    matches = search_artifacts(repo, "needle")
    assert [m.path for m in matches] == ["references/deep.md"]


def test_validate_library_returns_only_invalid_artifacts():
    repo = FakeArtifactRepository(
        [make_artifact("skill/a", errors=(ValidationError("V1", "x"),)), make_artifact("skill/b")]
    )
    assert [a.id for a in validate_library(repo)] == ["skill/a"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/application -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_library.application'`

- [ ] **Step 4: Write the implementation**

Create empty `src/harness_library/application/__init__.py` and `src/harness_library/application/read/__init__.py`, then `src/harness_library/application/read/use_cases.py`:

```python
"""Read use cases. No I/O of their own — everything arrives through the repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from harness_library.domain.artifact import Artifact
from harness_library.domain.repository import ArtifactRepository


class ArtifactNotFoundError(LookupError):
    pass


class SortKey(StrEnum):
    NAME = "name"
    UPDATED = "updated"
    SIZE = "size"


@dataclass(frozen=True, slots=True)
class ArtifactFilter:
    type: str | None = None
    tag: str | None = None
    collection: str | None = None
    invalid_only: bool = False

    def matches(self, artifact: Artifact) -> bool:
        if self.type and artifact.type.value != self.type:
            return False
        if self.tag and self.tag not in artifact.tags:
            return False
        if self.collection and self.collection not in artifact.collections:
            return False
        if self.invalid_only and artifact.is_valid:
            return False
        return True


@dataclass(frozen=True, slots=True)
class SearchMatch:
    artifact_id: str
    path: str
    line_number: int
    line: str


def list_artifacts(
    repo: ArtifactRepository,
    artifact_filter: ArtifactFilter | None = None,
    sort: SortKey = SortKey.NAME,
) -> list[Artifact]:
    active = artifact_filter or ArtifactFilter()
    selected = [a for a in repo.list_all() if active.matches(a)]
    match sort:
        case SortKey.NAME:
            return sorted(selected, key=lambda a: a.id)
        case SortKey.UPDATED:
            oldest = datetime.min.replace(tzinfo=UTC)
            return sorted(selected, key=lambda a: a.updated_at or oldest, reverse=True)
        case SortKey.SIZE:
            return sorted(selected, key=lambda a: (len(a.files), a.id), reverse=True)


def get_artifact(repo: ArtifactRepository, artifact_id: str) -> Artifact:
    artifact = repo.get(artifact_id)
    if artifact is None:
        raise ArtifactNotFoundError(artifact_id)
    return artifact


def get_artifact_file(repo: ArtifactRepository, artifact_id: str, relative_path: str) -> str:
    get_artifact(repo, artifact_id)
    return repo.read_file(artifact_id, relative_path)


def search_artifacts(repo: ArtifactRepository, query: str) -> list[SearchMatch]:
    needle = query.casefold()
    matches: list[SearchMatch] = []
    for artifact in repo.list_all():
        for path in artifact.files:
            try:
                text = repo.read_file(artifact.id, path)
            except (FileNotFoundError, UnicodeDecodeError, ValueError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if needle in line.casefold():
                    matches.append(SearchMatch(artifact.id, path, number, line.strip()))
    return matches


def validate_library(repo: ArtifactRepository) -> list[Artifact]:
    return [a for a in repo.list_all() if not a.is_valid]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/application -v`
Expected: PASS, 16 tests.

- [ ] **Step 6: Commit**

```bash
git add src/harness_library tests
git commit -m "feat(application): add read use cases"
```

---

### Task 7: Read CLI

**Files:**
- Create: `src/harness_library/cli/__init__.py`
- Create: `src/harness_library/cli/context.py`
- Create: `src/harness_library/cli/main.py`
- Create: `tests/cli/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: `build_repository(root: Path) -> FilesystemArtifactRepository` (reads `library.yaml` and wires it in); `resolve_library_root(explicit: Path | None) -> Path` (uses `--library`, else `$HL_LIBRARY`, else the current directory); the Typer `app` with `list`, `show`, `search`, `validate`. Exit code 1 when `validate` finds errors, 0 otherwise.

- [ ] **Step 1: Write the failing test**

`tests/cli/test_cli.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from harness_library.cli.main import app

runner = CliRunner()


def _run(library_root: Path, *args: str):
    return runner.invoke(app, ["--library", str(library_root), *args])


def test_list_shows_every_artifact_id(library_root: Path):
    result = _run(library_root, "list")
    assert result.exit_code == 0
    assert "skill/delivery-lead" in result.stdout
    assert "agent/backend-developer-specialist" in result.stdout


def test_list_marks_an_invalid_artifact(library_root: Path):
    result = _run(library_root, "list")
    assert "skill/solution-designer" in result.stdout
    assert "INVALID" in result.stdout


def test_list_filters_by_type(library_root: Path):
    result = _run(library_root, "list", "--type", "agent")
    assert "agent/backend-developer-specialist" in result.stdout
    assert "skill/delivery-lead" not in result.stdout


def test_show_prints_the_entry_body(library_root: Path):
    result = _run(library_root, "show", "skill/delivery-lead")
    assert result.exit_code == 0
    assert "Delivery Lead" in result.stdout


def test_show_lists_files_with_the_flag(library_root: Path):
    result = _run(library_root, "show", "skill/delivery-lead", "--files")
    assert "references/delegation.md" in result.stdout


def test_show_exits_nonzero_for_an_unknown_id(library_root: Path):
    result = _run(library_root, "show", "skill/ghost")
    assert result.exit_code == 1


def test_search_reports_the_matching_line(library_root: Path):
    result = _run(library_root, "search", "Integration owner")
    assert result.exit_code == 0
    assert "skill/delivery-lead" in result.stdout


def test_validate_exits_1_when_the_library_has_errors(library_root: Path):
    result = _run(library_root, "validate")
    assert result.exit_code == 1
    assert "V1" in result.stdout


def test_validate_exits_0_on_a_clean_library(tmp_path: Path):
    skill = tmp_path / "skills" / "ok"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: ok\ndescription: Fine.\n---\n\n# Ok\n")
    result = runner.invoke(app, ["--library", str(tmp_path), "validate"])
    assert result.exit_code == 0
```

Add `tests/cli/conftest.py` containing `from tests.infrastructure.conftest import library_root  # noqa: F401` so the CLI tests reuse the same tree.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_library.cli'`

- [ ] **Step 3: Write the wiring**

`src/harness_library/cli/context.py`:

```python
"""Composition root for the CLI. The only place adapters know about concrete infrastructure."""

from __future__ import annotations

import os
from pathlib import Path

from harness_library.infrastructure.filesystem_repository import (
    FilesystemArtifactRepository,
)
from harness_library.infrastructure.library_yaml import read_library_yaml


def resolve_library_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    from_env = os.environ.get("HL_LIBRARY")
    return Path(from_env) if from_env else Path.cwd()


def build_repository(root: Path) -> FilesystemArtifactRepository:
    return FilesystemArtifactRepository(root, metadata=read_library_yaml(root / "library.yaml"))
```

- [ ] **Step 4: Write the CLI**

`src/harness_library/cli/main.py`:

```python
"""Typer adapter. Contains no logic — every command calls one use case."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from harness_library.application.read.use_cases import (
    ArtifactFilter,
    ArtifactNotFoundError,
    SortKey,
    get_artifact,
    get_artifact_file,
    list_artifacts,
    search_artifacts,
    validate_library,
)
from harness_library.cli.context import build_repository, resolve_library_root
from harness_library.domain.types import entry_filename_for

app = typer.Typer(help="Harness Library — manage the skills and agents you author.")

_LibraryOption = Annotated[
    Path | None, typer.Option("--library", help="Library root. Defaults to $HL_LIBRARY or cwd.")
]


@app.callback()
def main(ctx: typer.Context, library: _LibraryOption = None) -> None:
    ctx.obj = build_repository(resolve_library_root(library))


@app.command("list")
def list_command(
    ctx: typer.Context,
    type_: Annotated[str | None, typer.Option("--type")] = None,
    tag: Annotated[str | None, typer.Option("--tag")] = None,
    collection: Annotated[str | None, typer.Option("--collection")] = None,
    invalid: Annotated[bool, typer.Option("--invalid")] = False,
    sort: Annotated[SortKey, typer.Option("--sort")] = SortKey.NAME,
) -> None:
    artifacts = list_artifacts(
        ctx.obj,
        ArtifactFilter(type=type_, tag=tag, collection=collection, invalid_only=invalid),
        sort,
    )
    for artifact in artifacts:
        flag = "  " if artifact.is_valid else " INVALID"
        superseded = f"  → {artifact.superseded_by}" if artifact.superseded_by else ""
        typer.echo(f"{artifact.id:<48}{len(artifact.files):>3} files{flag}{superseded}")


@app.command("show")
def show_command(
    ctx: typer.Context,
    artifact_id: str,
    files: Annotated[bool, typer.Option("--files")] = False,
) -> None:
    try:
        artifact = get_artifact(ctx.obj, artifact_id)
    except ArtifactNotFoundError:
        typer.echo(f"not found: {artifact_id}", err=True)
        raise typer.Exit(code=1) from None

    if files:
        for path in artifact.files:
            typer.echo(path)
        return

    for error in artifact.errors:
        typer.echo(f"[{error.code}] {error.message}", err=True)
    typer.echo(get_artifact_file(ctx.obj, artifact_id, entry_filename_for(artifact.type, artifact.name)))


@app.command("search")
def search_command(ctx: typer.Context, query: str) -> None:
    for match in search_artifacts(ctx.obj, query):
        typer.echo(f"{match.artifact_id}:{match.path}:{match.line_number}: {match.line}")


@app.command("validate")
def validate_command(ctx: typer.Context) -> None:
    invalid = validate_library(ctx.obj)
    for artifact in invalid:
        for error in artifact.errors:
            typer.echo(f"{artifact.id}: [{error.code}] {error.message}")
    if invalid:
        raise typer.Exit(code=1)
    typer.echo("library is valid")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/cli -v`
Expected: PASS, 9 tests.

- [ ] **Step 6: Run it against the real library**

Run: `uv run hl --library ~/.claude list` — but note `~/.claude` is a *target* layout, not a library, so this is only a smoke check that the command runs. Expected: it lists the six skills and two agents, and reports nothing as `INVALID` (the broken skills were fixed earlier).

- [ ] **Step 7: Commit**

```bash
git add src/harness_library tests
git commit -m "feat(cli): add list, show, search and validate"
```

---

### Task 8: MCP server and the structural read-only guarantee

**Files:**
- Create: `src/harness_library/mcp/__init__.py`
- Create: `src/harness_library/mcp/server.py`
- Create: `setup.cfg`
- Create: `tests/mcp/test_server.py`
- Create: `tests/test_architecture.py`

**Interfaces:**
- Consumes: the read use cases (Task 6) and `build_repository` / `resolve_library_root` (Task 7).
- Produces: `build_server(repo) -> mcp.server.Server` exposing exactly `list_artifacts`, `search_artifacts`, `get_artifact`, `get_reference`; console entry point `hl mcp`.

- [ ] **Step 1: Write the failing tests**

`tests/mcp/test_server.py`:

```python
import json

import pytest

from harness_library.mcp.server import TOOL_NAMES, build_server, call_tool
from tests.application.fakes import FakeArtifactRepository, make_artifact


@pytest.fixture
def repo():
    return FakeArtifactRepository(
        [make_artifact("skill/delivery-lead", tags=("process",), files=("SKILL.md", "references/d.md"))],
        {
            ("skill/delivery-lead", "SKILL.md"): "# Delivery Lead\nbody\n",
            ("skill/delivery-lead", "references/d.md"): "# Delegation\n",
        },
    )


def test_exposes_exactly_the_four_read_tools():
    assert TOOL_NAMES == (
        "list_artifacts",
        "search_artifacts",
        "get_artifact",
        "get_reference",
    )


def test_no_tool_name_suggests_a_mutation():
    forbidden = ("create", "update", "delete", "install", "write", "sync", "apply")
    assert not [n for n in TOOL_NAMES if any(word in n for word in forbidden)]


def test_list_artifacts_returns_ids_and_descriptions(repo):
    payload = json.loads(call_tool(repo, "list_artifacts", {}))
    assert payload[0]["id"] == "skill/delivery-lead"
    assert "description" in payload[0]


def test_list_artifacts_filters_by_tag(repo):
    assert json.loads(call_tool(repo, "list_artifacts", {"tag": "process"}))
    assert json.loads(call_tool(repo, "list_artifacts", {"tag": "absent"})) == []


def test_search_artifacts_returns_matches(repo):
    payload = json.loads(call_tool(repo, "search_artifacts", {"query": "Delegation"}))
    assert payload[0]["path"] == "references/d.md"


def test_get_artifact_returns_entry_text_and_file_list(repo):
    payload = json.loads(call_tool(repo, "get_artifact", {"id": "skill/delivery-lead"}))
    assert "Delivery Lead" in payload["text"]
    assert "references/d.md" in payload["files"]


def test_get_reference_returns_one_file(repo):
    payload = json.loads(
        call_tool(repo, "get_reference", {"id": "skill/delivery-lead", "path": "references/d.md"})
    )
    assert payload["text"] == "# Delegation\n"


def test_unknown_artifact_returns_an_error_payload_not_an_exception(repo):
    payload = json.loads(call_tool(repo, "get_artifact", {"id": "skill/ghost"}))
    assert payload["error"]


def test_build_server_registers_the_tools(repo):
    assert build_server(repo) is not None
```

`tests/test_architecture.py`:

```python
"""The read-only guarantee is structural. This runs as a test, not as a lint step."""

import subprocess
import sys


def test_import_contracts_hold():
    result = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/mcp tests/test_architecture.py -v`
Expected: FAIL — `ModuleNotFoundError` for `harness_library.mcp.server`, and the contract test fails because `setup.cfg` does not exist.

- [ ] **Step 3: Write the import contracts**

`setup.cfg`:

```ini
[importlinter]
root_package = harness_library

[importlinter:contract:layers]
name = Clean Architecture layers
type = layers
layers =
    harness_library.cli
    harness_library.mcp
    harness_library.infrastructure
    harness_library.application
    harness_library.domain
ignore_imports =
    harness_library.cli.context -> harness_library.infrastructure.*

[importlinter:contract:mcp-is-read-only]
name = MCP never imports write use cases
type = forbidden
source_modules = harness_library.mcp
forbidden_modules = harness_library.application.write

[importlinter:contract:domain-is-pure]
name = Domain imports no other layer
type = forbidden
source_modules = harness_library.domain
forbidden_modules =
    harness_library.application
    harness_library.infrastructure
    harness_library.cli
    harness_library.mcp
```

- [ ] **Step 4: Write the MCP server**

`src/harness_library/mcp/server.py`:

```python
"""Read-only stdio MCP server.

Imports from harness_library.application.read ONLY. Enforced by setup.cfg
contract "mcp-is-read-only", which runs in tests/test_architecture.py.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from harness_library.application.read.use_cases import (
    ArtifactFilter,
    ArtifactNotFoundError,
    get_artifact,
    get_artifact_file,
    list_artifacts,
    search_artifacts,
)
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.types import entry_filename_for

TOOL_NAMES = ("list_artifacts", "search_artifacts", "get_artifact", "get_reference")

TOOL_SCHEMAS = [
    types.Tool(
        name="list_artifacts",
        description="List skills and agents in the harness library.",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["skill", "agent"]},
                "tag": {"type": "string"},
            },
        },
    ),
    types.Tool(
        name="search_artifacts",
        description="Full-text search across artifact bodies and references.",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_artifact",
        description="Fetch an artifact's entry file and its file listing.",
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    ),
    types.Tool(
        name="get_reference",
        description="Fetch one reference file from an artifact, without its entry file.",
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "string"}, "path": {"type": "string"}},
            "required": ["id", "path"],
        },
    ),
]


def call_tool(repo: ArtifactRepository, name: str, arguments: dict[str, Any]) -> str:
    """Pure dispatch, separated from transport so it is testable without a pipe."""
    try:
        match name:
            case "list_artifacts":
                artifacts = list_artifacts(
                    repo,
                    ArtifactFilter(type=arguments.get("type"), tag=arguments.get("tag")),
                )
                return json.dumps(
                    [
                        {
                            "id": a.id,
                            "name": a.name,
                            "type": a.type.value,
                            "description": a.description,
                            "tags": list(a.tags),
                            "superseded_by": a.superseded_by,
                            "files": list(a.files),
                        }
                        for a in artifacts
                    ]
                )
            case "search_artifacts":
                matches = search_artifacts(repo, arguments["query"])
                return json.dumps(
                    [
                        {
                            "id": m.artifact_id,
                            "path": m.path,
                            "line": m.line_number,
                            "text": m.line,
                        }
                        for m in matches
                    ]
                )
            case "get_artifact":
                artifact = get_artifact(repo, arguments["id"])
                entry = entry_filename_for(artifact.type, artifact.name)
                return json.dumps(
                    {
                        "id": artifact.id,
                        "files": list(artifact.files),
                        "text": get_artifact_file(repo, artifact.id, entry),
                    }
                )
            case "get_reference":
                return json.dumps(
                    {
                        "id": arguments["id"],
                        "path": arguments["path"],
                        "text": get_artifact_file(repo, arguments["id"], arguments["path"]),
                    }
                )
            case _:
                return json.dumps({"error": f"unknown tool: {name}"})
    except ArtifactNotFoundError as exc:
        return json.dumps({"error": f"not found: {exc}"})
    except (FileNotFoundError, ValueError) as exc:
        return json.dumps({"error": str(exc)})


def build_server(repo: ArtifactRepository) -> Server:
    server: Server = Server("harness-library")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return TOOL_SCHEMAS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=call_tool(repo, name, arguments))]

    return server


async def run_stdio(repo: ArtifactRepository) -> None:
    server = build_server(repo)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
```

- [ ] **Step 5: Add the `hl mcp` command**

Append to `src/harness_library/cli/main.py`:

```python
@app.command("mcp")
def mcp_command(ctx: typer.Context) -> None:
    """Run the read-only MCP server over stdio. Spawned by an MCP client, not by you."""
    import asyncio

    from harness_library.mcp.server import run_stdio

    asyncio.run(run_stdio(ctx.obj))
```

Nothing in this command may print to stdout. stdout belongs to the JSON-RPC stream.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/mcp tests/test_architecture.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 7: Run the whole suite and the linters**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy src`
Expected: all green.

- [ ] **Step 8: Verify by hand in a real client**

Add to `~/.claude/settings.json` (or the project `.mcp.json`):

```json
{
  "mcpServers": {
    "harness-library": {
      "command": "uv",
      "args": ["run", "--directory", "/project/harness-library", "hl", "mcp"],
      "env": { "HL_LIBRARY": "/project/harness-library" }
    }
  }
}
```

Start a session, confirm the four tools appear, call `search_artifacts` with a term you know is in a reference file, and record the result. This is the one thing the suite cannot check. `[spec §10]`

- [ ] **Step 9: Commit**

```bash
git add src/harness_library tests setup.cfg
git commit -m "feat(mcp): add read-only stdio server with structural import contract"
```

---

## Done when

- `hl list`, `hl show`, `hl search`, `hl validate` all work against the real library tree.
- `hl validate` exits 1 and names the rule for every defect in §1 of the spec.
- The four MCP tools respond in a real Claude Code session.
- `uv run pytest && uv run ruff check . && uv run mypy src` is green.
- Nothing in this plan has written to `~/.claude/`.

## Not in this plan

Install, backup, manifest, drift, rollback (Plan 2). The FastAPI JSON API (Plan 3). The React SPA (Plan 4). `hl new` and `hl edit` — they are write use cases and belong with Plan 2.
