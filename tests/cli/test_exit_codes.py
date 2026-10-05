"""Contract C-6 — the `ErrorCode`-to-exit-status table.

Ruling R24 required a table rather than a chain of `if`s precisely so that it could be *walked*.
This is the walk: a code added to the taxonomy with no exit status fails here, at the moment it is
added, rather than in whichever command first happens to raise it.
"""

from __future__ import annotations

from loom.cli.exit_codes import (
    BACKUP_FAILED,
    BAD_REQUEST,
    EDITOR_FAILED,
    EXIT_STATUS,
    INCOMPLETE,
    LIBRARY_UNUSABLE,
    LOCK_HELD,
    MANIFEST_UNREADABLE,
    MANIFEST_UNWRITABLE,
    NOT_FOUND,
    OK,
    RECORD_STALE,
    STATE_UNWRITABLE,
    TARGET_UNREADABLE,
    TARGET_UNWRITABLE,
    USAGE,
    VALIDATION_FAILED,
    exit_status_for,
)
from loom.domain.errors import ErrorCode, HarnessLibraryError


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
    """A script that already branches on 3, 4 and 5 must not find `loom install` answering one of
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


# -- Contract C-14's seventh install status (T-17, ruling R81; emitted from T-21) -----------------
#
# Added in T-17, not altered since. `TARGET_UNREADABLE` arrived with its exit row and **no
# emitter**: C-14 named the integer, no `ErrorCode` carried it, and this table is required to be
# total over that enum, so the code existed before any raise site — the direction charter §9
# fixes, and the fourth time this project found a code living in a document instead of in the
# contract (R26).
#
# **T-21 is the task that needed it.** `resolve target` records what is on the target's disk, so
# it has to read it, and that read can fail. `TargetUnreadableError` is the class;
# `test_no_error_class_carries_target_unreadable_yet` said in its own docstring that it was meant
# to be deleted by whichever task added one, and this is that deletion. It is not weakened into
# something that still passes — the state it asserted is simply no longer true.


def test_the_target_unreadable_status_is_the_number_c14_fixed() -> None:
    """The integer itself, because a script branches on it. C-14 and R81 fix 12."""
    assert TARGET_UNREADABLE == 12
    assert exit_status_for(ErrorCode.TARGET_UNREADABLE) == TARGET_UNREADABLE


def test_a_target_that_cannot_be_read_is_told_apart_from_one_that_cannot_be_written() -> None:
    """Two facts about the same directory, two remedies, two numbers: a path whose permissions
    hide it from the scan, against a directory that will not take a write at all. A user sent to
    the wrong one of the two looks in the wrong place."""
    assert TARGET_UNREADABLE != TARGET_UNWRITABLE


def test_the_seven_install_statuses_are_seven_distinct_numbers() -> None:
    """The seven together, as one set. A seventh code reusing a sixth's number would make a
    script that already branches on 6..11 read this one as something it is not."""
    install = {
        ErrorCode.INCOMPLETE,
        ErrorCode.TARGET_UNWRITABLE,
        ErrorCode.MANIFEST_UNREADABLE,
        ErrorCode.BACKUP_FAILED,
        ErrorCode.LOCK_HELD,
        ErrorCode.MANIFEST_UNWRITABLE,
        ErrorCode.TARGET_UNREADABLE,
    }

    assert len({exit_status_for(code) for code in install}) == len(install) == 7


def test_target_unreadable_now_has_a_class_that_carries_it() -> None:
    """**`test_no_error_class_carries_target_unreadable_yet`, replaced rather than weakened.**

    That test asserted the state R81 deliberately left — a code in the contract with no emitter —
    and said in its own docstring that it was meant to be deleted by whichever task added one.
    T-21 is that task: `resolve target` records what is on the target's disk, so it reads the
    path, and a read that fails needs exactly the code C-14 already named. Replaced instead of
    dropped so the fact stays asserted in both directions — an edit that removed
    `TargetUnreadableError` would fail here rather than pass quietly.

    The positive control is the sibling assertion: the walk really does find a code with **no**
    class, so "carried" cannot mean "everything looks carried". It sees only the classes whose
    module is imported, which for `domain/errors.py` is all of them.
    """
    carried = {
        subclass.code
        for subclass in HarnessLibraryError.__subclasses__()
        if getattr(subclass, "code", None) is not None
    }

    assert ErrorCode.INCOMPLETE not in carried
    assert ErrorCode.TARGET_UNREADABLE in carried


# -- Contract C-14's eighth install status (T-19, ruling R90) -------------------------------------
#
# Added, not altered, as in T-13, T-16 and T-17. Unlike `TARGET_UNREADABLE`, this one arrives with
# its emitters: `prune_target` and `clean_foreign` raise it, and `rollback_install` and
# `uninstall_artifact` — which used to let a bare `OSError` out and said in their docstrings that
# giving it a code was a plan-level decision — now raise it too.


def test_the_record_stale_status_is_the_number_r90_fixed() -> None:
    """The integer itself, because a script branches on it. R90 fixes 13."""
    assert RECORD_STALE == 13
    assert exit_status_for(ErrorCode.RECORD_STALE) == RECORD_STALE


def test_a_stale_record_is_told_apart_from_a_manifest_that_was_never_written() -> None:
    """**The distinction the code exists for, and it is about a guarantee, not a directory.**

    `MANIFEST_UNWRITABLE` means *nothing happened*: R63 writes an apply's manifest before the
    first file, so the target is exactly as it was. `RECORD_STALE` means the opposite — charter
    §13b records last for every run that makes files disappear, so the work is done and only the
    record is behind. Answering the second with the first would tell a script the target was
    untouched when it had just been emptied.
    """
    assert RECORD_STALE != MANIFEST_UNWRITABLE
    assert exit_status_for(ErrorCode.MANIFEST_UNWRITABLE) != exit_status_for(ErrorCode.RECORD_STALE)


def test_the_eight_install_statuses_are_eight_distinct_numbers() -> None:
    """The eight together, as one set. An eighth code reusing a seventh's number would make a
    script that already branches on 6..12 read this one as something it is not."""
    install = {
        ErrorCode.INCOMPLETE,
        ErrorCode.TARGET_UNWRITABLE,
        ErrorCode.MANIFEST_UNREADABLE,
        ErrorCode.BACKUP_FAILED,
        ErrorCode.LOCK_HELD,
        ErrorCode.MANIFEST_UNWRITABLE,
        ErrorCode.TARGET_UNREADABLE,
        ErrorCode.RECORD_STALE,
    }

    assert len({exit_status_for(code) for code in install}) == len(install) == 8


def test_record_stale_has_a_class_that_carries_it() -> None:
    """Unlike `TARGET_UNREADABLE`, this code arrived **with** its raise sites — charter §9 allows
    a code before its class and forbids the reverse, and R90 named both in one ruling.

    The positive control is the sibling assertion: the walk really does find a code that has no
    class, so "carried" cannot mean "everything looks carried". It used to be
    `TARGET_UNREADABLE`, which T-21 gave a class; it is now `INCOMPLETE`, which `errors.py`
    argues may never get one — it is not a failure and is never raised, so it is the one member
    of the enum this control can rely on.
    """
    carried = {
        subclass.code
        for subclass in HarnessLibraryError.__subclasses__()
        if getattr(subclass, "code", None) is not None
    }

    assert ErrorCode.INCOMPLETE not in carried
    assert ErrorCode.RECORD_STALE in carried


# -- Contract C-14's ninth install status (T-22, ruling R102) ------------------------------------
#
# Added, not altered, as in T-13, T-16, T-17 and T-19. Every test above keeps the sets and the
# numbers it already asserted. Like `RECORD_STALE` and unlike `TARGET_UNREADABLE`, this one
# arrives **with** its emitters: `cli/settings.py` refuses an unset or unparseable `$EDITOR` and
# `cli/composition.py`'s `ReportingConflictEditor` gives the editor's own `OSError` this code.


def test_the_editor_failed_status_is_the_number_r102_fixed() -> None:
    """The integer itself, because a script branches on it. R102 fixes 14."""
    assert EDITOR_FAILED == 14
    assert exit_status_for(ErrorCode.EDITOR_FAILED) == EDITOR_FAILED


def test_a_failed_editor_is_told_apart_from_a_bad_request_and_from_a_usage_error() -> None:
    """**The distinction the code exists for, and it is about whose fault it is.**

    `BAD_REQUEST` says the request itself is not answerable whatever the library holds, and
    `USAGE` says this program rejected a flag. `EDITOR_FAILED` says the request was fine, the
    library was fine, the target was fine, and a program on the user's machine would not start.
    It is the only status in the table whose remedy is a shell variable rather than a directory.
    """
    assert EDITOR_FAILED not in {BAD_REQUEST, USAGE, OK}


def test_the_nine_install_statuses_are_nine_distinct_numbers() -> None:
    """The nine together, as one set. A ninth code reusing an eighth's number would make a
    script that already branches on 6..13 read this one as something it is not."""
    install = {
        ErrorCode.INCOMPLETE,
        ErrorCode.TARGET_UNWRITABLE,
        ErrorCode.MANIFEST_UNREADABLE,
        ErrorCode.BACKUP_FAILED,
        ErrorCode.LOCK_HELD,
        ErrorCode.MANIFEST_UNWRITABLE,
        ErrorCode.TARGET_UNREADABLE,
        ErrorCode.RECORD_STALE,
        ErrorCode.EDITOR_FAILED,
    }

    assert len({exit_status_for(code) for code in install}) == len(install) == 9


def test_editor_failed_has_a_class_that_carries_it() -> None:
    """Charter §9 allows a code before its class and forbids the reverse; R102 named both.

    The positive control is the sibling assertion, unchanged from the two tests above: the walk
    really does find a code with no class, so "carried" cannot mean "everything looks carried".
    `INCOMPLETE` is that code and `errors.py` argues it may never get one — it is not a failure
    and is never raised.
    """
    carried = {
        subclass.code
        for subclass in HarnessLibraryError.__subclasses__()
        if getattr(subclass, "code", None) is not None
    }

    assert ErrorCode.INCOMPLETE not in carried
    assert ErrorCode.EDITOR_FAILED in carried


# -- Contract C-14's tenth install status (T-24, ruling R111) ------------------------------------
#
# Added, not altered, as in T-13, T-16, T-17, T-19 and T-22. Every test above keeps the sets and
# the numbers it already asserted. Like `RECORD_STALE` and `EDITOR_FAILED`, this one arrives
# **with** its emitter: `FilesystemWriteLock._acquire` translates the `OSError` it had been
# letting out since T-17 — the one disk step of a write run that had no code, so an unwritable
# `~/.local/state` reached the user as a traceback and exit 1 on all four write commands.


def test_the_state_unwritable_status_is_the_number_r111_fixed() -> None:
    """The integer itself, because a script branches on it. R111 fixes 15."""
    assert STATE_UNWRITABLE == 15
    assert exit_status_for(ErrorCode.STATE_UNWRITABLE) == STATE_UNWRITABLE


def test_a_state_root_that_will_not_take_the_lock_is_told_apart_from_a_lock_that_is_held() -> None:
    """**The distinction the code exists for, and it is about the remedy.**

    Both are the lock refusing to hand over a target and both mean nothing was written. One is
    another run, and the answer is to wait; the other is the state directory itself, and waiting
    for a run that does not exist will not make it writable. A script told the wrong one of the
    two retries for ever.
    """
    assert STATE_UNWRITABLE != LOCK_HELD
    assert exit_status_for(ErrorCode.STATE_UNWRITABLE) != exit_status_for(ErrorCode.LOCK_HELD)


def test_a_state_root_that_will_not_take_the_lock_is_not_the_manifest_or_a_stale_record() -> None:
    """The other two codes that name the state directory, and neither is true here.

    `MANIFEST_UNWRITABLE` promises something specifically about the **manifest**, which R63's
    ordering is what makes meaningful — the sentinel is not the manifest, and answering with 11
    would claim a record had been attempted when nothing had. `RECORD_STALE` is the opposite
    again: work done, record behind. The lock precedes all of it.
    """
    assert STATE_UNWRITABLE not in {MANIFEST_UNWRITABLE, RECORD_STALE}


def test_the_ten_install_statuses_are_ten_distinct_numbers() -> None:
    """The ten together, as one set. A tenth code reusing a ninth's number would make a script
    that already branches on 6..14 read this one as something it is not."""
    install = {
        ErrorCode.INCOMPLETE,
        ErrorCode.TARGET_UNWRITABLE,
        ErrorCode.MANIFEST_UNREADABLE,
        ErrorCode.BACKUP_FAILED,
        ErrorCode.LOCK_HELD,
        ErrorCode.MANIFEST_UNWRITABLE,
        ErrorCode.TARGET_UNREADABLE,
        ErrorCode.RECORD_STALE,
        ErrorCode.EDITOR_FAILED,
        ErrorCode.STATE_UNWRITABLE,
    }

    assert len({exit_status_for(code) for code in install}) == len(install) == 10


def test_state_unwritable_has_a_class_that_carries_it() -> None:
    """Charter §9 allows a code before its class and forbids the reverse; R111 named both.

    The positive control is the sibling assertion, unchanged from the three tests above: the
    walk really does find a code with no class, so "carried" cannot mean "everything looks
    carried". `INCOMPLETE` is that code and `errors.py` argues it may never get one — it is not
    a failure and is never raised.
    """
    carried = {
        subclass.code
        for subclass in HarnessLibraryError.__subclasses__()
        if getattr(subclass, "code", None) is not None
    }

    assert ErrorCode.INCOMPLETE not in carried
    assert ErrorCode.STATE_UNWRITABLE in carried
