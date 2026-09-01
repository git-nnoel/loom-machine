"""Contract C-6's other half — `ErrorCode` to process exit status.

**A table, not a chain of `if`s.** Ruling R24 says so in advance, and the reason is that initiative
03 maps the *same* codes to HTTP statuses: two mappings written as branching logic drift the first
time a code is added to one and not the other, and nothing fails. A table can be walked, so
`tests/cli/test_exit_codes.py` walks `ErrorCode` and fails on a member with no status — the same
guard `domain/registry.py` uses over `ArtifactType`.

**The statuses are grouped by what a user must do about them**, not by which code raised. A wrong
id and a wrong collection key are one problem — "that thing is not here, go and list" — and a
traversal attempt and an empty query are another — "that request is not one I will answer". Giving
each code its own number would encode the taxonomy twice and tell a shell script nothing extra.
"""

from __future__ import annotations

from harness_library.domain.errors import ErrorCode

OK = 0
"""The command did what was asked."""

VALIDATION_FAILED = 1
"""`hl validate` found at least one ERROR finding.

Feature F-4, ruling R22. This is the status a pre-commit hook or a CI job branches on, and it is
deliberately *not* in the table below: it is not an error at all. The command succeeded — it looked
at the library and the answer was "invalid". A WARNING-only library exits `OK`, because a warning
never blocks.
"""

USAGE = 2
"""A bad flag or a missing argument. Click's own convention; not ours to renumber."""

NOT_FOUND = 3
"""The thing asked for is not in this library."""

BAD_REQUEST = 4
"""The request itself is not answerable, whatever the library contains."""

LIBRARY_UNUSABLE = 5
"""The library could not be read at all.

Covers both `LIBRARY_YAML_INVALID` and `NOT_A_LIBRARY`. From a caller's side these are one
situation — nothing can be answered until the library is fixed — and they differ only in whether
the metadata document is broken or the directory was never a library, which the stderr diagnosis
already says.
"""

EXIT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.LIBRARY_YAML_INVALID: LIBRARY_UNUSABLE,
    ErrorCode.ARTIFACT_NOT_FOUND: NOT_FOUND,
    ErrorCode.FILE_NOT_FOUND: NOT_FOUND,
    ErrorCode.COLLECTION_NOT_FOUND: NOT_FOUND,
    ErrorCode.INVALID_FILE_PATH: BAD_REQUEST,
    ErrorCode.FILE_NOT_TEXT: BAD_REQUEST,
    ErrorCode.INVALID_QUERY: BAD_REQUEST,
    ErrorCode.NOT_A_LIBRARY: LIBRARY_UNUSABLE,
}
"""One entry per `ErrorCode`. A member without one fails `tests/cli/test_exit_codes.py`."""


def exit_status_for(code: ErrorCode) -> int:
    """The process exit status for one error code. Total over `ErrorCode`, guarded by a test."""
    return EXIT_STATUS[code]


__all__ = [
    "BAD_REQUEST",
    "EXIT_STATUS",
    "LIBRARY_UNUSABLE",
    "NOT_FOUND",
    "OK",
    "USAGE",
    "VALIDATION_FAILED",
    "exit_status_for",
]
