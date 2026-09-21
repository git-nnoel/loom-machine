"""Contract C-6 — the `ErrorCode`-to-exit-status table.

Ruling R24 required a table rather than a chain of `if`s precisely so that it could be *walked*.
This is the walk: a code added to the taxonomy with no exit status fails here, at the moment it is
added, rather than in whichever command first happens to raise it.
"""

from __future__ import annotations

from harness_library.cli.exit_codes import (
    BACKUP_FAILED,
    BAD_REQUEST,
    EXIT_STATUS,
    INCOMPLETE,
    LIBRARY_UNUSABLE,
    LOCK_HELD,
    MANIFEST_UNREADABLE,
    MANIFEST_UNWRITABLE,
    NOT_FOUND,
    OK,
    TARGET_UNWRITABLE,
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
        ErrorCode.LIBRARY_YAML_INVALID,
        ErrorCode.NOT_A_LIBRARY,
    }


# -- Contract C-14, the install statuses (T-13) ---------------------------------------------------
#
# Every test above is unchanged. These are additions, over rows that did not exist when they were
# written; each of the five new codes takes a status of its own, so the three group assertions
# above keep exactly the sets they already asserted.


def test_the_install_statuses_are_the_numbers_c14_fixed() -> None:
    """The integers themselves, because a script branches on them.

    C-14 and rulings R57 and R59 fix these five; they are not this table's to choose. Asserted as
    literals rather than as "distinct and above 5", which would pass for any renumbering.
    """
    assert INCOMPLETE == 6
    assert TARGET_UNWRITABLE == 7
    assert MANIFEST_UNREADABLE == 8
    assert BACKUP_FAILED == 9
    assert LOCK_HELD == 10


def test_each_install_code_maps_to_its_own_status() -> None:
    """Unlike the read path, these five are **not** grouped. Five different actions — decide, fix
    the target, delete the manifest, fix the backup directory, wait — and a caller that cannot
    tell them apart cannot take any of them."""
    install = {
        ErrorCode.INCOMPLETE: INCOMPLETE,
        ErrorCode.TARGET_UNWRITABLE: TARGET_UNWRITABLE,
        ErrorCode.MANIFEST_UNREADABLE: MANIFEST_UNREADABLE,
        ErrorCode.BACKUP_FAILED: BACKUP_FAILED,
        ErrorCode.LOCK_HELD: LOCK_HELD,
    }

    assert {code: exit_status_for(code) for code in install} == install
    assert len(set(install.values())) == len(install)


def test_no_install_status_reuses_a_read_path_status() -> None:
    """A script that already branches on 3, 4 and 5 must not find `hl install` answering one of
    them with a different meaning."""
    read_path = {NOT_FOUND, BAD_REQUEST, LIBRARY_UNUSABLE}
    install = {INCOMPLETE, TARGET_UNWRITABLE, MANIFEST_UNREADABLE, BACKUP_FAILED, LOCK_HELD}

    assert read_path.isdisjoint(install)


# -- Contract C-14's sixth install status (T-16, ruling R64) --------------------------------------
#
# Added, not altered: every test above keeps the sets and the numbers it already asserted, and
# `MANIFEST_UNWRITABLE` takes a status of its own like the five before it.


def test_the_manifest_unwritable_status_is_the_number_r64_fixed() -> None:
    """The integer itself, because a script branches on it. R64 fixes 11; the table does not
    choose it."""
    assert MANIFEST_UNWRITABLE == 11
    assert exit_status_for(ErrorCode.MANIFEST_UNWRITABLE) == MANIFEST_UNWRITABLE


def test_an_unwritable_manifest_is_told_apart_from_an_unreadable_one_and_from_the_target() -> None:
    """Three directories, three remedies, three numbers.

    `MANIFEST_UNREADABLE` says the record is damaged — delete it and reinstall.
    `MANIFEST_UNWRITABLE` says it could not be written and, under ruling R63, that **nothing
    happened** — fix the state directory. `TARGET_UNWRITABLE` says the install target will not
    take a write. A user sent to the wrong one of the three looks in the wrong place.
    """
    statuses = {MANIFEST_UNREADABLE, MANIFEST_UNWRITABLE, TARGET_UNWRITABLE}

    assert len(statuses) == 3


def test_no_install_status_collides_with_another() -> None:
    """The six together, as one set. A sixth code reusing a fifth's number would make a script
    that already branches on 6..10 read this one as something it is not."""
    install = {
        ErrorCode.INCOMPLETE,
        ErrorCode.TARGET_UNWRITABLE,
        ErrorCode.MANIFEST_UNREADABLE,
        ErrorCode.BACKUP_FAILED,
        ErrorCode.LOCK_HELD,
        ErrorCode.MANIFEST_UNWRITABLE,
    }

    assert len({exit_status_for(code) for code in install}) == len(install)
