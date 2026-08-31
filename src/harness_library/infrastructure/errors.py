"""The project's error taxonomy — contract C-6, charter §9.

One base exception, and a **closed set of stable string codes** that callers branch on. The
`message` is a human sentence and is not contract; it may be reworded without notice. The `code` is
contract: it maps to a CLI exit code now and to an HTTP status in initiative 03, so **a code is
added to `ErrorCode` before it is emitted**, never invented at a raise site.

`code` is a class attribute rather than a constructor argument. Two exceptions of the same class
cannot then disagree about their code, and adding a new code means adding a new class — which is
the moment the taxonomy is meant to be reviewed.

**Placement, flagged deliberately.** This taxonomy is project-wide: `cli/` maps codes to exit codes
and `api/` will map them to HTTP statuses. Its natural home is `domain/`, which every layer may
import; it lives here only because T-4 was scoped to `infrastructure/` while T-3 held `domain/`.
`application/` may not import `infrastructure/` (they are independent siblings under the
layered-architecture contract), so an application-layer error **cannot** inherit from this base
while it sits here. Moving this module to `domain/errors.py` is a one-import-per-file change and
should happen before the second code is added.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class ErrorCode(StrEnum):
    """The closed set of error codes. Charter §9's contract, as code.

    Closed and a `StrEnum` rather than a bare `str`: a rename then fails at every emitter instead
    of passing silently and producing a value nothing handles.
    """

    LIBRARY_YAML_INVALID = "LIBRARY_YAML_INVALID"
    """`library.yaml` exists but cannot be used — unparseable YAML, or a value of the wrong shape.

    One code for both, on purpose. A colon in the wrong place and `tags: process` where a list
    belongs are the same fact to every caller — "this file is not usable, here is the line" — and
    both map to one CLI exit code and one HTTP status. Splitting them would put a distinction in
    the contract that no caller acts on.

    An **absent** `library.yaml` is not this error, and is not an error at all: a library that
    declares no metadata is a valid library with no tags and no collections.
    """


class HarnessLibraryError(Exception):
    """Base of every error this project raises deliberately at a user-facing boundary.

    Not raised directly. Subclasses set `code`; adapters catch this type and branch on `code`.
    """

    code: ErrorCode


class LibraryYamlError(HarnessLibraryError):
    """`library.yaml` cannot be read as metadata.

    Attributes:
        code: always `ErrorCode.LIBRARY_YAML_INVALID`.
        path: the `library.yaml` that failed. Absolute; always present.
        line: 1-based line of the offending construct, or `None` when the failure has no position
            at all (an unreadable or non-UTF-8 file). Present-and-null, never omitted. Every parse
            failure and every shape failure sets it.
        column: 1-based column, with the same nullability rule as `line`.
        reason: the human sentence, without the `path:line:` prefix that `str(error)` carries. Not
            contract.
    """

    code = ErrorCode.LIBRARY_YAML_INVALID

    def __init__(
        self,
        reason: str,
        *,
        path: Path,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.path = path
        self.line = line
        self.column = column
        self.reason = reason
        super().__init__(_render(reason, path=path, line=line, column=column))


def _render(reason: str, *, path: Path, line: int | None, column: int | None) -> str:
    """`path:line:column: reason`, dropping the parts that are unknown.

    The location goes in the message as well as in the fields because the CLI prints `str(error)`,
    and a diagnosis a user cannot locate is half a diagnosis.
    """
    location = str(path)
    if line is not None:
        location = f"{location}:{line}"
        if column is not None:
            location = f"{location}:{column}"
    return f"{location}: {reason}"
