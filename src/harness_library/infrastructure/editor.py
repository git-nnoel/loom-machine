"""`$EDITOR` over two versions of a refused path — the one implementation of `ConflictEditor`.

**This is the only place in the project that hands control to a program the user chose**, and the
whole of the design is about keeping that fact behind a seam. `application/write/resolve.py` calls
`compare`; it knows nothing about temporary files, argument vectors or processes, and every test
of `--resolve` runs against a fake. A use case that reached for `subprocess` itself would make the
suite launch an editor, and a test that launches `$EDITOR` is a test that hangs CI on a buffer
nobody will ever close.

**The editor command is a constructor parameter and is never read from the environment here.**
Charter §13 keeps every `os.environ` lookup in `cli/settings.py`, so the composition root resolves
`$EDITOR` and hands the result down — the same division `default_state_root()` already keeps for
the manifest store. It is a full argument vector rather than a string, because a user's `$EDITOR`
is routinely `code --wait` or `vim -d` and splitting one here would be a second, worse shell.

**No merge, and nothing is read back.** Ruling R54 and spec §8.5: the editor exists so the user
can *see* both versions, and the decision they reach is then spelled as `--resolve library` or
`--resolve target`. Whatever they leave in the buffer is discarded with the workspace, which is
why the workspace is somewhere harmless and never inside the target.

**The workspace mirrors the real relative paths**, one directory per side. `library/skills/x/
SKILL.md` beside `target/skills/x/SKILL.md` keeps the extension — so the editor picks the right
syntax highlighting — keeps the basename, so a split window is legible, and keeps two files with
the same name apart, which a flat directory could not do. Nothing is written outside the
workspace: the paths come from a plan, so they are target-relative, but they are re-checked here
anyway rather than trusted.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from harness_library.domain.resolution import ConflictVersions

LIBRARY_DIRECTORY = "library"
"""Where the library's version of each path is materialised, inside the workspace."""

TARGET_DIRECTORY = "target"
"""Where the target's version of each path is materialised, inside the workspace."""


def run_editor(argv: Sequence[str]) -> None:
    """Run the editor and wait for it. The default runner, and the only line that spawns.

    Split out so that `tests/infrastructure/test_editor.py` can assert the argument vector and the
    files behind it without launching anything — the constraint on this task is absolute and the
    seam is one parameter.

    Raises:
        OSError: the command could not be run, or exited non-zero. `CalledProcessError` is an
            `OSError` subclass, so both reach the caller as the builtin `ConflictEditor` documents
            (ruling R24's posture: `application/` is where a failed syscall becomes a code).
    """
    subprocess.run(list(argv), check=True)


class SubprocessConflictEditor:
    """`ConflictEditor` over a real editor process. Satisfies the protocol structurally (R14).

    Attributes are all constructor-supplied, because every one of them is a policy this layer
    must not choose: which editor, where the temporary files go, and what "run" means.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        workspace: Path,
        run: Callable[[Sequence[str]], None] = run_editor,
    ) -> None:
        """Open an editor seam.

        Args:
            command: the editor's argument vector, already split — `["vim", "-d"]`, `["code",
                "--wait"]`. The materialised files are appended to it. Never a string, and never
                read from `$EDITOR` here: charter §13 keeps the environment in `cli/settings.py`.
            workspace: the directory the versions are materialised under. Created if it does not
                exist. Supplied rather than invented so that the composition root owns where a
                user's content is written and a test owns `tmp_path` — a class that called
                `mkdtemp` itself would leave a suite no way to see what it wrote.
            run: how the command is run. The default really launches a process; a test passes a
                recorder, which is the whole reason no test in this project starts an editor.

        Raises:
            ValueError: `command` is empty. An editor seam with no editor would materialise the
                versions and then silently do nothing, which is the failure mode this product
                exists to eliminate rather than reproduce.
        """
        if not command:
            raise ValueError(
                "a conflict editor needs a command to run: an empty one would write both "
                "versions out and then quietly do nothing, which looks exactly like a user who "
                "decided not to resolve anything"
            )
        self._command = tuple(command)
        self._workspace = workspace
        self._run = run

    def compare(self, versions: tuple[ConflictVersions, ...]) -> None:
        """Materialise every version pair and open them all in one editor session.

        A single invocation for the whole artifact, as the protocol requires: an artifact's
        refused paths are one decision. An **empty** tuple runs nothing at all — there is nothing
        to show, and launching an editor on no files would leave a user staring at a blank buffer
        wondering what this tool thought it was asking.

        A side that is absent, or that could not be read (R72), contributes **no file**. Writing
        an empty one would say "this version is empty", which is a different and confidently
        wrong answer from "this version does not exist"; the reason is in the report the caller
        renders, and the missing pane is the honest signal.

        Raises:
            OSError: the versions could not be written, or the editor could not be run or exited
                non-zero. A builtin, as `ConflictEditor` documents.
            ValueError: a version's path is empty, absolute or climbs out of the workspace with
                `..`. It came from a plan and so cannot be any of those; re-checked here anyway,
                because this is the one class in the project that writes a user's content to a
                directory chosen by someone else.
        """
        if not versions:
            return

        files: list[str] = []
        for version in versions:
            for directory, content in (
                (LIBRARY_DIRECTORY, version.library),
                (TARGET_DIRECTORY, version.target),
            ):
                if content is None:
                    continue
                files.append(str(self._materialise(directory, version.path, content)))

        self._run([*self._command, *files])

    def _materialise(self, directory: str, path: str, content: bytes) -> Path:
        """Write one side's bytes under the workspace, at the path the target spells it.

        Bytes and never text: a refused path can hold anything, charter §7 keeps binary content
        readable without decoding it, and a round trip through `str` does not survive one. What
        the editor makes of a binary buffer is the editor's business and the user's.
        """
        located = self._locate(directory, path)
        located.parent.mkdir(parents=True, exist_ok=True)
        located.write_bytes(content)
        return located

    def _locate(self, directory: str, path: str) -> Path:
        """The absolute path of one materialised version, or a refusal.

        The same shape check `FilesystemTargetRepository._locate` makes first, and for the same
        reason: it is a property of the string, so it holds on a workspace that happens not to
        contain the escaped-to file. There is no symlink stage here — this class creates every
        directory it writes into, under a root nothing else touches.
        """
        pure = PurePosixPath(path)
        if not pure.parts or pure.is_absolute() or any(part == ".." for part in pure.parts):
            raise ValueError(
                f"{path!r} is not a path a conflict version can be written at: it is relative to "
                "the target root, is not empty, and may not climb out of it"
            )
        return self._workspace.joinpath(directory, *pure.parts)


__all__ = [
    "LIBRARY_DIRECTORY",
    "TARGET_DIRECTORY",
    "SubprocessConflictEditor",
    "run_editor",
]
