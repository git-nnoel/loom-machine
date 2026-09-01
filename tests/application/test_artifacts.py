"""Features F-1 and F-2 — listing, filtering, ordering, and showing one artifact.

Every expected order in this module is a **golden literal**, never a recomputation (lesson L12). An
assertion comparing `sort_artifacts(x, key)` against a list comprehension that applies the same key
is invisible to a mutation of the key: both sides move together and the test stays green. The lists
below are written out, so reversing a comparison or dropping ruling R8's rank breaks them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from harness_library.application.read import (
    ArtifactFilter,
    SortKey,
    get_artifact,
    get_artifact_file,
    list_artifacts,
)
from harness_library.domain.errors import (
    ArtifactFileNotFoundError,
    ArtifactNotFoundError,
    CollectionNotFoundError,
    ErrorCode,
    FileNotTextError,
    InvalidFilePathError,
)
from harness_library.domain.identity import ArtifactType
from harness_library.domain.metadata import Collection
from harness_library.domain.validation import ValidationCode
from tests.application.fakes import (
    FakeArtifactRepository,
    finding,
    make_artifact,
    make_file,
    skill_with_entry,
)


def ids(payload_artifacts: object) -> list[str]:
    assert isinstance(payload_artifacts, tuple)
    return [artifact.id for artifact in payload_artifacts]


# -- Listing and filters -------------------------------------------------------------------------


def test_every_artifact_appears_including_the_invalid_ones() -> None:
    """Feature F-1. An artifact that is invisible because it is broken is the failure this
    product exists to close, so the listing is where that must not happen."""
    broken = make_artifact("no-entry", findings=(finding(ValidationCode.V1, "no SKILL.md"),))
    repository = FakeArtifactRepository([make_artifact("clean"), broken])

    payload = list_artifacts(repository)

    assert ids(payload.artifacts) == ["skill/clean", "skill/no-entry"]
    assert payload.total == 2
    assert [a.is_valid for a in payload.artifacts] == [True, False]


def test_the_invalid_only_filter_keeps_error_artifacts_and_drops_the_rest() -> None:
    repository = FakeArtifactRepository(
        [
            make_artifact("clean"),
            make_artifact("broken", findings=(finding(ValidationCode.V1),)),
        ]
    )

    payload = list_artifacts(repository, artifact_filter=ArtifactFilter(invalid_only=True))

    assert ids(payload.artifacts) == ["skill/broken"]


def test_a_warning_only_artifact_is_not_invalid() -> None:
    """Ruling R22 — severity decides validity, and V6 is a WARNING.

    The positive control is the sibling above: `invalid_only` demonstrably *does* select an
    artifact, so this assertion of absence is capable of failing.
    """
    repository = FakeArtifactRepository(
        [make_artifact("swap-file", findings=(finding(ValidationCode.V6, path="SKILL.md.swp"),))]
    )

    assert list_artifacts(repository).artifacts[0].is_valid is True
    assert list_artifacts(repository, artifact_filter=ArtifactFilter(invalid_only=True)).total == 0


def test_the_type_filter_selects_one_type() -> None:
    repository = FakeArtifactRepository(
        [
            make_artifact("writer", artifact_type=ArtifactType.AGENT),
            make_artifact("writing"),
        ]
    )

    payload = list_artifacts(repository, artifact_filter=ArtifactFilter(type=ArtifactType.AGENT))

    assert ids(payload.artifacts) == ["agent/writer"]


def test_the_tag_filter_matches_exactly() -> None:
    repository = FakeArtifactRepository(
        [
            make_artifact("alpha", tags=("process", "review")),
            make_artifact("beta", tags=("Process",)),
            make_artifact("gamma"),
        ]
    )

    payload = list_artifacts(repository, artifact_filter=ArtifactFilter(tag="process"))

    assert ids(payload.artifacts) == ["skill/alpha"]


def test_an_unused_tag_yields_an_empty_listing_rather_than_an_error() -> None:
    """A tag is free-form, so an unrecognised one is indistinguishable from an unused one."""
    repository = FakeArtifactRepository([make_artifact("alpha", tags=("process",))])

    assert list_artifacts(repository, artifact_filter=ArtifactFilter(tag="absent")).total == 0


def test_the_collection_filter_selects_declared_members() -> None:
    repository = FakeArtifactRepository(
        [make_artifact("alpha"), make_artifact("beta"), make_artifact("gamma")],
        collections=[Collection(key="core", members=("skill/gamma", "skill/alpha"))],
    )

    payload = list_artifacts(repository, artifact_filter=ArtifactFilter(collection="core"))

    assert ids(payload.artifacts) == ["skill/alpha", "skill/gamma"]


def test_an_undeclared_collection_fails_loudly() -> None:
    """Charter §13. A collection key *is* declared, unlike a tag, so silence would be a lie."""
    repository = FakeArtifactRepository([make_artifact("alpha")])

    with pytest.raises(CollectionNotFoundError) as raised:
        list_artifacts(repository, artifact_filter=ArtifactFilter(collection="core"))

    assert raised.value.code is ErrorCode.COLLECTION_NOT_FOUND


def test_an_empty_collection_narrows_the_listing_to_nothing() -> None:
    """The sentinel for "no collection filter" must not be confused with an empty one."""
    repository = FakeArtifactRepository(
        [make_artifact("alpha")], collections=[Collection(key="empty")]
    )

    assert list_artifacts(repository, artifact_filter=ArtifactFilter(collection="empty")).total == 0


def test_filters_combine_with_and() -> None:
    repository = FakeArtifactRepository(
        [
            make_artifact("alpha", tags=("process",)),
            make_artifact("writer", artifact_type=ArtifactType.AGENT, tags=("process",)),
        ]
    )

    payload = list_artifacts(
        repository, artifact_filter=ArtifactFilter(type=ArtifactType.SKILL, tag="process")
    )

    assert ids(payload.artifacts) == ["skill/alpha"]


# -- Ruling R8 -----------------------------------------------------------------------------------


def _supersession_library() -> FakeArtifactRepository:
    """`beta` is retired in favour of `alpha`; `gamma` is live and sorts last by name."""
    return FakeArtifactRepository(
        [
            make_artifact("beta", superseded_by="skill/alpha"),
            make_artifact("alpha"),
            make_artifact("gamma"),
        ]
    )


def test_a_superseded_artifact_appears_by_default_and_ranks_below_the_live_ones() -> None:
    """Ruling R8, as a golden list.

    `beta` sorts first alphabetically and appears **last** because it is superseded; `gamma` sorts
    after `alpha` and stays there. Both halves matter: the first proves the rank is applied, the
    second proves it did not simply reverse the order.
    """
    payload = list_artifacts(_supersession_library())

    assert ids(payload.artifacts) == ["skill/alpha", "skill/gamma", "skill/beta"]


def test_every_payload_carries_superseded_by() -> None:
    """Ruling R8 — a consumer must always be able to see that an artifact is retired."""
    payload = list_artifacts(_supersession_library())

    assert {a.id: a.superseded_by for a in payload.artifacts} == {
        "skill/alpha": None,
        "skill/gamma": None,
        "skill/beta": "skill/alpha",
    }


def test_include_superseded_false_is_the_only_thing_that_hides_one() -> None:
    """Positive control for the default: the listing *can* drop `beta`, and by default does not."""
    repository = _supersession_library()

    assert "skill/beta" in ids(list_artifacts(repository).artifacts)
    narrowed = list_artifacts(repository, artifact_filter=ArtifactFilter(include_superseded=False))
    assert ids(narrowed.artifacts) == ["skill/alpha", "skill/gamma"]


# -- Sort keys -----------------------------------------------------------------------------------


def _sortable_library() -> FakeArtifactRepository:
    """Three artifacts whose name, timestamp and size orders are all different from one another.

    Deliberate: if two of the three orders coincided, a sort key silently falling back to another
    would pass. `zulu` is superseded, so ruling R8's rank is exercised by every key at once.
    """
    return FakeArtifactRepository(
        [
            make_artifact(
                "mid",
                files=(make_file("SKILL.md", b"x" * 300),),
                updated_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            make_artifact(
                "aaa",
                files=(make_file("SKILL.md", b"x" * 100),),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            make_artifact(
                "zulu",
                files=(make_file("SKILL.md", b"x" * 900),),
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
                superseded_by="skill/aaa",
            ),
        ]
    )


@pytest.mark.parametrize(
    ("sort_key", "expected"),
    [
        (SortKey.NAME, ["skill/aaa", "skill/mid", "skill/zulu"]),
        (SortKey.UPDATED, ["skill/mid", "skill/aaa", "skill/zulu"]),
        (SortKey.SIZE, ["skill/mid", "skill/aaa", "skill/zulu"]),
    ],
)
def test_each_sort_key_has_a_golden_order(sort_key: SortKey, expected: list[str]) -> None:
    """Golden literals, per lesson L12.

    `zulu` is largest and newest and still ranks last under every key, because ruling R8 outranks
    the sort key. `mid` leads `aaa` under `updated` and `size` and trails it under `name`, so no
    two keys can be confused for one another.
    """
    payload = list_artifacts(_sortable_library(), sort_key=sort_key)

    assert ids(payload.artifacts) == expected
    assert payload.sort == sort_key.value


def test_the_order_is_total_when_the_key_ties() -> None:
    """Two artifacts with one name and one timestamp still have one defined position."""
    repository = FakeArtifactRepository(
        [
            make_artifact("twin", artifact_type=ArtifactType.SKILL),
            make_artifact("twin", artifact_type=ArtifactType.AGENT),
        ]
    )

    assert ids(list_artifacts(repository, sort_key=SortKey.NAME).artifacts) == [
        "agent/twin",
        "skill/twin",
    ]


# -- Feature F-2 ---------------------------------------------------------------------------------


def test_showing_a_valid_artifact_returns_entry_text_files_and_frontmatter() -> None:
    artifact, contents = skill_with_entry(
        "delivery-lead",
        "# Delivery lead\n",
        references={"references/costs.md": "budget\n"},
        frontmatter={"name": "delivery-lead", "description": "leads"},
    )
    repository = FakeArtifactRepository([artifact], contents=contents)

    detail = get_artifact(repository, "skill/delivery-lead")

    assert detail.entry_path == "SKILL.md"
    assert detail.entry_text == "# Delivery lead\n"
    assert [f.path for f in detail.files] == ["SKILL.md", "references/costs.md"]
    assert detail.frontmatter == {"name": "delivery-lead", "description": "leads"}


def test_showing_a_skill_with_no_entry_document_returns_its_finding_and_does_not_raise() -> None:
    """Feature F-2, and the case the superseded plan crashed on."""
    artifact = make_artifact("no-entry", findings=(finding(ValidationCode.V1, "no SKILL.md"),))
    repository = FakeArtifactRepository([artifact])

    detail = get_artifact(repository, "skill/no-entry")

    assert detail.entry_text is None
    assert detail.entry_path == "SKILL.md"
    assert [f.code for f in detail.findings] == [ValidationCode.V1]
    assert detail.is_valid is False


def test_an_agents_entry_path_is_its_own_basename() -> None:
    """From the type registry, so this layer holds no second opinion about the layout."""
    artifact = make_artifact(
        "writer",
        artifact_type=ArtifactType.AGENT,
        files=(make_file("writer.md", b"# writer\n"),),
    )
    repository = FakeArtifactRepository(
        [artifact], contents={("agent/writer", "writer.md"): b"# writer\n"}
    )

    detail = get_artifact(repository, "agent/writer")

    assert detail.entry_path == "writer.md"
    assert detail.entry_text == "# writer\n"


def test_an_unknown_id_becomes_artifact_not_found() -> None:
    """Ruling R24 — the repository's `None` and `KeyError` become one branchable code."""
    with pytest.raises(ArtifactNotFoundError) as raised:
        get_artifact(FakeArtifactRepository([]), "skill/absent")

    assert raised.value.code is ErrorCode.ARTIFACT_NOT_FOUND
    assert raised.value.artifact_id == "skill/absent"


# -- One file ------------------------------------------------------------------------------------


def test_reading_one_file_returns_its_text_and_its_recorded_digest() -> None:
    artifact, contents = skill_with_entry(
        "delivery-lead", references={"references/costs.md": "budget\n"}
    )
    repository = FakeArtifactRepository([artifact], contents=contents)

    content = get_artifact_file(repository, "skill/delivery-lead", "references/costs.md")

    assert content.text == "budget\n"
    assert content.is_text is True
    assert content.size == len(b"budget\n")
    assert content.sha256 == artifact.files[1].sha256


def test_reading_a_binary_file_returns_null_text_rather_than_mojibake() -> None:
    """Charter §7. The file exists and is readable; it is simply never decoded."""
    png = b"\x89PNG\r\n\x1a\n\xff\xfe"
    artifact = make_artifact(
        "assets",
        files=(make_file("SKILL.md", b"# a\n"), make_file("logo.png", png, is_text=False)),
    )
    repository = FakeArtifactRepository([artifact], contents={("skill/assets", "logo.png"): png})

    content = get_artifact_file(repository, "skill/assets", "logo.png")

    assert content.is_text is False
    assert content.text is None
    assert repository.read_calls == []


def test_a_file_the_scan_called_text_that_does_not_decode_becomes_file_not_text() -> None:
    """Ruling R24. A torn read (charter §7): the metadata and the bytes disagree.

    This is also the guard on the handler order in `_access`: `UnicodeDecodeError` is a subclass of
    `ValueError`, so catching `ValueError` first would report this as `INVALID_FILE_PATH`.
    """
    artifact = make_artifact("assets", files=(make_file("SKILL.md", b"\xff\xfe"),))
    repository = FakeArtifactRepository(
        [artifact], contents={("skill/assets", "SKILL.md"): b"\xff\xfe"}
    )

    with pytest.raises(FileNotTextError) as raised:
        get_artifact_file(repository, "skill/assets", "SKILL.md")

    assert raised.value.code is ErrorCode.FILE_NOT_TEXT


def test_an_undecodable_entry_document_does_not_stop_the_artifact_being_shown() -> None:
    """Feature F-2 again: showing an artifact never raises on the artifact's own defects."""
    artifact = make_artifact("assets", files=(make_file("SKILL.md", b"\xff\xfe"),))
    repository = FakeArtifactRepository(
        [artifact], contents={("skill/assets", "SKILL.md"): b"\xff\xfe"}
    )

    assert get_artifact(repository, "skill/assets").entry_text is None


def test_a_path_the_artifact_does_not_hold_becomes_file_not_found() -> None:
    artifact, contents = skill_with_entry("delivery-lead")
    repository = FakeArtifactRepository([artifact], contents=contents)

    with pytest.raises(ArtifactFileNotFoundError) as raised:
        get_artifact_file(repository, "skill/delivery-lead", "references/absent.md")

    assert raised.value.code is ErrorCode.FILE_NOT_FOUND


def test_a_traversal_path_becomes_invalid_file_path_and_not_file_not_found() -> None:
    """The two are different HTTP statuses in initiative 03, so they are different codes.

    The classification is the repository's, not this layer's: a path outside the snapshot is
    handed back to it precisely so a traversal attempt cannot be flattened into a typo here.
    """
    artifact, contents = skill_with_entry("delivery-lead")
    repository = FakeArtifactRepository([artifact], contents=contents)

    with pytest.raises(InvalidFilePathError) as raised:
        get_artifact_file(repository, "skill/delivery-lead", "../escape.md")

    assert raised.value.code is ErrorCode.INVALID_FILE_PATH
