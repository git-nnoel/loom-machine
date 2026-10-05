"""Contract C-8 — where a library root comes from, and what makes a directory a library.

Three steps, in order: the `--library` flag, then `$LOOM_LIBRARY`, then the current directory
(charter §13). Each step is a deliberate answer to a different question — the flag is "this run",
the variable is "this shell", the current directory is "the library I am standing in" — so the
precedence is not arbitrary and a test exercises all three, including the one that supplies no flag
at all.

**Resolution fails loudly on a directory that is not a library.** Charter §13 requires it, and the
reason is the failure this product exists to eliminate: a read path that answers "no artifacts"
when the truth is "you are not where you think you are" is confidently wrong, and it is wrong in
the direction a user cannot detect. An empty listing is a fact about a library; it must never also
be the way a missing library looks.

---

**The write side lives here too, and in one place on purpose (T-22).** A target needs five
collaborators that have to agree about which directory they are for — the target repository, the
backup store, the manifest store, the write lock and the manifest already on disk — and four of
the five are keyed by a *canonical* spelling of the target path (R43). Composed at five call
sites, a command could hold a lock on one spelling of a directory and write the manifest of
another; composed once, in `open_target`, it cannot. `TargetSession` is that bundle and every
write command takes one.

**A missing target is refused and never created — ruling R71.** `loom install --target ~/.clade`
on a typo must say so and stop, rather than build a harness in a directory nobody asked for and
report success. The refusal is stated twice by construction: `require_target` here, and
`FilesystemTargetRepository`'s own constructor, which declines to be built over a non-directory
precisely so that this decision stays in the composition root.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from loom.cli.settings import Settings, editor_command
from loom.domain.backup import BackupStore
from loom.domain.errors import EditorFailedError, ErrorCode, HarnessLibraryError
from loom.domain.lock import WriteLock
from loom.domain.manifest import Manifest, ManifestStore
from loom.domain.registry import ARTIFACT_DIRECTORIES
from loom.domain.resolution import ConflictEditor, ConflictVersions
from loom.domain.target import TargetRepository
from loom.infrastructure.backup import FilesystemBackupStore
from loom.infrastructure.editor import SubprocessConflictEditor
from loom.infrastructure.library_yaml import LIBRARY_YAML_FILENAME
from loom.infrastructure.lock import FilesystemWriteLock
from loom.infrastructure.manifest_store import (
    FilesystemManifestStore,
    canonical_target_path,
    default_state_root,
    read_manifest,
)
from loom.infrastructure.repository import FilesystemArtifactRepository
from loom.infrastructure.target import FilesystemTargetRepository

DEFAULT_TARGET_DIRECTORY = ".claude"
"""Where a harness lives under a user's home. The default for `--target`.

A constant rather than a literal in a Typer default, because two spellings of "the user's harness"
is exactly the drift ruling R43 made the target an explicit parameter to avoid. **No test ever
reaches it** — every test names its own target under `tmp_path`, and charter §10 forbids writing
into a real `~/.claude/` outright.
"""


class LibraryRootError(HarnessLibraryError):
    """The library root could not be resolved to a usable library.

    **In the taxonomy since ruling R29.** T-7 raised this class carrying no `ErrorCode` at all,
    because charter §9 forbids inventing a code at a raise site and none covered "this directory is
    not a library". The delivery lead has since ruled `NOT_A_LIBRARY` into the contract, so this is
    now an ordinary `HarnessLibraryError`: `cli/main.py` reports it through the same branch as every
    other typed failure, the exit status comes from the table rather than from a special case, and
    initiative 03 reads a code instead of re-deriving one from an exception type it cannot see.

    Attributes:
        code: always `ErrorCode.NOT_A_LIBRARY`.
        path: the directory that was rejected, as text.
        reason: the human sentence. Not contract.
    """

    code = ErrorCode.NOT_A_LIBRARY

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
            "set LOOM_LIBRARY, or run from inside a library",
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


# ------------------------------------------------------------------------------------------------
# The write side — one target, its five collaborators, and the refusal that comes before them
# ------------------------------------------------------------------------------------------------


class TargetRootError(HarnessLibraryError):
    """The install target could not be used, and **nothing was created**. Ruling R71.

    `TARGET_UNWRITABLE` rather than a code of its own: to a caller "the directory is not there"
    and "the directory will not take a write" are one situation with one remedy — look at the
    path you passed — and C-14 already says that status exists to send a user with a typo in
    `--target` to the right one of the two directories. `LibraryRootError` is this class's mirror
    on the read side, over `NOT_A_LIBRARY`, and the pairing is the point: a run that cannot start
    says which of the two directories it could not use.

    Attributes:
        code: always `ErrorCode.TARGET_UNWRITABLE`.
        path: the directory that was rejected, as text.
        reason: the human sentence. Not contract.
    """

    code = ErrorCode.TARGET_UNWRITABLE

    def __init__(self, path: Path, reason: str) -> None:
        self.path = str(path)
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class TargetNotInstalledError(HarnessLibraryError):
    """Nothing has been installed into this target, so there is nothing to act on.

    **The answer `clean_foreign` refused to make expressible**, in the place it said the answer
    belongs. That use case requires a manifest and argues why: `clean --foreign` against a target
    no manifest describes means *"every path here is foreign, remove them all"* — `rm -rf`
    reached through a plan. Uninstall, rollback and prune each require one for the same reason,
    and an absent record is never an empty one (C-11).

    `ARTIFACT_NOT_FOUND` and therefore exit 3, reusing the code rather than inventing one — the
    shape `NothingToResolveError` already uses, and for its reading of that code: *the thing you
    asked to act on is not here, so go and look at what is*. The commonest cause is a mistyped
    `--target`, and NOT_FOUND sends a user to look at what they asked for rather than at a
    directory that is perfectly fine.

    Attributes:
        code: always `ErrorCode.ARTIFACT_NOT_FOUND`.
        path: the target that holds nothing this tool installed, as text.
        operation: what was being attempted. Not contract; a diagnosis.
    """

    code = ErrorCode.ARTIFACT_NOT_FOUND

    def __init__(self, path: Path, operation: str) -> None:
        self.path = str(path)
        self.operation = operation
        super().__init__(
            f"nothing is installed in {path}: no manifest records an install here, so there is "
            f"nothing to {operation}. Check --target, or run loom install first"
        )


@dataclass(frozen=True, slots=True)
class TargetSession:
    """Everything a write command needs about one target, resolved once.

    Five collaborators and a value, and the reason they are one object is that four of them are
    keyed by the *canonical* spelling of the target path (R43, `canonical_target_path`). Composed
    separately, a command could take the lock on `~/.claude` and write the manifest of
    `~/.claude/` — two files, one directory, no protection at all. Composed here, the spelling is
    computed once and every collaborator is built from the same `Path`.

    Attributes:
        root: the resolved target directory. Absolute, because every diagnosis below this point
            quotes it.
        target_path: the canonical spelling the manifest records and the store keys by. What
            every write use case's `target_path` argument is given.
        target: contract C-12, the directory being read and written.
        backups: contract C-13.
        manifests: contract C-15, the seam apply writes its record through.
        lock: contract C-16, charter §12. One per session, and every write use case takes it —
            **sequentially**. The lock is not re-entrant, so a command that runs two use cases
            runs them one after the other and never nests them.
        manifest: contract C-11, what was last installed here, or `None` when nothing was. **Read
            once**, here, and handed to every use case as a value, so a command judges one
            snapshot. A command that runs two write use cases takes the second one's `manifest`
            from the **first one's result**, never from this field: `ManifestStore` has one
            member and nothing in `application/` can refresh a record it did not write.
    """

    root: Path
    target_path: str
    target: TargetRepository
    backups: BackupStore
    manifests: ManifestStore
    lock: WriteLock
    manifest: Manifest | None


def default_target_root() -> Path:
    """`~/.claude`, the harness a user actually runs. Computes; never creates."""
    return Path.home() / DEFAULT_TARGET_DIRECTORY


def require_target(root: Path) -> Path:
    """`root`, absolute, once it is known to be a usable install target. Otherwise a refusal.

    **Ruling R71: a missing directory is not created.** The temptation is real — `mkdir -p` is one
    line and the next line would install successfully — and it is the failure this whole
    initiative exists to prevent, one directory up: `loom install --target ~/.clade` would build a
    complete harness in a typo, report success, and leave the user's real one untouched and their
    disk holding a tree nothing will ever look at again. A directory that does not exist is a
    question, and this tool asks it rather than answering it.

    Raises:
        TargetRootError: the path does not exist or is not a directory.
    """
    absolute = root.expanduser().resolve()
    if not absolute.exists():
        raise TargetRootError(
            absolute,
            "no such directory. An install target is never created: pass --target with a "
            "directory that exists, or create it yourself first",
        )
    if not absolute.is_dir():
        raise TargetRootError(absolute, "not a directory, so it is not an install target")
    return absolute


def open_target(explicit: Path | None = None, *, state_root: Path | None = None) -> TargetSession:
    """Resolve the target and open everything a write command needs over it, in one call.

    Args:
        explicit: the `--target` flag, or `None` for `~/.claude`. Any directory (R43).
        state_root: where the manifests, the backups and the sentinel live.
            `default_state_root()` when omitted; a test passes `tmp_path` and therefore never
            touches the developer's own state directory.

    Returns:
        A `TargetSession`. The manifest is read here and nowhere else in the command.

    Raises:
        TargetRootError: the target does not exist or is not a directory (R71).
        ManifestError: this target has a manifest and it cannot be used. An **absent** manifest
            is not an error and comes back as `None` — a first install must work.
    """
    root = require_target(explicit if explicit is not None else default_target_root())
    state = state_root if state_root is not None else default_state_root()
    return TargetSession(
        root=root,
        target_path=canonical_target_path(root),
        target=FilesystemTargetRepository(root),
        backups=FilesystemBackupStore(state, root),
        manifests=FilesystemManifestStore(state),
        lock=FilesystemWriteLock(root, state_root=state),
        manifest=read_manifest(root, state_root=state),
    )


class ReportingConflictEditor:
    """A `ConflictEditor` that gives the editor's `OSError` ruling R102's code.

    Satisfies `domain.resolution.ConflictEditor` **structurally**, like every other implementation
    of a protocol in this project (R14).

    **Two lines, and a class rather than a `try` around `compare_versions`.** That call also
    reaches the library repository, whose `read_bytes` raises a bare `OSError` for a permission
    fault that has nothing whatever to do with an editor; a translation wide enough to catch the
    editor's failure would relabel that one `EDITOR_FAILED` and send the user to their shell
    configuration for a file they cannot read. Wrapping the seam instead makes the translation
    exactly as wide as the thing it is about.

    Ruling R24's posture, one layer further out than usual: `application/` is normally where a
    builtin becomes a code, and C-6 was frozen while T-21 built the seam, so `compare_versions`
    documents the `OSError` and lets it out. R102 closes that and this is where it lands.
    """

    def __init__(self, inner: ConflictEditor, *, command: Sequence[str]) -> None:
        """Wrap a real editor seam.

        Args:
            inner: the editor that actually materialises the versions and spawns the process.
            command: what it will run, kept only so the diagnosis can name it. A user told "the
                editor could not be run" and not *which* editor has been told nothing.
        """
        self._inner = inner
        self._command = tuple(command)

    def compare(self, versions: tuple[ConflictVersions, ...]) -> None:
        """Show both versions, or fail with a code.

        Raises:
            EditorFailedError: the versions could not be materialised, or the command could not
                be run or exited non-zero. **Nothing was written and nothing was recorded** —
                `compare_versions` decides nothing, so the refused path is refused exactly as it
                was.
        """
        try:
            self._inner.compare(versions)
        except OSError as error:
            raise EditorFailedError(" ".join(self._command), str(error)) from error


def open_editor(workspace: Path, *, settings: Settings | None = None) -> ConflictEditor:
    """The `$EDITOR` seam, resolved and wrapped. Ruling R104.

    Args:
        workspace: the directory both versions are materialised under. Supplied by the caller —
            `loom` uses a `TemporaryDirectory` that is removed however the run ends — so that a
            user's content is never written somewhere this module chose, and never inside the
            target.
        settings: the environment reader (ruling R2).

    Raises:
        EditorFailedError: `$EDITOR` is unset, blank or unsplittable. Raised **before** the
            workspace is touched, so a misconfigured editor leaves nothing behind.
    """
    command = editor_command(settings)
    return ReportingConflictEditor(
        SubprocessConflictEditor(command, workspace=workspace), command=command
    )


__all__ = [
    "DEFAULT_TARGET_DIRECTORY",
    "LibraryRootError",
    "ReportingConflictEditor",
    "TargetNotInstalledError",
    "TargetRootError",
    "TargetSession",
    "default_target_root",
    "is_library",
    "open_editor",
    "open_library",
    "open_target",
    "require_library",
    "require_target",
    "resolve_library_root",
]
