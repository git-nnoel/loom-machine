"""Contract C-12 over a real install target — the first code in this project that writes outside it.

This is the sibling of `scanner.py` and the two are **deliberately unalike**. The library scanner
knows the type registry, walks artifact roots, and refuses four kinds of path — a vendor tree, a
nested `.git`, an editor swap file and a symlink — reporting each as a `SkippedPath` for the
assembler to turn into V6. None of that belongs here:

* there is **no registry and no artifact root**. A target is a directory of paths (R43);
* **nothing is filtered.** The same `SKILL.md.swp` the library scanner skips is an ordinary entry
  here, and so is Claude Code's `synced/` bucket — ruling R44 refuses it a named exclusion,
  because a named exclusion hides whatever else lands in that directory as well;
* a **symlink is recorded, not skipped** (R6). It is still never followed and never hashed; what
  changes is that install has to be able to see that the path it was about to write is a link
  pointing somewhere else. That is the whole difference between reporting a library and reporting
  a place you are about to write into.

**What this layer is blind to.** It cannot see whether any path it reports belongs to an artifact,
was installed by this tool, or has drifted. Those are the verdict rule's (C-9, C-10) and the
plan's (T-15); nothing here compares a digest to anything.

**Determinism.** Children are sorted by name at every level, so two scans of one target produce
the same order. The library scanner keeps the same discipline for the same reason: a report that
reorders itself between two runs cannot be diffed or pinned to a golden list.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from harness_library.domain.hashing import hash_bytes
from harness_library.domain.target import TargetFile

FILE_MODE = 0o644
"""The mode every file this repository writes ends up with. F-9, ruling R56.

Set explicitly rather than left to the process umask, because `write` is the only thing that
creates a file in a user's target and a strict umask would otherwise ship them a harness whose
skills their own editor cannot read. Mode is excluded from the content hash (R9, R56), so
normalising it here changes no digest and no verdict.
"""

DIRECTORY_MODE = 0o755
"""The mode every directory this repository creates ends up with. F-9, ruling R56."""

NO_DIGEST: str | None = None
"""What a symlink's `sha256` is: nothing, because nothing was read.

A constant rather than a bare `None` at the call site so the absence is named where it is produced
and where it is asserted. `TargetFile` enforces that only a symlink may carry it.

**Ruling R68 replaced T-14's empty string with `None`.** `""` compares, sorts and renders like a
digest while being none, so an equality test against it silently answers "different" rather than
"unknown"; `None` is the spelling C-10 and C-11 already use for every optional field, and it makes
the absence impossible to mistake for content.
"""


class FilesystemTargetRepository:
    """One install target on disk. Implements contract C-12.

    The protocol stays in `domain/target.py` and is satisfied structurally — this class does not
    inherit it, so `domain/` keeps knowing nothing about who implements it. Ruling R14 settled
    that shape for C-4 and it holds here for the same reason.

    Unlike `FilesystemArtifactRepository`, **no snapshot is held**. That repository caches its scan
    because C-4 promises `get()` and `list_all()` agree within one process; this one writes, so a
    cached scan would go stale at the first `write` and every subsequent `scan` would describe a
    target that no longer exists. Each `scan()` is a fresh walk.
    """

    def __init__(self, target_root: Path) -> None:
        """Open a target.

        Args:
            target_root: the directory to install into. Any directory (R43), not only
                `~/.claude/`.

        Raises:
            FileNotFoundError: `target_root` is not a directory. Creating a target that does not
                exist yet is a policy decision — "this tool is about to start writing into a
                directory nobody has yet" is a thing a user should be told — and it belongs to the
                composition root (T-22), not to a repository constructor that would do it as a
                side effect of being built.
        """
        if not target_root.is_dir():
            raise FileNotFoundError(
                f"{target_root} is not a directory, so it is not an install target"
            )
        self._root = target_root

    # -- Contract C-12 ---------------------------------------------------------------------------

    def scan(self) -> tuple[TargetFile, ...]:
        """Every path in the target, depth-first and name-sorted at each level.

        Nothing is filtered and nothing is interpreted; see the module docstring. A symlink is one
        entry carrying `is_symlink=True` and no digest, and is not descended into.

        Raises:
            OSError: a file could not be read or a directory could not be listed. Deliberately
                **not** swallowed, which is where this parts company with the library scanner: that
                one answers an unreadable directory with no artifacts, and the worst that costs a
                read-only tool is an incomplete report. Here, a path missing from the scan is a
                path the verdict rule is told the target does not hold — judged `CREATE`, and
                written straight over on the next apply.
        """
        return tuple(self._walk(self._root, prefix=""))

    def read_bytes(self, path: str) -> bytes:
        """The raw bytes at one target-relative path. See C-12 for the refusals."""
        located = self._locate(path)
        if located.is_symlink():
            raise ValueError(
                f"{path!r} is a symlink, which is never followed (ruling R6). The scan records it "
                "as one; reading through it is how a target path answers with content from "
                "outside the target"
            )
        return located.read_bytes()

    def write(self, path: str, data: bytes) -> None:
        """Write `data` at one target-relative path, creating the directories it needs.

        Not atomic, and that is a choice rather than an omission. `manifest_store.write_manifest`
        writes through a temporary file and `os.replace` because a half-written manifest is
        unrecoverable; here the same technique would leave a stray `.tmp` file inside the user's
        target whenever a write was interrupted, and that file would read `FOREIGN` on every
        subsequent scan, forever, with nothing able to remove it but the user. T-16's backup is
        the recovery mechanism for an interrupted apply (F-9), and it recovers the whole target
        rather than one file.
        """
        located = self._locate(path)
        if located.is_symlink():
            raise ValueError(
                f"{path!r} is a symlink, which is never written through (ruling R6): the bytes "
                "would land wherever it points, which may be outside the target entirely"
            )
        self._make_parents(located)
        located.write_bytes(data)
        located.chmod(FILE_MODE)

    def delete(self, path: str) -> None:
        """Remove one file, or one symlink, at a target-relative path.

        `os.unlink` removes a symlink **as itself**, which is why this member does not refuse one:
        unlinking a link is the opposite of following it, and refusing here would leave a link
        planted over an installed path impossible to uninstall.
        """
        os.unlink(self._locate(path))

    def exists(self, path: str) -> bool:
        """Whether anything is at this target-relative path, a dangling symlink included."""
        return os.path.lexists(self._locate(path))

    # -- The walk --------------------------------------------------------------------------------

    def _walk(self, directory: Path, *, prefix: str) -> Iterator[TargetFile]:
        """Depth-first over one directory, in name order.

        The symlink test comes **first**, before `is_dir()` and `is_file()`, which both resolve.
        Testing either one first would descend a symlinked directory and hash the files behind it
        as if they were in the target — the escape R6 exists to prevent, and the reason the
        library scanner orders its own checks the same way.
        """
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            relative = f"{prefix}{child.name}"

            if child.is_symlink():
                yield TargetFile(
                    path=relative,
                    sha256=NO_DIGEST,
                    size=child.lstat().st_size,
                    is_symlink=True,
                )
                continue

            if child.is_dir():
                yield from self._walk(child, prefix=f"{relative}/")
                continue

            if not child.is_file():
                # A fifo, a socket or a device node. Passed over because contract C-12 has no
                # channel to report a path it declined — `scan()` returns files and nothing else —
                # and because `read_bytes` on a fifo blocks until something writes to it, which
                # would hang the scan rather than fail it. Flagged to the delivery lead.
                continue

            data = child.read_bytes()
            yield TargetFile(
                path=relative,
                sha256=hash_bytes(data),
                size=len(data),
                is_symlink=False,
            )

    # -- Path safety -----------------------------------------------------------------------------

    def _locate(self, path: str) -> Path:
        """The absolute path of one target-relative path, or a refusal. Three stages, ordered.

        1. **Shape**, before anything touches the disk: empty, `.`, absolute, or any `..`
           component is a `ValueError`. First so the guarantee is a property of the string and
           holds on a target that happens not to contain the escaped-to file.
        2. **No intermediate symlink.** A relative path with no `..` in it still lands outside the
           target if one of its directories is a link, and that is the realistic shape of the
           escape: nobody writes `../../etc`, but a user really does symlink `~/.claude/skills`
           somewhere. Each component but the last is refused if it is a link.
        3. **Containment, re-checked** against the resolved parent. Redundant given 1 and 2, and
           kept for the reason `FilesystemArtifactRepository._resolve` keeps its own third stage:
           it is the one that still holds if a future change loosens either of the others.

        The final component is left alone here — `read_bytes` and `write` refuse a symlink there,
        `delete` removes it, and `exists` reports it.
        """
        pure = PurePosixPath(path)
        if not pure.parts or pure.is_absolute() or any(part == ".." for part in pure.parts):
            raise ValueError(
                f"{path!r} is not a path inside this target: a target path is relative to the "
                "target root, is not empty, and may not climb out of it"
            )

        located = self._root
        for part in pure.parts[:-1]:
            located = located / part
            if located.is_symlink():
                raise ValueError(
                    f"{path!r} passes through {part!r}, which is a symlink: a link is never "
                    "followed (ruling R6), and following this one would leave the target"
                )

        if located.exists() and not located.resolve().is_relative_to(self._root.resolve()):
            raise ValueError(f"{path!r} resolves outside this target")

        return located / pure.parts[-1]

    def _make_parents(self, located: Path) -> None:
        """Create the directories `located` needs, each at `DIRECTORY_MODE`.

        `mkdir(mode=...)` is masked by the process umask, so the mode is set afterwards and only
        on the directories this call actually created — an existing directory the user chose the
        mode of is left exactly as it is.
        """
        missing = [
            ancestor
            for ancestor in located.parents
            if ancestor.is_relative_to(self._root) and not ancestor.exists()
        ]
        located.parent.mkdir(parents=True, exist_ok=True)
        for directory in missing:
            directory.chmod(DIRECTORY_MODE)


__all__ = ["DIRECTORY_MODE", "FILE_MODE", "NO_DIGEST", "FilesystemTargetRepository"]
