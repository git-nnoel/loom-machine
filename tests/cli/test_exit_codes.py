"""Contract C-6 — the `ErrorCode`-to-exit-status table.

Ruling R24 required a table rather than a chain of `if`s precisely so that it could be *walked*.
This is the walk: a code added to the taxonomy with no exit status fails here, at the moment it is
added, rather than in whichever command first happens to raise it.
"""

from __future__ import annotations

from harness_library.cli.exit_codes import (
    BAD_REQUEST,
    EXIT_STATUS,
    LIBRARY_UNUSABLE,
    NOT_FOUND,
    OK,
    USAGE,
    VALIDATION_FAILED,
    exit_status_for,
)
from harness_library.domain.errors import ErrorCode


def test_every_error_code_has_an_exit_status() -> None:
    """Total over the enum. The same guard `domain/registry.py` uses over `ArtifactType`."""
    missing = [code.value for code in ErrorCode if code not in EXIT_STATUS]

    assert missing == [], (
        f"these error codes have no exit status: {missing}. Contract C-6 maps every code; a code "
        "that reaches the CLI without one cannot be branched on by a script."
    )


def test_the_table_maps_only_codes_that_exist() -> None:
    """The other direction: a renamed code must not leave a stale row behind."""
    assert set(EXIT_STATUS) <= set(ErrorCode)


def test_every_status_is_reachable_through_the_lookup() -> None:
    """`exit_status_for` is the accessor every caller uses; it must agree with the table."""
    assert all(exit_status_for(code) == EXIT_STATUS[code] for code in ErrorCode)


def test_success_and_a_failed_validation_are_distinguishable() -> None:
    """Feature F-4 depends on this being two numbers and not one."""
    assert OK != VALIDATION_FAILED


def test_no_error_code_collides_with_success_usage_or_a_failed_validation() -> None:
    """A taxonomy status that reused `0`, `1` or `2` would make a script unable to tell "the
    library is invalid" from "the artifact was not found", which is the distinction F-4 rests on."""
    reserved = {OK, VALIDATION_FAILED, USAGE}

    assert reserved.isdisjoint(set(EXIT_STATUS.values()))


def test_the_statuses_group_by_what_the_user_must_do() -> None:
    """The grouping is the contract's shape, and initiative 03 maps the same codes to HTTP.

    Asserted as whole sets rather than per code: a code moving from one group to the other is a
    contract change, and it should fail here even if the number it moved to already existed."""
    assert {code for code, status in EXIT_STATUS.items() if status == NOT_FOUND} == {
        ErrorCode.ARTIFACT_NOT_FOUND,
        ErrorCode.FILE_NOT_FOUND,
        ErrorCode.COLLECTION_NOT_FOUND,
    }
    assert {code for code, status in EXIT_STATUS.items() if status == BAD_REQUEST} == {
        ErrorCode.INVALID_FILE_PATH,
        ErrorCode.FILE_NOT_TEXT,
        ErrorCode.INVALID_QUERY,
    }
    assert {code for code, status in EXIT_STATUS.items() if status == LIBRARY_UNUSABLE} == {
        ErrorCode.LIBRARY_YAML_INVALID
    }
