"""The project's error taxonomy — contract C-6, charter §9.

One base exception, and a **closed set of stable string codes** that callers branch on. The
`message` is a human sentence and is not contract; it may be reworded without notice. The `code` is
contract: it maps to a CLI exit code now and to an HTTP status in initiative 03, so **a code is
added to `ErrorCode` before it is emitted**, never invented at a raise site.

`code` is a class attribute rather than a constructor argument. Two exceptions of the same class
cannot then disagree about their code, and adding a new code means adding a new class — which is
the moment the taxonomy is meant to be reviewed.

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
