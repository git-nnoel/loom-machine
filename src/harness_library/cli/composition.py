"""Contract C-8 — where a library root comes from, and what makes a directory a library.

Three steps, in order: the `--library` flag, then `$HL_LIBRARY`, then the current directory
(charter §13). Each step is a deliberate answer to a different question — the flag is "this run",
the variable is "this shell", the current directory is "the library I am standing in" — so the
precedence is not arbitrary and a test exercises all three, including the one that supplies no flag
at all.

**Resolution fails loudly on a directory that is not a library.** Charter §13 requires it, and the
reason is the failure this product exists to eliminate: a read path that answers "no artifacts"
when the truth is "you are not where you think you are" is confidently wrong, and it is wrong in
the direction a user cannot detect. An empty listing is a fact about a library; it must never also
be the way a missing library looks.
"""

from __future__ import annotations

from pathlib import Path

from harness_library.cli.settings import Settings
from harness_library.domain.registry import ARTIFACT_DIRECTORIES
from harness_library.infrastructure.library_yaml import LIBRARY_YAML_FILENAME
from harness_library.infrastructure.repository import FilesystemArtifactRepository


class LibraryRootError(Exception):
    """The library root could not be resolved to a usable library.

    **Deliberately outside `ErrorCode`.** Charter §9 says a code is added to the taxonomy before it
    is emitted, and no code covers "this directory is not a library"; inventing one at this raise
    site is the exact thing §9 forbids. This failure happens during composition, before any typed
    error can be raised, and it maps to its own exit status rather than through the code table. See
    `cli.exit_codes.LIBRARY_UNUSABLE`.

    Flagged to the delivery lead: initiative 03 must return an HTTP status for this same condition,
    and at that point it needs a code in the contract rather than an exception the API cannot see.

    Attributes:
        path: the directory that was rejected, as text.
        reason: the human sentence. Not contract.
    """

    def __init__(self, path: Path, reason: str) -> None:
        self.path = str(path)
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def resolve_library_root(explicit: Path | None = None, *, settings: Settings | None = None) -> Path:
    """The library root, by contract C-8's precedence. Charter §13.

    Args:
        explicit: the `--library` flag, or `None` when it was not given.
        settings: the environment reader (ruling R2). Constructed here when omitted, and injected
            by tests so that proving the precedence never requires mutating `os.environ` in a
            process other tests share.

    Returns:
        The resolved directory, made absolute. Absolute because every diagnosis below this point
        quotes the path, and a relative one is unreadable in a message the user sees after the
        fact.

    Raises:
        LibraryRootError: the resolved path does not exist, is not a directory, or is a directory
            that holds no library.
    """
    resolved = settings if settings is not None else Settings()
    root = explicit if explicit is not None else resolved.library
    return require_library(Path.cwd() if root is None else Path(root))


def require_library(root: Path) -> Path:
    """`root`, absolute, once it is known to be a library. Otherwise a loud failure.

    Raises:
        LibraryRootError: with a sentence naming what was looked for, because "not a library" on
            its own tells a user nothing about how to fix it.
    """
    absolute = root.expanduser().resolve()
    if not absolute.exists():
        raise LibraryRootError(absolute, "no such directory")
    if not absolute.is_dir():
        raise LibraryRootError(absolute, "not a directory")
    if not is_library(absolute):
        expected = ", ".join([*ARTIFACT_DIRECTORIES, LIBRARY_YAML_FILENAME])
        raise LibraryRootError(
            absolute,
            f"not a harness library: expected it to contain one of {expected}. Pass --library, "
            "set HL_LIBRARY, or run from inside a library",
        )
    return absolute


def is_library(root: Path) -> bool:
    """Whether a directory holds a library.

    A library is a directory carrying `library.yaml` or at least one artifact directory. The
    artifact directories are read from the type registry rather than restated, so adding a type
    cannot leave this test behind knowing only about skills and agents.

    A library whose `skills/` directory is *empty* is still a library, and lists as empty — that is
    a true answer. A directory with none of these is not a library, and saying so is the whole
    point of charter §13.
    """
    if (root / LIBRARY_YAML_FILENAME).is_file():
        return True
    return any((root / directory).is_dir() for directory in ARTIFACT_DIRECTORIES)


def open_library(
    explicit: Path | None = None, *, settings: Settings | None = None
) -> FilesystemArtifactRepository:
    """Resolve the root and open the library over it. The composition root, in one call.

    This is the only place in the project that constructs a repository, so every adapter — and
    T-8's server, which is handed the result rather than resolving its own — reads one library by
    one set of rules.

    Raises:
        LibraryRootError: the root could not be resolved (see `resolve_library_root`).
    """
    return FilesystemArtifactRepository(resolve_library_root(explicit, settings=settings))


__all__ = [
    "LibraryRootError",
    "is_library",
    "open_library",
    "require_library",
    "resolve_library_root",
]
