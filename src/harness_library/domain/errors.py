"""The project's error taxonomy — contract C-6, charter §9.

One base exception, and a **closed set of stable string codes** that callers branch on. The
`message` is a human sentence and is not contract; it may be reworded without notice. The `code` is
contract: it maps to a CLI exit code now and to an HTTP status in initiative 03, so **a code is
added to `ErrorCode` before it is emitted**, never invented at a raise site.

`code` is a class attribute rather than a constructor argument. Two exceptions of the same class
cannot then disagree about their code, and adding a new code means adding a new class — which is
the moment the taxonomy is meant to be reviewed.

**The implication runs one way, and T-18 is where that first mattered.** A code needs a class;
a class does not need a code of its own. `BACKUP_FAILED` and `TARGET_UNWRITABLE` each carry two
classes, because what a class fixes is *the fields a raise site carries* and rollback's two
failures name a backup where apply's named a path. Two remedies would have been two codes; these
are one remedy each — go and look at where backups live, go and look at the target — reached from
two directions.

**Two codes currently have no class, deliberately.** `TARGET_UNWRITABLE`, `BACKUP_FAILED`,
`INCOMPLETE` and `LOCK_HELD` entered the enum in T-13 together with `MANIFEST_UNREADABLE`, because
invariant I-8 makes `cli/exit_codes.py` total over `ErrorCode` and a code added later without its
exit row turns the gate red in a task that looks nothing like the cause (ruling R26's recorded
failure). What the *contract* fixes is the code and its status; what a class fixes is the fields a
raise site carries — what a failed backup names, what a held lock names — and those belong to the
tasks that raise them. T-16 brought two of the four their classes, `BACKUP_FAILED` and
`TARGET_UNWRITABLE`, and T-17 brought `LOCK_HELD` its own, each in the task that raises it. The
two still without one are `INCOMPLETE`, which is argued below, and **`TARGET_UNREADABLE`**, which
T-17 added to the enum under ruling R81 because C-14 named the integer and no enum carried it:
**nothing emits it yet.** `infrastructure/target.py`'s scan propagates a bare `OSError` for a path
it cannot read, and giving that failure this code is the work of whichever task decides what a
half-readable target does to a plan. So the sentence above still holds in the direction that
matters: **no code is invented at a raise site.** A code may arrive before its class; a class may
never arrive before its code.

**`INCOMPLETE` may never get a class, and that is not an oversight.** It is not a failure — the
run did everything it safely could — so it is carried by `ApplyResult` and turned into an exit
status by the CLI, not raised. It is in the enum because C-14 maps it to a status like the others.

**Placement.** This taxonomy is project-wide: `cli/` maps codes to exit codes and `api/` will map
them to HTTP statuses. It lives in `domain/` because that is the only layer every other layer may
import. `application/` and `infrastructure/` are independent siblings under the
layered-architecture contract, so a base exception in either one is unreachable from the other, and
an application-layer error could not inherit it. T-4 raised this against itself; T-4b moved it here
under ruling R17, deliberately before a second `ErrorCode` existed.

**`path` is a `str`, not a `pathlib.Path`, and that is load-bearing.** `domain/` performs no I/O and
holds no filesystem library — `tests/domain/test_purity.py` enforces it beyond what `import-linter`
can see. The field is the user-facing *location of the fault*, which is all any consumer reads it
as; `_render` reduced it to text regardless. Narrowing the type was the only one of the three
available repairs that weakened neither the guard nor the field: importing `Path` under
`TYPE_CHECKING` would have routed around the guard, and removing `pathlib` from its forbidden set
would have dismantled it.
"""

from __future__ import annotations

from enum import StrEnum


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

    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    """The library holds no artifact with the requested `<type>/<name>` id.

    Added by T-6 under ruling R24. The repository answers an unknown id with `None` from `get()`
    and a bare `KeyError` from `read_bytes`; neither is a value an adapter can branch on, and
    charter §9 forbids an English string as the branchable value. This is the code T-7 maps to a
    CLI exit code and initiative 03 maps to HTTP 404.
    """

    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    """The artifact exists but contains no file at the requested path.

    Distinct from `ARTIFACT_NOT_FOUND` because the two are different user mistakes with different
    remedies — a wrong id is fixed by listing the library, a wrong path by showing the artifact —
    and initiative 03 will want to say which of the two the request got wrong.
    """

    INVALID_FILE_PATH = "INVALID_FILE_PATH"
    """The requested path is not addressable inside an artifact.

    An absolute path, an empty one, a `..` component, or a symlink that ruling R6 never follows.
    Separate from `FILE_NOT_FOUND` on purpose: "this file is not here" and "this is not a request I
    will answer" map to different HTTP statuses (404 against 400), and collapsing them would let a
    traversal attempt read as a typo.
    """

    FILE_NOT_TEXT = "FILE_NOT_TEXT"
    """The file cannot be decoded as UTF-8, so there is no text to return.

    Charter §7: binary is stored, hashed, exported and installed, never searched or diffed. The
    repository lets `UnicodeDecodeError` surface rather than papering over it with replacement
    characters; this is that fact given a code, so an adapter reports a binary file as binary
    instead of showing mojibake.
    """

    COLLECTION_NOT_FOUND = "COLLECTION_NOT_FOUND"
    """`library.yaml` declares no collection with the requested key.

    A collection key is a *declared* name, unlike a tag, so an unrecognised one is a mistake rather
    than a query that matches nothing. Charter §13's posture — fail loudly rather than silently
    return an empty list — applies to it for the same reason it applies to a non-library directory.
    """

    INVALID_QUERY = "INVALID_QUERY"
    """The search query is empty or blank.

    Not an empty result: an empty needle is a substring of every line, so answering it would return
    the result cap's worth of matches from an arbitrary corner of the library and report the search
    as truncated. That is a confidently wrong answer to a question the user did not ask.
    """

    NOT_A_LIBRARY = "NOT_A_LIBRARY"
    """The resolved library root is not a library, or is not a readable directory at all.

    Added by T-8 under **ruling R29**. Charter §13 requires resolution to fail loudly on a
    directory that is not a library — an empty listing is a fact about a library and must never
    also be how a missing one looks — and T-7 correctly refused to invent a code for it at the
    raise site, leaving `cli.composition.LibraryRootError` uncoded. This is that condition given a
    place in the contract: `cli/` maps it to the "library unusable" exit status and initiative 03
    maps it to an HTTP status without re-deriving one from an exception type it cannot see.

    Raised during **composition**, before any repository exists, which is what distinguishes it
    from `LIBRARY_YAML_INVALID`: that one is a library whose metadata document is broken, this one
    is not a library at all.
    """

    # -- The install path (initiative 02, the C-6 amendment) -------------------------------------
    #
    # All five entered the enum in T-13, the first task that emits one of them, with all five exit
    # rows in the same edit. Charter §9 requires a code to be in the contract before it is emitted,
    # and I-8 requires every member here to have a status in `cli/exit_codes.py`.

    INCOMPLETE = "INCOMPLETE"
    """Install ran, wrote everything it safely could, and some artifact was not applied.

    Named for the **outcome** rather than for either of its two causes (R57): a conflict awaiting
    `--resolve`, or a V11 symlinked root that was never scanned. A script branches on "you must
    decide something" and does not care which of the two it was — the plan already says, per entry
    and with a reason. This is not a failure: nothing broke, and the target is in a good state.

    `InstallPlan.is_complete` is the predicate, and `BLOCKING_VERDICTS` is its register.
    """

    TARGET_UNWRITABLE = "TARGET_UNWRITABLE"
    """The install target cannot be written to at all — missing, not a directory, or read-only.

    Distinct from `LIBRARY_UNUSABLE`'s pair, which is about the source. A user whose library is
    fine and whose target is a typo needs to be told which of the two directories to look at.
    """

    MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
    """The manifest for this target exists and cannot be used.

    Unparseable JSON, a value of the wrong type, an unknown key, a schema version this build does
    not read, or a file that is not UTF-8 text. One code for all of them, exactly as
    `LIBRARY_YAML_INVALID` covers both halves of its own document's failures: to every caller this
    is one fact — "what I recorded about this target is damaged, here is where" — and the location
    in the message says the rest.

    An **absent** manifest is not this error and is not an error at all: nothing has been installed
    into that target yet, and a first install must work. Returning an empty manifest for a damaged
    one would be far worse than either — the next install would see no record of anything, judge
    every one of the user's files `CREATE`, and overwrite them.
    """

    BACKUP_FAILED = "BACKUP_FAILED"
    """The pre-install backup could not be taken, so nothing was written.

    Its own code because the remedy is nothing like the others': the target is fine, the library is
    fine, and the place backups go is not. Install refuses rather than proceeding unprotected
    (F-9) — a write with no way back is the failure mode this initiative exists to remove.
    """

    LOCK_HELD = "LOCK_HELD"
    """Another writer holds this target's advisory lock, so this one did not write (R50).

    Charter §12: a single-writer lock, an `O_EXCL` sentinel beside the manifest, stale-broken by
    pid check. Its own code because "wait and retry" is a remedy no other code shares.
    """

    MANIFEST_UNWRITABLE = "MANIFEST_UNWRITABLE"
    """The record of what an install is about to do could not be written, so it did not run.

    Contract C-14 and **ruling R64**, which also fixes its exit status at 11. T-13 flagged the gap
    the moment it appeared: the C-6 amendment gave `MANIFEST_UNREADABLE` for a manifest that
    cannot be *read* and nothing at all for one that cannot be *written*, and `write_manifest` let
    a bare `OSError` surface rather than borrow a code whose name says something else.

    **Under ruling R63 this always means nothing happened.** The manifest is written after the
    backup and before the first file, so a failure here aborts with the target untouched. That
    ordering is what lets this code carry a guarantee instead of a question: were the manifest
    written last, the same failure would leave a modified target with no record of what was put
    there, every installed path reading `FOREIGN` — untouchable by install, unremovable by
    uninstall, and recoverable by nothing this initiative ships.

    Deliberately **not** `TARGET_UNWRITABLE`: the target is fine. The user must look at their
    state directory, and a code naming the wrong directory sends them to the wrong place.
    """

    TARGET_UNREADABLE = "TARGET_UNREADABLE"
    """A path the install target holds could not be read, so the target is not fully known.

    Contract C-14 and **ruling R81**, which fixes its exit status at 12. **Nothing emits it yet**,
    and the module docstring says why that is deliberate rather than an omission: C-14 named the
    integer, no enum carried it, and I-8 makes `cli/exit_codes.py` total over this enum — so a
    code living in a document and not in the contract is the shape ruling R26 recorded and this
    entry closes. The fourth time this project has found it.

    The counterpart of `TARGET_UNWRITABLE`, and not the same fact. That one says the destination
    will not take a write, before anything is attempted. This one says the destination could not
    be *described*: `infrastructure/target.py`'s scan refuses to answer an unreadable path with
    "the target does not hold it", because a path missing from a scan is judged `CREATE` and
    written straight over on the next apply. Today the scan propagates a bare `OSError` for it and
    whichever task decides what a half-readable target does to a plan is the one that gives that
    failure this code and a class to carry the path.
    """

    RECORD_STALE = "RECORD_STALE"
    """The work was done and the record of it could not be written. **Ruling R90**, exit 13.

    The counterpart of `MANIFEST_UNWRITABLE`, and the reason that one can keep its guarantee.
    Under R63 an apply writes its manifest between the backup and the first file, so a failure
    there always means *nothing happened*. Charter §13b sends every run that makes files
    **disappear** the other way — rollback, uninstall, prune and `clean --foreign` all record
    last, because a record written first can disown a file that is still on disk. For those four
    a failed manifest write means the opposite: the target has already changed and only the
    record is behind.

    Its own code because `MANIFEST_UNWRITABLE`'s promise would be a lie here, and a status
    carrying the wrong guarantee is worse than no status at all — a script that read "nothing
    happened" off a target that had just been emptied would retry, report success, or do nothing,
    and every one of those is wrong. The remedy is its own too: nothing is broken and nothing is
    lost, but the next `hl diff` over-reports until the record catches up, so the answer is to
    fix the state directory and run the same command again. All four are idempotent, which is
    what makes that remedy safe.

    **Nothing is disowned**, which is the whole point of the ordering that produces this code.
    The record still claims the files that went, so they come back `CREATE` — a decision the user
    is asked about — rather than `FOREIGN`, which nothing in this initiative can reach.
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
        path: the `library.yaml` that failed, as text. Absolute; always present.
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
        path: str,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.path = path
        self.line = line
        self.column = column
        self.reason = reason
        super().__init__(_render(reason, path=path, line=line, column=column))


# -- Read-path errors (ruling R24) ---------------------------------------------------------------
#
# The repository raises plain `KeyError`, `FileNotFoundError`, `ValueError` and
# `UnicodeDecodeError` — deliberately, because `domain/errors.py` was out of bounds for the task
# that wrote it (T-5 decision 3). The application layer is where those become meaningful: it is the
# last layer above the filesystem and below every adapter, so translating there means T-7's exit
# codes and initiative 03's HTTP statuses read one taxonomy rather than each re-deriving it from a
# builtin. Every code below entered `ErrorCode` in the same edit that added its class.


class ArtifactNotFoundError(HarnessLibraryError):
    """No artifact in the library has this id.

    Attributes:
        code: always `ErrorCode.ARTIFACT_NOT_FOUND`.
        artifact_id: the id that resolved to nothing.
    """

    code = ErrorCode.ARTIFACT_NOT_FOUND

    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        super().__init__(f"no artifact {artifact_id!r} in this library")


class ArtifactFileNotFoundError(HarnessLibraryError):
    """The artifact exists; it contains no file at this path.

    Attributes:
        code: always `ErrorCode.FILE_NOT_FOUND`.
        artifact_id: the artifact that was asked.
        path: the path it does not contain, relative to the artifact root.
    """

    code = ErrorCode.FILE_NOT_FOUND

    def __init__(self, artifact_id: str, path: str) -> None:
        self.artifact_id = artifact_id
        self.path = path
        super().__init__(f"{artifact_id} contains no file at {path!r}")


class InvalidFilePathError(HarnessLibraryError):
    """The path is not addressable inside an artifact root.

    Attributes:
        code: always `ErrorCode.INVALID_FILE_PATH`.
        artifact_id: the artifact that was asked.
        path: the rejected path, as the caller wrote it.
        reason: the human sentence. Not contract.
    """

    code = ErrorCode.INVALID_FILE_PATH

    def __init__(self, artifact_id: str, path: str, reason: str) -> None:
        self.artifact_id = artifact_id
        self.path = path
        self.reason = reason
        super().__init__(f"{path!r} is not a path inside {artifact_id}: {reason}")


class FileNotTextError(HarnessLibraryError):
    """The file is not UTF-8 text, so it has no text to return or search.

    Attributes:
        code: always `ErrorCode.FILE_NOT_TEXT`.
        artifact_id: the artifact holding the file.
        path: the file, relative to the artifact root.
    """

    code = ErrorCode.FILE_NOT_TEXT

    def __init__(self, artifact_id: str, path: str) -> None:
        self.artifact_id = artifact_id
        self.path = path
        super().__init__(
            f"{artifact_id}/{path} is not UTF-8 text: binary content is stored, hashed and "
            "installed, never decoded (charter §7)"
        )


class CollectionNotFoundError(HarnessLibraryError):
    """`library.yaml` declares no collection with this key.

    Attributes:
        code: always `ErrorCode.COLLECTION_NOT_FOUND`.
        key: the key that resolved to nothing.
    """

    code = ErrorCode.COLLECTION_NOT_FOUND

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"this library declares no collection {key!r}")


class InvalidQueryError(HarnessLibraryError):
    """The search query is unusable.

    Attributes:
        code: always `ErrorCode.INVALID_QUERY`.
        reason: the human sentence. Not contract.
    """

    code = ErrorCode.INVALID_QUERY

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# -- The install path (initiative 02) ------------------------------------------------------------
#
# One class, for the one code T-13 emits. The other four codes above are in the contract ahead of
# their raise sites; see this module's docstring for why that is deliberate and not an oversight.


class ManifestError(HarnessLibraryError):
    """This target's manifest exists and cannot be used.

    The loud half of the reader in `infrastructure/manifest_store.py`. Absent is not this error —
    it is `None`, meaning nothing has been installed here yet.

    **Two kinds of location, because JSON offers two.** A file that does not parse has a line and
    a column, straight from the decoder, and renders as `path:line:column: reason`, the same shape
    `LibraryYamlError` renders. A file that parses into the wrong *shape* has neither: by the time
    a value is known to be a number where a string belongs, the parser has thrown its positions
    away. What that failure has instead is a **field path** — `artifacts[0].files[1].sha256` — which
    is the location a reader of the document actually needs, and it renders as
    `path: artifacts[0].files[1].sha256: reason`.

    Both are carried as fields as well as folded into the message, because the CLI prints
    `str(error)` and a diagnosis nobody can locate is half a diagnosis.

    Attributes:
        code: always `ErrorCode.MANIFEST_UNREADABLE`.
        path: the manifest file that failed, as text. Absolute; always present.
        location: the field path inside the document, or `None` when the failure is not about one
            field — a file that does not parse, or one that is not text at all.
        line: 1-based line of the offending construct, or `None` when the failure has no position.
            Present-and-null, never omitted.
        column: 1-based column, with the same nullability rule as `line`.
        reason: the human sentence, without the location prefix `str(error)` carries. Not contract.
    """

    code = ErrorCode.MANIFEST_UNREADABLE

    def __init__(
        self,
        reason: str,
        *,
        path: str,
        location: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.path = path
        self.location = location
        self.line = line
        self.column = column
        self.reason = reason
        located = reason if location is None else f"{location}: {reason}"
        super().__init__(_render(located, path=path, line=line, column=column))


# -- The write path (initiative 02, T-16) --------------------------------------------------------
#
# Three classes over three codes that have been in the contract since T-13 — two of them waiting
# for the task that raises them, and `MANIFEST_UNWRITABLE` arriving with its own row in
# `cli/exit_codes.py` in this same edit (C-14, R64). Each carries the location a user has to go
# and look at, because all three name a directory and they name three different ones.


class BackupFailedError(HarnessLibraryError):
    """The pre-install backup could not be taken, so nothing was written.

    The refusal F-9 rests on. Install does not proceed unprotected: a write with no way back is
    the failure mode this whole initiative exists to remove, and "the backup directory is broken"
    is a problem a user can fix in a minute, while an overwritten harness is not.

    Attributes:
        code: always `ErrorCode.BACKUP_FAILED`.
        reason: the human sentence, usually the underlying `OSError`'s. Not contract.
    """

    code = ErrorCode.BACKUP_FAILED

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            f"the backup could not be taken, so nothing was written: {reason}. Install refuses "
            "to write a target it cannot put back"
        )


class ManifestWriteError(HarnessLibraryError):
    """The manifest could not be written, so the install did not run.

    The loud half of ruling R63's ordering. Because the manifest is written *before* the first
    file, this error always means the target is untouched — see `ErrorCode.MANIFEST_UNWRITABLE`
    for why the other ordering would make the same failure unrecoverable.

    The sibling of `ManifestError`, which is the *read* failure and carries a location inside the
    document. This one has no location inside anything: the document was never written.

    Attributes:
        code: always `ErrorCode.MANIFEST_UNWRITABLE`.
        path: the manifest file that could not be written, as text, or `None` when the store does
            not have one to name. Present-and-null, never omitted.
        reason: the human sentence, usually the underlying `OSError`'s. Not contract.
    """

    code = ErrorCode.MANIFEST_UNWRITABLE

    def __init__(self, reason: str, *, path: str | None = None) -> None:
        self.path = path
        self.reason = reason
        located = reason if path is None else f"{path}: {reason}"
        super().__init__(f"the manifest could not be written, so nothing was installed: {located}")


class TargetUnwritableError(HarnessLibraryError):
    """A path in the install target could not be written or removed.

    Unlike its two siblings this one can be raised **part-way through**: the manifest is already
    on disk and the files before this one are already written. That is ruling R63's accepted
    cost — the manifest over-claims, and an over-claim is self-correcting, because every path it
    names that was never written comes back `LOCAL_EDIT` or `CONFLICT` on the next `hl diff`
    rather than disappearing into `FOREIGN`.

    Attributes:
        code: always `ErrorCode.TARGET_UNWRITABLE`.
        path: the target-relative path that failed.
        reason: the human sentence, usually the underlying `OSError`'s. Not contract.
    """

    code = ErrorCode.TARGET_UNWRITABLE

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path} could not be written into the target: {reason}")


# -- The single writer (initiative 02, T-17, ruling R50) -----------------------------------------


class LockHeldError(HarnessLibraryError):
    """Another writer holds this target's advisory lock, so this run wrote nothing.

    Charter §12 and **ruling R50**: one writer per target at a time, enforced by an `O_EXCL`
    sentinel beside the manifest and broken automatically when the process that left it is gone.
    Two applies interleaving against one target can write half of each plan's files and leave a
    manifest describing neither — a state no verdict in C-9 can express and nothing in this
    initiative can repair.

    **Nothing was written, and nothing was backed up.** The lock is taken before the first of
    apply's three steps, so this error carries the same guarantee `ManifestWriteError` does: the
    target is exactly as it was. Its own code because the remedy is one no other code shares —
    wait for the other run to finish and try again.

    Attributes:
        code: always `ErrorCode.LOCK_HELD`.
        path: the sentinel file that is held, as text. Where a user looks, and — if a machine
            really has gone down mid-install — what they would remove by hand.
        pid: the process the sentinel names, when it could be read, and `None` when the lock was
            lost to another run in the moment between breaking a stale sentinel and replacing it.
            A pid is a diagnosis and never a contract: it may already have exited by the time it
            is printed, and it is the holder's, not this process's.
    """

    code = ErrorCode.LOCK_HELD

    def __init__(self, path: str, *, pid: int | None = None) -> None:
        self.path = path
        self.pid = pid
        holder = "another process" if pid is None else f"process {pid}"
        super().__init__(
            f"{path} is held by {holder}: another install is writing to this target, so this run "
            "wrote nothing. Wait for it to finish and run again"
        )


# -- Undoing an install (initiative 02, T-18) ----------------------------------------------------
#
# Two classes and **no new code**. Charter §9 fixes the direction — a code may arrive before its
# class, never the reverse — and both codes below have been in the contract since T-13. What each
# class fixes is the fields its raise site carries, and rollback's two failures carry a backup id
# where apply's carried a path: `BackupStore.restore` puts a backup back as a unit, so the seam
# has no failing path to report and inventing one would be worse than naming the backup.


class BackupNotFoundError(HarnessLibraryError):
    """No backup has this id, so there is nothing to roll back to.

    The sibling of `BackupFailedError` over one code: that one is a backup that could not be
    *taken*, this one is a backup that cannot be *found*, and a user acts on both the same way —
    go and look at where backups live. A directory holding files and no `backup.json` is not a
    backup either (see `infrastructure/backup.py`): a half-written copy offered for restore would
    put half a target back, so it is not offered at all and arrives here.

    Attributes:
        code: always `ErrorCode.BACKUP_FAILED`.
        backup_id: the id that names nothing. Not contract; a diagnosis.
    """

    code = ErrorCode.BACKUP_FAILED

    def __init__(self, backup_id: str) -> None:
        self.backup_id = backup_id
        super().__init__(
            f"no backup {backup_id!r} is available for this target, so there is nothing to put "
            "back. A backup whose record is missing or unreadable is not offered rather than "
            "restored half way"
        )


class RestoreFailedError(HarnessLibraryError):
    """A backup could not be put back, so the target is part-way restored.

    The counterpart of `TargetUnwritableError` on the undo path, over the same code and for the
    same reason: the destination would not take a write. It carries the **backup id** rather than
    a path because C-13 restores as a unit — the seam is given an id and reports nothing about
    which of the paths it was on when the write failed.

    **Nothing is disowned.** The manifest is rewritten only after a restore that finished, so a
    target left half restored is still fully claimed by the record, and every path that did move
    comes back `LOCAL_EDIT`, `CONFLICT` or `CREATE` on the next `hl diff` rather than `FOREIGN`.
    The remedy is to fix the fault and roll back again: restoring one backup twice produces the
    same target, which is the property apply does not have and the reason apply needed a rollback
    while a rollback needs nothing beyond itself.

    Attributes:
        code: always `ErrorCode.TARGET_UNWRITABLE`.
        backup_id: the backup that was being put back.
        reason: the human sentence, usually the underlying `OSError`'s. Not contract.
    """

    code = ErrorCode.TARGET_UNWRITABLE

    def __init__(self, backup_id: str, reason: str) -> None:
        self.backup_id = backup_id
        self.reason = reason
        super().__init__(
            f"backup {backup_id} could not be put back: {reason}. The target may be part-way "
            "restored and is still fully described by its manifest; fix this and roll back again"
        )


# -- The record that could not keep up (initiative 02, T-19, ruling R90) -------------------------


class RecordStaleError(HarnessLibraryError):
    """The work was done and the manifest describing it could not be written.

    **The counterpart of `ManifestWriteError`, and its opposite in the one way that matters.**
    That one says *nothing happened*, which is true of an apply because R63 writes its manifest
    between the backup and the first file. Charter §13b sends every run that makes files
    disappear the other way round — rollback, uninstall, prune and `clean --foreign` record last,
    because a record written first can disown a file that is still on disk — so for those four
    the same syscall failing means the target has already changed and only the record is behind.

    Both codes existed in a document long before this class did: the two use cases that record
    last let a bare `OSError` out and said in their docstrings that a code carrying the wrong
    guarantee would be worse, and that giving this failure one of its own was a plan-level
    decision. Ruling **R90** is that decision.

    **Nothing is disowned**, which is the whole reason the ordering puts this failure here. The
    record still claims every file that went, so they come back `CREATE` on the next `hl diff` —
    something the user is asked about — and not `FOREIGN`, which nothing in this initiative can
    reach. Running the same command again is safe and is the remedy: all four are idempotent.

    Attributes:
        code: always `ErrorCode.RECORD_STALE`.
        operation: which run left the record behind — `"prune"`, `"clean"`, `"uninstall"`,
            `"rollback"`. A diagnosis and not contract; a caller branches on `code`, and a user
            reading stderr needs to know which command to run again.
        reason: the human sentence, usually the underlying `OSError`'s. Not contract.
    """

    code = ErrorCode.RECORD_STALE

    def __init__(self, operation: str, reason: str) -> None:
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"the {operation} finished and its record could not be written: {reason}. Nothing "
            "was lost and nothing is unreachable — the manifest still names the files that went, "
            f"so they report as missing until it catches up. Fix this and run the {operation} "
            "again"
        )


def _render(reason: str, *, path: str, line: int | None, column: int | None) -> str:
    """`path:line:column: reason`, dropping the parts that are unknown.

    The location goes in the message as well as in the fields because the CLI prints `str(error)`,
    and a diagnosis a user cannot locate is half a diagnosis.
    """
    location = path
    if line is not None:
        location = f"{location}:{line}"
        if column is not None:
            location = f"{location}:{column}"
    return f"{location}: {reason}"
