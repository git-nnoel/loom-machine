"""Ruling R2 — the one object that reads the environment, and the only one.

Charter §13 says a single settings object is the sole reader of the environment and that no other
module calls `os.environ`. That is not tidiness: an environment variable read at the point of use
is a dependency that no signature declares, cannot be overridden in a test without mutating the
process, and is invisible to anyone reading the call site. Reading it once, here, turns it into an
ordinary value that the composition root passes down.

`pydantic-settings` rather than `os.environ.get` because the value is a path that may be absent,
and validating it at the boundary is what keeps `None`-versus-empty-string out of every caller.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration drawn from the environment. The `HL_` prefix is charter §13's namespace.

    Attributes:
        library: `$HL_LIBRARY`, or `None` when it is unset. **Never defaulted to the current
            directory here.** The default belongs to the precedence chain in
            `cli.composition.resolve_library_root`, which has to distinguish "the environment said
            nothing" from "the environment said this" in order to apply `--library` above it. A
            default baked in at this level would make the environment indistinguishable from its
            own absence and quietly collapse two of the three steps of C-8.
    """

    model_config = SettingsConfigDict(env_prefix="HL_", extra="ignore")

    library: Path | None = None


__all__ = ["Settings"]
