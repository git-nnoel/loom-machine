"""Ruling R2 — the one object that reads the environment, and the only one.

Charter §13 says a single settings object is the sole reader of the environment and that no other
module calls `os.environ`. That is not tidiness: an environment variable read at the point of use
is a dependency that no signature declares, cannot be overridden in a test without mutating the
process, and is invisible to anyone reading the call site. Reading it once, here, turns it into an
ordinary value that the composition root passes down.

`pydantic-settings` rather than `os.environ.get` because the value is a path that may be absent,
and validating it at the boundary is what keeps `None`-versus-empty-string out of every caller.

**`$EDITOR` is read here too — ruling R104** — although it carries no `HL_` prefix and belongs to
the user's shell rather than to this tool. Charter §13 says *every* environment read lives here,
with no exception for a variable somebody else named, and the alternative is the one the charter
exists to prevent: `infrastructure/editor.py` reaching for `os.environ` in a class whose whole
purpose is to be a seam a test replaces. It is **split into an argument vector here as well**,
because a real `$EDITOR` is routinely `code --wait` or `vim -d`, and splitting it further down
would put a second, worse shell inside the one class in this project that spawns a process.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness_library.domain.errors import EditorFailedError


class Settings(BaseSettings):
    """Configuration drawn from the environment. The `HL_` prefix is charter §13's namespace.

    Attributes:
        library: `$HL_LIBRARY`, or `None` when it is unset. **Never defaulted to the current
            directory here.** The default belongs to the precedence chain in
            `cli.composition.resolve_library_root`, which has to distinguish "the environment said
            nothing" from "the environment said this" in order to apply `--library` above it. A
            default baked in at this level would make the environment indistinguishable from its
            own absence and quietly collapse two of the three steps of C-8.
        editor: `$EDITOR`, or `None` when it is unset. **Deliberately outside the `HL_`
            namespace**, and the `validation_alias` is what takes it outside: this is the
            variable every editor-launching program on the machine already reads, and an
            `HL_EDITOR` nobody sets would mean `hl install --resolve edit` opening a different
            editor from `git commit`. Raw text here and an argument vector from
            `editor_command` — the split is a decision and belongs beside the read, not in three
            callers.
    """

    model_config = SettingsConfigDict(env_prefix="HL_", extra="ignore")

    library: Path | None = None
    editor: str | None = Field(default=None, validation_alias="EDITOR")


def editor_command(settings: Settings | None = None) -> tuple[str, ...]:
    """`$EDITOR` as an argument vector. Ruling R104.

    Args:
        settings: the environment reader (ruling R2). Constructed here when omitted, and injected
            by a test so that proving the split never requires mutating `os.environ` in a process
            other tests share.

    Returns:
        The command and its arguments, already split — `("code", "--wait")`. Never a string:
        `SubprocessConflictEditor` appends the materialised files to it and runs it without a
        shell, so a vector is the only shape that cannot turn a path with a space in it into two
        arguments.

    Raises:
        EditorFailedError: `$EDITOR` is unset, blank, or not something `shlex` can split — an
            unbalanced quote. All three mean the same thing to a user and carry the same remedy,
            which is why one code covers them (R102). **Nothing has happened** when this fires:
            it is raised before any version is materialised and before any process is started.
    """
    resolved = settings if settings is not None else Settings()
    raw = (resolved.editor or "").strip()
    if not raw:
        raise EditorFailedError(None, "$EDITOR is unset or blank, so there is nothing to run")
    try:
        argv = shlex.split(raw)
    except ValueError as error:
        raise EditorFailedError(raw, f"it cannot be read as a command: {error}") from error
    if not argv:  # pragma: no cover - `shlex` returns at least one word for non-blank input
        raise EditorFailedError(raw, "it splits into no command at all")
    return tuple(argv)


__all__ = ["Settings", "editor_command"]
