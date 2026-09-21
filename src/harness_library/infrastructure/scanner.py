"""The scanner — the layer where every pure guarantee above finally meets a real filesystem.

`domain/assembly.py` decides all of charter §8 from literals, and `tests/domain/test_assembly.py`
says in its own docstring what that cannot prove: that the scanner *records* a symlink as skipped,
only that a recorded skip becomes a V6 warning. Same for V1 — the domain suite proves a
`RawArtifact` with no entry produces V1; only this module can produce that value from a real
directory that really has no `SKILL.md`. Everything here is tested against real files (§10).

**It decides, it never judges.** The scanner reads the tree, hashes what it takes, and records what
it refused and why. It emits no `ValidationFinding` and knows no rule. That division is the seam
DEC-1 bought: `SkippedPath` in, V6 out, exactly as `DuplicateKey` in, V9 out — and, since ruling
R46, `SymlinkedRoot` in, V11 out. The third one is the seam's sharpest case: the value describes an
artifact that does not exist, which only a scanner can know and only a rule can call a fault.

**Derived, never composed.** `kind`, the artifact root path and the entry document's path are
properties of the type registry, reached through `TypeSpec.root_path` / `TypeSpec.entry_path` and
never built by string concatenation here. A second source of truth for the disk layout is how a
scanner and a validator drift, and the copy nobody edits is the one that goes stale.

**Deterministic order.** Children are sorted by name at every level, so `files` and `skipped` are
stable across two scans of one library — the same discipline V7, V8 and V9 already keep, and the
precondition for any golden-literal test over a real tree.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import frontmatter

from harness_library.domain.artifact import ArtifactFile, ArtifactKind
from harness_library.domain.hashing import hash_bytes
from harness_library.domain.raw import (
    EntryParseError,
    LibraryScan,
    RawArtifact,
    RawEntry,
    SkippedPath,
    SkipReason,
    SymlinkedRoot,
)
from harness_library.domain.registry import ARTIFACT_TYPE_SPECS, ENTRY_SUFFIX, TypeSpec
from harness_library.infrastructure.timestamps import ArtifactTimestamps, GitTimestamps

VENDOR_DIRECTORY_NAMES = frozenset({"node_modules", "vendor", "venv", ".venv"})
"""Checked-in dependency trees. Skipped whole and **never descended** — charter §8 names them, and
descending one turns a scan of a skill into a scan of a package manager's output."""

NESTED_REPOSITORY_NAME = ".git"
"""A git directory under an artifact root. Skipped as `OTHER` rather than as a vendor tree: it is
not a vendored dependency, and `SkipReason.OTHER` exists precisely so a scanner never has to choose
between silence and a domain change."""

EDITOR_SWAP_SUFFIXES = (".swp", ".swo", ".swn")
"""Vim's swap files. Observed destroying real content when a copy took them along."""


def scan_library(
    library_root: Path, *, timestamps: ArtifactTimestamps | None = None
) -> LibraryScan:
    """Walk a library root and produce one `RawArtifact` per artifact, for the assembler.

    Args:
        library_root: the library's root directory — the one holding `skills/` and `agents/`.
        timestamps: how ruling R5 is answered. Defaults to `GitTimestamps` over `library_root`,
            which is the real rule; injectable so a test that is not about R5 does not pay for a
            subprocess and does not depend on the repository it happens to be running inside.

    Returns:
        A `LibraryScan`: every artifact found, ordered by type directory and then by name, **plus
        every artifact root that is a symlink** and was therefore not walked (V11, R46).
        **Nothing is filtered** — a skill directory with no entry document comes back as a
        `RawArtifact` with `entry=None`, which is what makes V1 fire. An artifact that is
        invisible because it is broken is the failure this product exists to close, and a
        symlinked root is the last shape of it: invisible because it was never read.

        One value rather than two returns, so a caller cannot take the artifacts and lose the
        roots — which would be the very omission V11 reports.

    A directory the registry does not own is passed over in silence, and a missing `skills/` or
    `agents/` is simply no artifacts of that type. Deciding that a directory is not a library at all
    belongs to the composition root (contract C-8), which fails loudly; a scanner that raised here
    could not scan a library that holds only agents.
    """
    resolved = timestamps if timestamps is not None else GitTimestamps(library_root)
    artifacts: list[RawArtifact] = []
    symlinked: list[SymlinkedRoot] = []
    for spec in ARTIFACT_TYPE_SPECS.values():
        _scan_type(library_root, spec, resolved, artifacts, symlinked)
    return LibraryScan(artifacts=tuple(artifacts), symlinked_roots=tuple(symlinked))


def _scan_type(
    library_root: Path,
    spec: TypeSpec,
    timestamps: ArtifactTimestamps,
    artifacts: list[RawArtifact],
    symlinked: list[SymlinkedRoot],
) -> None:
    """Every artifact of one type, in name order, and every symlinked root beside them.

    **The two `is_symlink()` questions below are deliberately separate statements**, and fusing
    them would be a mistake that hides itself. `_symlinked_root` answers *should this be
    reported* (V11); `_artifact_name` answers *may this be walked* (R6). They happen to test the
    same predicate today and they are not one decision: the whole point of V11 is that the
    refusal and the report are two facts, so that removing the refusal leaves the warning
    standing and removing the warning leaves the refusal standing. One `if` doing both would make
    each mutation take its own control away.
    """
    directory = library_root / spec.directory
    if not directory.is_dir():
        return
    for child in _sorted_children(directory):
        root = _symlinked_root(child, spec)
        if root is not None:
            symlinked.append(root)
        name = _artifact_name(child, spec)
        if name is None:
            continue
        artifacts.append(_scan_artifact(library_root, spec, name, timestamps))


def _symlinked_root(child: Path, spec: TypeSpec) -> SymlinkedRoot | None:
    """This child as a V11 subject, or `None` when it is not a symlinked artifact root.

    Two narrowings, and both are about false positives rather than about R6:

    * a child that is not a link at all is not this rule's business;
    * under a `FILE`-kind type only a `.md` child could ever have been an artifact, so a linked
      `agents/notes.txt` is passed over exactly as an unlinked one is. Under a `DIRECTORY`-kind
      type **every** link is reported, because deciding whether one points at a directory means
      `is_dir()`, which follows it — the thing R6 forbids. A linked `skills/README.md` therefore
      warns, and the message says what it says: this path is a link, and if it was meant to be an
      artifact it is not in the library.

    A link whose name cannot be an identity — `agents/.md`, whose stem is empty — is passed over
    rather than raised on: the scan of a whole library must not die on one unnameable link.
    """
    if not child.is_symlink():
        return None
    if spec.kind is ArtifactKind.DIRECTORY:
        name = child.name
    elif child.suffix != ENTRY_SUFFIX:
        return None
    else:
        name = child.stem
    if not name:
        return None
    return SymlinkedRoot(type=spec.type, name=name, destination=_link_destination(child))


def _artifact_name(child: Path, spec: TypeSpec) -> str | None:
    """The artifact name this child announces, or `None` when it is not an artifact root.

    `is_symlink` is tested **before** `is_dir` and `is_file`, which both follow links (ruling R6).
    A symlinked artifact root is therefore not followed and not scanned — **and, since ruling
    R46, it is reported**: `_scan_type` records it as a `SymlinkedRoot` and the assembler turns
    that into V11, so the omission this line creates is now visible instead of silent.

    It is still not turned into a `RawArtifact`. Doing that would fire V1 against a symlinked
    skill that loads perfectly, and a false ERROR is worse than a reported absence.
    """
    if child.is_symlink():
        return None
    if spec.kind is ArtifactKind.DIRECTORY:
        return child.name if child.is_dir() else None
    if not child.is_file() or child.suffix != ENTRY_SUFFIX:
        return None
    return child.stem


def _scan_artifact(
    library_root: Path, spec: TypeSpec, name: str, timestamps: ArtifactTimestamps
) -> RawArtifact:
    """One artifact root, walked."""
    root = library_root / spec.root_path(name)
    if spec.kind is ArtifactKind.DIRECTORY:
        files, skipped = _walk(root, prefix="")
    else:
        # A `FILE`-kind artifact *is* its entry document: the root is the file, and its single
        # `ArtifactFile.path` is its own basename — which the registry, not this module, decides.
        files, skipped = _read_single_file(root, spec.entry_path(name))

    stamp = timestamps.for_artifact(root, [root / file.path for file in files])
    return RawArtifact(
        type=spec.type,
        name=name,
        updated_at=stamp.updated_at,
        files=files,
        skipped=skipped,
        entry=_read_entry(root, spec, name, files),
        is_dirty=stamp.is_dirty,
    )


# ------------------------------------------------------------------------------------------------
# The walk, and the skip decisions of ruling R6 and charter §8
# ------------------------------------------------------------------------------------------------


def _walk(root: Path, *, prefix: str) -> tuple[tuple[ArtifactFile, ...], tuple[SkippedPath, ...]]:
    """Depth-first over one artifact root, in name order at every level."""
    files: list[ArtifactFile] = []
    skipped: list[SkippedPath] = []
    _walk_into(root, prefix=prefix, files=files, skipped=skipped)
    return tuple(files), tuple(skipped)


def _walk_into(
    directory: Path, *, prefix: str, files: list[ArtifactFile], skipped: list[SkippedPath]
) -> None:
    for child in _sorted_children(directory):
        relative = f"{prefix}{child.name}"

        # Ruling R6 first, and before anything that would follow the link. `is_dir()` and
        # `is_file()` both resolve, so testing either one first would silently walk a symlinked
        # directory — which is exactly the escape R6 exists to prevent, since a link resolving
        # outside the artifact root is how a copy writes outside its target.
        if child.is_symlink():
            skipped.append(SkippedPath(relative, SkipReason.SYMLINK, detail=_link_target(child)))
            continue

        if child.is_dir():
            if child.name in VENDOR_DIRECTORY_NAMES:
                skipped.append(SkippedPath(relative, SkipReason.VENDOR_TREE))
                continue
            if child.name == NESTED_REPOSITORY_NAME:
                skipped.append(
                    SkippedPath(relative, SkipReason.OTHER, detail="a nested git directory")
                )
                continue
            _walk_into(child, prefix=f"{relative}/", files=files, skipped=skipped)
            continue

        if _is_editor_swap(child.name):
            skipped.append(SkippedPath(relative, SkipReason.EDITOR_SWAP))
            continue

        if not child.is_file():
            skipped.append(SkippedPath(relative, SkipReason.OTHER, detail="not a regular file"))
            continue

        scanned = _read_file(child, relative)
        if scanned is None:
            skipped.append(SkippedPath(relative, SkipReason.OTHER, detail="could not be read"))
            continue
        files.append(scanned)


def _sorted_children(directory: Path) -> list[Path]:
    """This directory's entries, by name. An unreadable directory contributes nothing.

    Sorted because determinism is a property this whole layer is asserted on: `files` and `skipped`
    both reach a report, and a report that reorders itself between two scans of one library cannot
    be diffed, pinned to a golden literal, or trusted.
    """
    try:
        return sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:  # pragma: no cover - a directory the scan cannot list yields no artifacts
        return []


def _is_editor_swap(name: str) -> bool:
    """Whether a filename is an editor's leftovers rather than content.

    Vim's `.swp` family, Emacs' `#file#` autosaves and `.#file` lock links, and the trailing-tilde
    backup that half the editors in the world still write.
    """
    if name.endswith(EDITOR_SWAP_SUFFIXES):
        return True
    if name.endswith("~") and len(name) > 1:
        return True
    if name.startswith(".#") and len(name) > 2:
        return True
    return len(name) > 2 and name.startswith("#") and name.endswith("#")


def _link_destination(link: Path) -> str:
    """The raw target a symlink names, unresolved.

    Deliberately `readlink` and not `resolve`: the target is reported so a reader can see *where the
    link pointed*, and resolving it would both follow the link R6 forbids following and turn a
    broken link into an error. A relative target keeps its `..` components, which is the whole
    diagnosis when the link escapes the artifact root.
    """
    try:
        return os.readlink(link)
    except OSError:  # pragma: no cover - it was a symlink a moment ago
        return "(unreadable)"


def _link_target(link: Path) -> str:
    """A symlink's destination as `SkippedPath.detail` renders it — the arrow included."""
    return f"-> {_link_destination(link)}"


# ------------------------------------------------------------------------------------------------
# Reading files
# ------------------------------------------------------------------------------------------------


def _read_single_file(
    root: Path, relative: str
) -> tuple[tuple[ArtifactFile, ...], tuple[SkippedPath, ...]]:
    """The one file of a `FILE`-kind artifact, under the path the registry gives it."""
    scanned = _read_file(root, relative)
    if scanned is None:
        return (), (SkippedPath(relative, SkipReason.OTHER, detail="could not be read"),)
    return (scanned,), ()


def _read_file(path: Path, relative: str) -> ArtifactFile | None:
    """One file, read once: hashed, sized and classified. `None` when it cannot be read.

    The bytes are read a single time and never re-read — `content_hash_of_files` reuses these
    per-file digests, so a scan costs one pass over the library and not two.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return ArtifactFile(
        path=relative,
        sha256=hash_bytes(data),
        size=len(data),
        is_text=is_text(data),
    )


def is_text(data: bytes) -> bool:
    """Whether a file is searchable and diffable. Charter §7 decides this **per file**.

    A NUL byte or a failed UTF-8 decode makes it binary. Binary content is still stored, hashed,
    exported and installed — it is only never searched or diffed, which is T-6's concern and not
    this module's. Public because "what counts as text" is a question worth pinning on its own,
    separately from what a scan does with the answer.
    """
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _read_entry(
    root: Path, spec: TypeSpec, name: str, files: Sequence[ArtifactFile]
) -> RawEntry | None:
    """The parsed entry document, or `None` — which is what makes V1 fire.

    `None` covers every way the document fails to be there for a reader: absent, skipped as a
    symlink (R6 — a symlinked `SKILL.md` is never followed, so the artifact really does load as
    nothing), or not decodable as text. Each of those is honestly "there is no entry document
    here", which is the fault V1 names.

    A frontmatter block that does not parse is **not** one of them, and is not a raise either. The
    document exists, so V1 would be a lie. It is carried with an empty frontmatter mapping, the
    whole text as its body, and an `EntryParseError` saying what the parser objected to and where —
    which is V10 (ruling R33). The flag this docstring used to carry, asking for a dedicated code,
    was answered by T-9: the fault it described happened on the first run against real content.
    """
    entry_path = spec.entry_path(name)
    if not any(file.path == entry_path for file in files):
        return None
    target = root if spec.kind is ArtifactKind.FILE else root / entry_path
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return _parse_entry(text)


def _parse_entry(text: str) -> RawEntry:
    """Split an entry document into its frontmatter and its body.

    A failure is **recorded, not swallowed**: it comes back as `RawEntry.parse_error`, which the
    assembler turns into V10. The body is still the whole text, so the document stays searchable and
    V3 still has something to read — a file that will not parse is exactly the one a user needs to
    be able to look at.
    """
    try:
        parsed = frontmatter.loads(text)
    # Every parse failure, not just YAML's: the handler is chosen by the document's own delimiters,
    # so narrowing this to `yaml.YAMLError` would let a TOML or JSON header crash the scan.
    except Exception as failure:
        return RawEntry(frontmatter={}, body=text, parse_error=_parse_error_from(failure))
    return RawEntry(frontmatter=dict(parsed.metadata), body=parsed.content)


def _parse_error_from(failure: Exception) -> EntryParseError:
    """The parser's own complaint, as the pure value V10 reports.

    **The position is the entry document's, not the frontmatter block's**, which is what makes it
    usable: the user opens the file and goes to that line. The two coincide because the handler
    splits on the delimiter line and hands the parser everything after it, leaving a blank first
    line where the opening `---` stood. That alignment is a property of the library rather than of
    this function, so it is pinned as a golden literal in the infrastructure suite instead of being
    recomputed here — a fixed offset applied on both sides would agree with itself forever (L12).

    `problem` is preferred over `str(failure)` because the latter re-states the position this value
    already carries as fields, and a message that repeats its own coordinates renders twice.
    """
    problem = getattr(failure, "problem", None)
    context = getattr(failure, "context", None)
    if isinstance(problem, str) and problem.strip():
        message = problem.strip()
        if isinstance(context, str) and context.strip():
            message = f"{context.strip()}: {message}"
    else:
        message = " ".join(str(failure).split()) or type(failure).__name__

    mark = getattr(failure, "problem_mark", None)
    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    return EntryParseError(
        message=message,
        line=line + 1 if isinstance(line, int) and line >= 0 else None,
        column=column + 1 if isinstance(column, int) and column >= 0 else None,
    )


__all__ = [
    "EDITOR_SWAP_SUFFIXES",
    "NESTED_REPOSITORY_NAME",
    "VENDOR_DIRECTORY_NAMES",
    "is_text",
    "scan_library",
]
