"""Tests for the `library.yaml` reader.

Charter §10: `infrastructure/` is tested against **real files under `tmp_path`**, never a fake
filesystem. What this layer is blind to is stated once, here: it can see nothing about whether the
ids in the file name artifacts that exist. That is rule V7, it belongs to the assembler, which sees
the whole library at once, and a reader test could not observe it because no tree is scanned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_library.domain.errors import (
    ErrorCode,
    HarnessLibraryError,
    LibraryYamlError,
)
from harness_library.domain.metadata import EMPTY_ARTIFACT_METADATA, LibraryMetadata
from harness_library.infrastructure.library_yaml import (
    LIBRARY_YAML_FILENAME,
    read_library_metadata,
)


def write_library_yaml(root: Path, text: str) -> Path:
    """Put a real `library.yaml` under `root` and return its path."""
    path = root / LIBRARY_YAML_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


# Behaviour 1 — an absent file is empty metadata, not an error.


def test_absent_file_is_empty_metadata(tmp_path: Path) -> None:
    """A library with no `library.yaml` is a valid library with no tags and no collections."""
    assert not (tmp_path / LIBRARY_YAML_FILENAME).exists()

    metadata = read_library_metadata(tmp_path)

    assert metadata == LibraryMetadata.empty()
    assert metadata.artifacts == {}
    assert metadata.collections == ()
    # Positive control for the two absence assertions above: the same reader, given a file, returns
    # a non-empty result — so "empty" here is the absent file speaking, not the reader failing to
    # load and not the assertions being incapable of failing.
    write_library_yaml(tmp_path, "artifacts:\n  skill/a:\n    tags: [x]\n")
    assert read_library_metadata(tmp_path).for_artifact("skill/a").tags == ("x",)


def test_an_existing_but_empty_file_is_empty_metadata(tmp_path: Path) -> None:
    """The file exists and declares nothing. The author said "nothing" and meant it."""
    write_library_yaml(tmp_path, "")

    assert read_library_metadata(tmp_path) == LibraryMetadata.empty()


def test_a_null_document_is_empty_metadata(tmp_path: Path) -> None:
    """`~` is a document that declares nothing, not a document that failed to parse."""
    write_library_yaml(tmp_path, "~\n")

    assert read_library_metadata(tmp_path) == LibraryMetadata.empty()


# Behaviour 2 — malformed YAML is a hard, loud failure carrying the line number.


def test_malformed_yaml_raises_with_the_line_number(tmp_path: Path) -> None:
    """The named assertion of the T-4 mutation check.

    Silently returning empty metadata here would make a typo look like "the user has no tags", so
    this asserts the raise, the code, and — the part that matters — the **specific line**, not
    merely that some exception happened.
    """
    path = write_library_yaml(
        tmp_path,
        "artifacts:\n"  # line 1
        "  skill/one:\n"  # line 2
        "    tags: [a, b]\n"  # line 3
        "   skill/two:\n",  # line 4 — dedented into nothing valid
    )

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 4
    assert caught.value.code is ErrorCode.LIBRARY_YAML_INVALID
    assert caught.value.path == str(path)
    assert "4" in str(caught.value)


def test_unclosed_flow_sequence_reports_its_line(tmp_path: Path) -> None:
    """A second syntax error, at a different line, so the number is read and not hard-coded."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n"  # line 1
        "  skill/one:\n"  # line 2
        "    tags: [a, b\n"  # line 3 — never closed
        "collections: {}\n",  # line 4 — where the parser gives up
    )

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 4


def test_a_malformed_file_is_not_confused_with_an_absent_one(tmp_path: Path) -> None:
    """The two conditions must not collapse into each other in either direction."""
    write_library_yaml(tmp_path, "artifacts: [\n")

    with pytest.raises(LibraryYamlError):
        read_library_metadata(tmp_path)

    (tmp_path / LIBRARY_YAML_FILENAME).unlink()
    assert read_library_metadata(tmp_path) == LibraryMetadata.empty()


def test_the_error_is_a_harness_library_error_with_a_stable_code() -> None:
    """Charter §9: adapters catch the base type and branch on `code`, never on the message."""
    error = LibraryYamlError("something", path="/library/library.yaml", line=7, column=3)

    assert isinstance(error, HarnessLibraryError)
    assert error.code is ErrorCode.LIBRARY_YAML_INVALID
    assert error.code.value == "LIBRARY_YAML_INVALID"
    assert str(error) == "/library/library.yaml:7:3: something"


# Behaviour 3 — a null-valued key is the empty form of its type.


def test_a_null_valued_key_is_the_empty_form_of_its_type(tmp_path: Path) -> None:
    """`tags:` with nothing after it is no tags — YAML's only idiom for "nothing here".

    The distinction from an absent key is preserved where it could bite: null becomes an *empty*
    tuple, never a one-element tuple holding `None`.
    """
    write_library_yaml(
        tmp_path,
        "artifacts:\n"
        "  skill/nulls:\n"
        "    tags:\n"
        "    superseded_by:\n"
        "collections:\n"
        "  empty-one:\n"
        "    title:\n"
        "    members:\n",
    )

    metadata = read_library_metadata(tmp_path)

    declared = metadata.for_artifact("skill/nulls")
    assert declared.tags == ()
    assert declared.superseded_by is None
    collection = metadata.collections[0]
    assert collection.key == "empty-one"
    assert collection.title is None
    assert collection.members == ()
    # Positive control: the same keys, given values, are read — so the emptiness above is the null
    # values speaking, not the keys being ignored.
    write_library_yaml(
        tmp_path,
        "artifacts:\n"
        "  skill/nulls:\n"
        "    tags: [t]\n"
        "    superseded_by: skill/other\n"
        "collections:\n"
        "  empty-one:\n"
        "    title: T\n"
        "    members: [skill/nulls]\n",
    )
    filled = read_library_metadata(tmp_path)
    assert filled.for_artifact("skill/nulls").tags == ("t",)
    assert filled.for_artifact("skill/nulls").superseded_by == "skill/other"
    assert filled.collections[0].title == "T"
    assert filled.collections[0].members == ("skill/nulls",)


def test_a_null_artifact_entry_declares_nothing(tmp_path: Path) -> None:
    """`skill/foo:` with nothing under it is a mention, not a malformed entry."""
    write_library_yaml(tmp_path, "artifacts:\n  skill/mentioned:\n")

    metadata = read_library_metadata(tmp_path)

    assert "skill/mentioned" in metadata.artifacts
    assert metadata.for_artifact("skill/mentioned") == EMPTY_ARTIFACT_METADATA


def test_null_top_level_sections_are_empty_not_missing(tmp_path: Path) -> None:
    """`artifacts:` and `collections:` written bare declare nothing, and do not fail."""
    write_library_yaml(tmp_path, "artifacts:\ncollections:\n")

    assert read_library_metadata(tmp_path) == LibraryMetadata.empty()


# Behaviour 4 — a scalar where a list is expected is diagnosed, not coerced, not crashed on.


def test_a_scalar_where_tags_expects_a_list_is_diagnosed_with_its_line(tmp_path: Path) -> None:
    """`tags: process` is neither silently promoted to `["process"]` nor an unhandled crash."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n"  # line 1
        "  skill/one:\n"  # line 2
        "    tags: process\n",  # line 3
    )

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 3
    assert caught.value.code is ErrorCode.LIBRARY_YAML_INVALID
    assert "must be a list of strings" in caught.value.reason
    assert "[process]" in caught.value.reason


def test_a_scalar_where_members_expects_a_list_is_diagnosed(tmp_path: Path) -> None:
    """The same rule, on the collections side, so it is one helper and not two behaviours."""
    write_library_yaml(
        tmp_path,
        "collections:\n"  # line 1
        "  ctg-delivery:\n"  # line 2
        "    title: CTG delivery system\n"  # line 3
        "    members: skill/delivery-lead\n",  # line 4
    )

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 4
    assert "must be a list of strings" in caught.value.reason


def test_a_list_where_a_string_is_expected_is_diagnosed(tmp_path: Path) -> None:
    """The converse coercion is refused too: `superseded_by` takes one id, not a list of them."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n  skill/one:\n    superseded_by: [skill/two, skill/three]\n",
    )

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 3
    assert "must be a string" in caught.value.reason


def test_a_non_string_scalar_is_not_coerced_into_a_tag(tmp_path: Path) -> None:
    """`tags: [2024]` is an int in YAML. Quoting it is the author's decision, not the reader's."""
    write_library_yaml(tmp_path, "artifacts:\n  skill/one:\n    tags: [2024]\n")

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 3
    # Positive control: the same document with the value quoted is read without complaint, so the
    # rejection is the scalar's type speaking and not the list shape.
    write_library_yaml(tmp_path, 'artifacts:\n  skill/one:\n    tags: ["2024"]\n')
    assert read_library_metadata(tmp_path).for_artifact("skill/one").tags == ("2024",)


# The happy path, and the shape rules that guard it.


def test_a_well_formed_document_is_read_whole(tmp_path: Path) -> None:
    """The format from the initiative plan, read end to end, in declaration order."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n"
        "  skill/delivery-lead:\n"
        "    tags: [orchestration, process]\n"
        "  skill/developers-orchestration:\n"
        "    superseded_by: skill/delivery-lead\n"
        "collections:\n"
        "  ctg-delivery:\n"
        "    title: CTG delivery system\n"
        "    description: The full spec-to-delivery chain.\n"
        "    members: [skill/delivery-lead, agent/backend-developer-specialist]\n",
    )

    metadata = read_library_metadata(tmp_path)

    lead = metadata.for_artifact("skill/delivery-lead")
    assert lead.tags == ("orchestration", "process")
    assert lead.superseded_by is None

    old = metadata.for_artifact("skill/developers-orchestration")
    assert old.superseded_by == "skill/delivery-lead"
    assert old.tags == ()

    assert len(metadata.collections) == 1
    collection = metadata.collections[0]
    assert collection.key == "ctg-delivery"
    assert collection.title == "CTG delivery system"
    assert collection.description == "The full spec-to-delivery chain."
    assert collection.members == (
        "skill/delivery-lead",
        "agent/backend-developer-specialist",
    )


def test_an_undeclared_artifact_reads_as_the_empty_declaration(tmp_path: Path) -> None:
    """`for_artifact` never returns `None`; an undeclared artifact has no tags and no successor."""
    write_library_yaml(tmp_path, "artifacts:\n  skill/one:\n    tags: [a]\n")

    metadata = read_library_metadata(tmp_path)

    assert metadata.for_artifact("skill/never-mentioned") == EMPTY_ARTIFACT_METADATA
    # Positive control: an id that *is* declared comes back with its tags, so the empty result
    # above is the lookup missing and not the document failing to load.
    assert metadata.for_artifact("skill/one").tags == ("a",)


@pytest.mark.parametrize(
    ("document", "line", "fragment"),
    [
        pytest.param("artifact:\n  skill/one:\n", 1, "'artifact'", id="top-level"),
        pytest.param("artifacts:\n  skill/one:\n    tag: [a]\n", 3, "'tag'", id="artifact-entry"),
        pytest.param(
            "collections:\n  c:\n    member: [skill/one]\n",
            3,
            "'member'",
            id="collection-entry",
        ),
    ],
)
def test_an_unknown_key_is_rejected_with_its_line(
    tmp_path: Path, document: str, line: int, fragment: str
) -> None:
    """Ignoring `tag:` for `tags:` is exactly how a user's metadata vanishes with no explanation."""
    write_library_yaml(tmp_path, document)

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == line
    assert fragment in caught.value.reason


def test_a_scalar_document_is_rejected(tmp_path: Path) -> None:
    """A file that is a bare string is not a metadata document."""
    write_library_yaml(tmp_path, "just a string\n")

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 1
    assert "must be a mapping" in caught.value.reason


def test_artifacts_as_a_list_is_rejected(tmp_path: Path) -> None:
    """The format keys artifacts by id; a list of them is a different document."""
    write_library_yaml(tmp_path, "artifacts:\n  - skill/one\n")

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 2
    assert "must be a mapping" in caught.value.reason


def test_an_empty_collection_key_is_rejected(tmp_path: Path) -> None:
    """An empty collection key is refused with a line, rather than as a `ValueError` escaping
    from the domain constructor far from the file that caused it."""
    write_library_yaml(tmp_path, 'collections:\n  "":\n    members: []\n')

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 2


# Safety — ruling R1. The file comes out of a user's repository.


def test_a_python_object_tag_is_rejected_and_never_constructed(tmp_path: Path) -> None:
    """R1: no loader that can construct arbitrary Python objects.

    The document below is what an unsafe loader would turn into a subprocess call. Composing stops
    at the node tree and never reaches a constructor, so the tag arrives at the reader as a value
    whose type is simply not a string, and is refused with a line.
    """
    marker = tmp_path / "pwned"
    write_library_yaml(
        tmp_path,
        "artifacts:\n"
        "  skill/one:\n"
        f"    superseded_by: !!python/object/apply:os.system ['touch {marker}']\n",
    )

    with pytest.raises(LibraryYamlError) as caught:
        read_library_metadata(tmp_path)

    assert caught.value.line == 3
    assert not marker.exists()
    # Positive control for that absence assertion: the marker path is one this test can observe
    # when something does create it, so "not created" is evidence and not an untestable claim.
    marker.write_text("", encoding="utf-8")
    assert marker.exists()


# What this reader deliberately does not do — the V7 seam.


def test_ids_that_resolve_to_nothing_are_returned_not_rejected(tmp_path: Path) -> None:
    """Shape, not resolution. V7 belongs to the assembler, which sees the whole library at once.

    A `LibraryMetadata` naming an artifact that does not exist on disk is *correct* output here:
    the reader is handed no tree and cannot know. Returning it is what lets V7 report it later
    with the id the user actually wrote.
    """
    write_library_yaml(
        tmp_path,
        "artifacts:\n"
        "  skill/does-not-exist:\n"
        "    superseded_by: skill/also-missing\n"
        "  not-even-an-id:\n"
        "    tags: [x]\n"
        "collections:\n"
        "  c:\n"
        "    members: [skill/nowhere]\n",
    )

    metadata = read_library_metadata(tmp_path)

    assert set(metadata.artifacts) == {"skill/does-not-exist", "not-even-an-id"}
    assert metadata.for_artifact("skill/does-not-exist").superseded_by == "skill/also-missing"
    assert metadata.collections[0].members == ("skill/nowhere",)


# Behaviour 7 — V9: a key declared twice is recorded, never silently collapsed.
#
# What this layer is blind to: it records the duplication and nothing else. That a `DuplicateKey`
# becomes a V9 ERROR finding is charter §8's decision and is asserted in
# `tests/domain/test_assembly.py`. Recording without judging is the same division of labour the
# scanner and the assembler already use for V6.


def test_an_artifact_id_declared_twice_is_recorded_as_a_duplicate(tmp_path: Path) -> None:
    """The named assertion of mutation (b).

    `yaml.compose` (R16) is what makes this observable at all: `YamlMapping.pairs` is a list, so
    both blocks survive. Under `safe_load` the first block's tags would already be gone.
    """
    write_library_yaml(
        tmp_path,
        "artifacts:\n"  # line 1
        "  skill/one:\n"  # line 2
        "    tags: [first]\n"  # line 3
        "  skill/two:\n"  # line 4
        "    tags: [other]\n"  # line 5
        "  skill/one:\n"  # line 6 — the repeat
        "    tags: [second]\n",  # line 7
    )

    metadata = read_library_metadata(tmp_path)

    assert [(d.key, d.first_line, d.line, d.context) for d in metadata.duplicate_keys] == [
        ("skill/one", 2, 6, ("artifacts",))
    ]


def test_a_key_declared_once_records_no_duplicate(tmp_path: Path) -> None:
    """Must stay green under mutation (b): a single occurrence of a key is still read correctly and
    reports nothing.

    Deliberately holds no duplicate of its own — its positive control is the sibling above, which
    proves the reader is capable of recording one. The tag assertions are what keep this test from
    passing vacuously if the reader stopped reading altogether.
    """
    write_library_yaml(
        tmp_path,
        "artifacts:\n"
        "  skill/one:\n"
        "    tags: [first]\n"
        "  skill/two:\n"
        "    tags: [other]\n"
        "collections:\n"
        "  backend:\n"
        "    members: [skill/one]\n",
    )

    metadata = read_library_metadata(tmp_path)

    assert metadata.duplicate_keys == ()
    assert metadata.for_artifact("skill/one").tags == ("first",)
    assert metadata.for_artifact("skill/two").tags == ("other",)
    assert metadata.collections[0].members == ("skill/one",)


def test_a_duplicate_collection_key_is_recorded(tmp_path: Path) -> None:
    write_library_yaml(
        tmp_path,
        "collections:\n"  # line 1
        "  backend:\n"  # line 2
        "    members: [skill/one]\n"  # line 3
        "  backend:\n"  # line 4 — the repeat
        "    members: [skill/two]\n",  # line 5
    )

    metadata = read_library_metadata(tmp_path)

    assert [(d.key, d.first_line, d.line) for d in metadata.duplicate_keys] == [("backend", 2, 4)]
    assert metadata.duplicate_keys[0].context == ("collections",)


def test_a_repeated_key_inside_one_entry_is_recorded_with_its_context(tmp_path: Path) -> None:
    """Charter §8 heads V9 "a duplicate key in `library.yaml`". A `tags:` written twice inside one
    entry discards a block exactly as silently as a repeated id, so it is the same fault; the
    context is what lets the report say which mapping it happened in."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n"  # line 1
        "  skill/one:\n"  # line 2
        "    tags: [first]\n"  # line 3
        "    tags: [second]\n",  # line 4 — the repeat
    )

    metadata = read_library_metadata(tmp_path)

    assert [(d.key, d.first_line, d.line, d.context) for d in metadata.duplicate_keys] == [
        ("tags", 3, 4, ("artifacts", "skill/one"))
    ]


def test_a_top_level_section_declared_twice_is_recorded(tmp_path: Path) -> None:
    write_library_yaml(
        tmp_path,
        "artifacts:\n"  # line 1
        "  skill/one:\n"  # line 2
        "collections: {}\n"  # line 3
        "artifacts:\n"  # line 4 — the repeat
        "  skill/two:\n",  # line 5
    )

    metadata = read_library_metadata(tmp_path)

    assert [(d.key, d.first_line, d.line, d.context) for d in metadata.duplicate_keys] == [
        ("artifacts", 1, 4, ())
    ]


def test_the_same_id_in_two_different_mappings_is_not_a_duplicate(tmp_path: Path) -> None:
    """An id may legitimately appear under `artifacts:` and again as a collection member. Only a
    key repeated *within one mapping* loses data."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n  skill/one:\n    tags: [a]\ncollections:\n  backend:\n    members:\n"
        "      - skill/one\n",
    )

    metadata = read_library_metadata(tmp_path)

    assert metadata.duplicate_keys == ()
    assert metadata.collections[0].members == ("skill/one",)


def test_a_duplicate_does_not_stop_the_document_being_read(tmp_path: Path) -> None:
    """A duplicate is reported, not raised: the document parses and both blocks are understood, so
    it does not meet this reader's bar for "unusable". The surviving value stays last-wins — neither
    block can be preferred on merit — and the V9 ERROR is what says the document is wrong.
    """
    write_library_yaml(
        tmp_path,
        "artifacts:\n  skill/one:\n    tags: [first]\n  skill/one:\n    tags: [second]\n",
    )

    metadata = read_library_metadata(tmp_path)

    assert metadata.for_artifact("skill/one").tags == ("second",)
    assert metadata.duplicate_keys


def test_a_document_that_cannot_be_used_still_raises_ahead_of_any_duplicate(
    tmp_path: Path,
) -> None:
    """Collecting duplicates must not demote a shape failure into a finding: an unknown key in a
    file that also repeats one is still the hard, located error it was before."""
    write_library_yaml(
        tmp_path,
        "artifacts:\n  skill/one:\n    tag: [first]\n  skill/one:\n    tags: [second]\n",
    )

    with pytest.raises(LibraryYamlError, match="'tag' is not a key"):
        read_library_metadata(tmp_path)
