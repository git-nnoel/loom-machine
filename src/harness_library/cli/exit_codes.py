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

INCOMPLETE = 6
"""Install ran and some artifact was not applied. Contract C-14, ruling R57.

**Not a failure.** Everything safe was written, nothing was destroyed, and the plan says per entry
what is left and why. The user must decide something — resolve a conflict, or deal with a V11
symlinked root — and a script must be able to tell that from "it broke", which is the whole reason
this initiative's statuses do not share one generic failure number.

Named for the outcome rather than for either cause (R57). Two causes reach it and a caller acts the
same way on both: read the plan.
"""

TARGET_UNWRITABLE = 7
"""The install target cannot be written to. Contract C-14.

Deliberately not folded into `LIBRARY_UNUSABLE`: that one says the *source* is unreadable, this one
says the *destination* is unwritable, and a user with a typo in `--target` needs to be sent to the
right one of the two directories.
"""

MANIFEST_UNREADABLE = 8
"""The record of what was installed into this target is damaged. Contract C-14, ruling R59.

Its own status because a caller's remedy is specific and safe: the manifest lives outside both the
library and the target, so it can be deleted and rebuilt by a reinstall without touching a file the
user owns. No other status has that remedy. An **absent** manifest never reaches here — it is not
an error.
"""

BACKUP_FAILED = 9
"""The pre-install backup could not be taken, so nothing was written. Contract C-14, ruling R59.

Distinct from `TARGET_UNWRITABLE` even though both are a directory that will not take a write: this
one means the target is untouched *because the tool refused*, which is the guarantee F-9 rests on.
"""

LOCK_HELD = 10
"""Another writer holds this target's lock; this run wrote nothing. Contract C-14, ruling R59.

The only status whose remedy is "wait and run it again", which is why it is not folded into any of
the others. Charter §12, ruling R50.
"""

MANIFEST_UNWRITABLE = 11
"""The record of what this install was about to do could not be written. Contract C-14, R64.

**Nothing happened.** Ruling R63 writes the manifest after the backup and before the first file,
so this status is the one in the table that carries a guarantee rather than a question: the target
is exactly as it was. Its own number rather than `TARGET_UNWRITABLE`'s because the two send a user
to two different directories, and the whole point of these statuses is telling them which.
"""

TARGET_UNREADABLE = 12
"""A path the install target holds could not be read. Contract C-14, ruling R81.

**Nothing emits this yet**, and the row exists anyway: C-14 fixed the integer, no `ErrorCode`
carried it, and invariant I-8 makes this table total over that enum — so a code named in a
document and absent from the contract is the shape ruling R26 recorded, and a code added later
without its status turns the gate red in a task that looks nothing like the cause. The code enters
the contract first; the raise site follows. See `ErrorCode.TARGET_UNREADABLE`.

Its own number rather than `TARGET_UNWRITABLE`'s even though both name the target directory: a
target that cannot be *described* is a plan this tool refuses to trust, and a target that will not
take a write is a plan it never got to run. The remedies differ — a permission on one path against
a permission on the directory — and telling a user which is the whole point of these statuses.
"""

RECORD_STALE = 13
"""The work was done and the record of it could not be written. Contract C-14, ruling R90.

**The mirror of `MANIFEST_UNWRITABLE`, and the reason that one can promise anything.** Under R63
an apply writes its manifest before the first file, so 11 means *nothing happened*. Charter §13b
sends every run that makes files **disappear** the other way — rollback, uninstall, prune and
`clean --foreign` record last — so the same failure there means the target has already changed.
Answering it with 11 would tell a script the opposite of the truth about a target that had just
been emptied, and a script that believed it would retry, report success, or do nothing.

Its own number rather than `MANIFEST_UNWRITABLE`'s because these two send a user to the same
directory with two different situations, and the whole point of these statuses is telling them
apart. **Not a failure of the work** — nothing is lost and nothing is unreachable; the next
`hl diff` over-reports until the record catches up, and the remedy is to fix the state directory
and run the same command again, which is safe because all four are idempotent.
"""

EDITOR_FAILED = 14
"""`$EDITOR` is not configured, or could not be run. Contract C-14, ruling R102.

**The only status in this table that is about the user's machine** rather than about their
library, their target or this tool's record — which is why it is not folded into any of the
thirteen above it. Every other remedy points at a directory; this one points at a shell variable.

`compare_versions` shows two versions of a refused path and decides nothing (R54), so a failure
to show them changes no state at all: the path is refused exactly as it was, and running the
command again after setting `$EDITOR` is the whole recovery. T-21 let the editor's `OSError` out
rather than mislabel it as one of the codes that already existed, and said so in two docstrings;
without a status a mistyped environment variable reaches the user as a traceback.
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
    # The install path. One status each, unlike the read path's groups: these nine call for
    # nine different actions — decide, fix the target, delete the manifest, fix the backup
    # directory, wait, fix the state directory, fix the unreadable path, run the command again,
    # set $EDITOR — so grouping them would throw away the only thing a script wants from them.
    # The eighth is T-19's (R90) and the ninth is T-22's (R102); every one of the nine now has
    # an emitter.
    ErrorCode.INCOMPLETE: INCOMPLETE,
    ErrorCode.TARGET_UNWRITABLE: TARGET_UNWRITABLE,
    ErrorCode.MANIFEST_UNREADABLE: MANIFEST_UNREADABLE,
    ErrorCode.BACKUP_FAILED: BACKUP_FAILED,
    ErrorCode.LOCK_HELD: LOCK_HELD,
    ErrorCode.MANIFEST_UNWRITABLE: MANIFEST_UNWRITABLE,
    ErrorCode.TARGET_UNREADABLE: TARGET_UNREADABLE,
    ErrorCode.RECORD_STALE: RECORD_STALE,
    ErrorCode.EDITOR_FAILED: EDITOR_FAILED,
}
"""One entry per `ErrorCode`. A member without one fails `tests/cli/test_exit_codes.py`."""


def exit_status_for(code: ErrorCode) -> int:
    """The process exit status for one error code. Total over `ErrorCode`, guarded by a test."""
    return EXIT_STATUS[code]


__all__ = [
    "BACKUP_FAILED",
    "BAD_REQUEST",
    "EDITOR_FAILED",
    "EXIT_STATUS",
    "INCOMPLETE",
    "LIBRARY_UNUSABLE",
    "LOCK_HELD",
    "MANIFEST_UNREADABLE",
    "MANIFEST_UNWRITABLE",
    "NOT_FOUND",
    "OK",
    "RECORD_STALE",
    "TARGET_UNREADABLE",
    "TARGET_UNWRITABLE",
    "USAGE",
    "VALIDATION_FAILED",
    "exit_status_for",
]
