"""Feature F-3 — what is searched, what is skipped, and where the answer stops.

Three rules are under test and each has a way of passing vacuously, so each is pinned twice:

* **ruling R4** — only the entry document and `.md` files under `references/` are searched. A test
  asserting a file was *not* searched is worthless alone, so every such assertion here sits beside
  one proving the same search does find a match somewhere it should.
* **ruling R25** — the reason is *not a markdown reference*, never "binary". A UTF-8 HTML asset is
  the case that tells the two apart, so that is the fixture.
* **the cap** — `truncated` is a reported fact, not `len(matches) == limit`.
* **ruling R36** — a match carries the line either side of it. Every case below names the
  neighbouring lines as **values**, never as the presence of a field: the requirement survived
  three tasks unbuilt because the criterion said only "and context", which no test can fail.
"""

from __future__ import annotations

import pytest

from loom.application.read import (
    SEARCH_RESULT_LIMIT,
    ArtifactFilter,
    SearchSkipReason,
    search_artifacts,
)
from loom.domain.errors import ErrorCode, InvalidQueryError
from tests.application.fakes import (
    FakeArtifactRepository,
    make_artifact,
    make_file,
    skill_with_entry,
)

HTML_ASSET = "<html><body>needle in an asset</body></html>\n"
"""Valid UTF-8, and still not searched. This is the fixture ruling R25 turns on."""


def _library_with_one_of_everything() -> FakeArtifactRepository:
    """A skill holding an entry, a markdown reference, an HTML asset and a binary file."""
    artifact, contents = skill_with_entry(
        "delivery-lead",
        "# Delivery lead\nthe needle is here\n",
        references={
            "references/costs.md": "nothing to see\nanother needle line\n",
            "references/diagram.html": HTML_ASSET,
        },
        extra_files=(make_file("logo.png", b"\x89PNG\xff\xfe", is_text=False),),
    )
    contents[("skill/delivery-lead", "logo.png")] = b"\x89PNG\xff\xfe"
    return FakeArtifactRepository([artifact], contents=contents)


def test_a_phrase_only_in_a_reference_is_found_with_its_path_and_line_number() -> None:
    """Feature F-3's core case."""
    results = search_artifacts(_library_with_one_of_everything(), "another needle")

    assert [(m.path, m.line_number, m.line_text) for m in results.matches] == [
        ("references/costs.md", 2, "another needle line")
    ]
    assert results.matches[0].artifact_id == "skill/delivery-lead"


def test_the_entry_document_is_searched_too() -> None:
    results = search_artifacts(_library_with_one_of_everything(), "the needle is here")

    assert [(m.path, m.line_number) for m in results.matches] == [("SKILL.md", 2)]


def test_matching_is_case_insensitive() -> None:
    results = search_artifacts(_library_with_one_of_everything(), "NEEDLE IS HERE")

    assert [m.path for m in results.matches] == ["SKILL.md"]


def test_the_html_asset_is_not_searched_and_its_reason_is_not_the_word_binary() -> None:
    """Ruling R25, stated as plainly as the ruling is.

    The asset contains the needle and is valid UTF-8. If it were searched, the assertion on
    `matches` fails; if it were skipped for the wrong reason, the assertion on `reason` fails. The
    positive control is `test_a_phrase_only_in_a_reference_is_found...`, which proves this same
    search does find matches in files it is allowed to read.
    """
    results = search_artifacts(_library_with_one_of_everything(), "needle in an asset")

    assert results.matches == ()
    skipped = {s.path: s for s in results.skipped}
    assert skipped["references/diagram.html"].reason is SearchSkipReason.NOT_A_MARKDOWN_REFERENCE
    assert "binary" not in skipped["references/diagram.html"].message


def test_every_unsearched_file_is_reported_so_the_omission_is_visible() -> None:
    """Ruling R4: the skip is reported, never silent."""
    results = search_artifacts(_library_with_one_of_everything(), "needle")

    assert sorted(s.path for s in results.skipped) == ["logo.png", "references/diagram.html"]
    assert all(s.artifact_id == "skill/delivery-lead" for s in results.skipped)


def test_a_binary_file_is_skipped_for_the_same_reason_as_the_html_asset() -> None:
    """Ruling R25 again: the path test runs first, so the PNG's bytes never enter the reason.

    Structural, not a coincidence — `is_searchable` reads the path and nothing else, so no file
    that fails it can ever be reported as undecodable.
    """
    results = search_artifacts(_library_with_one_of_everything(), "needle")

    png = next(s for s in results.skipped if s.path == "logo.png")
    assert png.reason is SearchSkipReason.NOT_A_MARKDOWN_REFERENCE
    assert "binary" not in png.message


def test_a_markdown_reference_that_does_not_decode_is_reported_as_unreadable() -> None:
    """The only route to `UNREADABLE_AS_TEXT`, and it is reachable only past the path test."""
    artifact = make_artifact(
        "torn",
        files=(make_file("SKILL.md", b"needle\n"), make_file("references/bad.md", b"\xff\xfe")),
    )
    repository = FakeArtifactRepository(
        [artifact],
        contents={
            ("skill/torn", "SKILL.md"): b"needle\n",
            ("skill/torn", "references/bad.md"): b"\xff\xfe",
        },
    )

    results = search_artifacts(repository, "needle")

    assert [m.path for m in results.matches] == ["SKILL.md"]
    assert [(s.path, s.reason) for s in results.skipped] == [
        ("references/bad.md", SearchSkipReason.UNREADABLE_AS_TEXT)
    ]


# ----------------------------------------------------------------------------------------------
# Ruling R36 — one line of context either side
# ----------------------------------------------------------------------------------------------


def _one_skill(body: str) -> FakeArtifactRepository:
    """A single skill whose entry document is exactly `body`."""
    artifact, contents = skill_with_entry("delivery-lead", body)
    return FakeArtifactRepository([artifact], contents=contents)


CONTEXT_BODY = "# Delivery lead\nthe line above\nthe needle is here\nthe line below\ntail\n"
"""Five lines, the needle on the third, so neither neighbour is a file edge."""


def test_a_match_carries_the_lines_either_side_of_it_as_values() -> None:
    """Feature F-3 and ruling R36, and **named in advance as the assertion that must fail** when
    `line_before` and `line_after` are returned as `None` for every match.

    The neighbours are named here as literals. A test asserting only that the fields exist, or
    comparing them against lines recomputed from the same body, passes through exactly the change
    it exists to catch (L12).
    """
    results = search_artifacts(_one_skill(CONTEXT_BODY), "the needle")

    (match,) = results.matches
    assert (match.line_number, match.line_before, match.line_text, match.line_after) == (
        3,
        "the line above",
        "the needle is here",
        "the line below",
    )


def test_a_match_on_the_first_line_has_no_line_before_but_still_has_the_one_after() -> None:
    """`None` above, a real value below — so "no line there" is not being returned wholesale."""
    results = search_artifacts(_one_skill("needle at the top\nthe line below\n"), "needle")

    (match,) = results.matches
    assert (match.line_number, match.line_before, match.line_after) == (1, None, "the line below")


def test_a_match_on_the_last_line_has_no_line_after_but_still_has_the_one_before() -> None:
    """The mirror of the case above, and the one an off-by-one is most likely to survive: a
    negative index would wrap to the end of the file rather than run off it.
    """
    results = search_artifacts(_one_skill("the line above\nneedle at the end\n"), "needle")

    (match,) = results.matches
    assert (match.line_number, match.line_before, match.line_after) == (2, "the line above", None)


def test_a_match_in_a_single_line_file_has_no_neighbour_on_either_side() -> None:
    """**Named in advance as the control that must stay green** under the same mutation.

    Both neighbours are legitimately `None` here, so this test alone cannot tell "correct at a
    file edge" from "always `None`" — it is evidence only in the pair, beside
    `test_a_match_carries_the_lines_either_side_of_it_as_values`, which names real values.
    """
    results = search_artifacts(_one_skill("the needle, alone\n"), "needle")

    (match,) = results.matches
    assert (match.line_number, match.line_before, match.line_after) == (1, None, None)


def test_a_blank_neighbour_is_an_empty_string_and_not_an_absent_line() -> None:
    """The distinction ruling R36 turns on: a blank line *is* a line, and a consumer renders it
    differently from the end of a file. Flattening one into the other loses a fact.
    """
    results = search_artifacts(_one_skill("\nthe needle is here\n\ntail\n"), "needle")

    (match,) = results.matches
    assert (match.line_before, match.line_after) == ("", "")
    assert match.line_before is not None, "a blank line is present, not absent"
    assert match.line_after is not None


def test_a_neighbour_is_trimmed_of_trailing_whitespace_like_the_matching_line() -> None:
    """One rule for all three lines. A consumer joining them into a block would otherwise get
    ragged trailing space from the neighbours and none from the match.
    """
    results = search_artifacts(_one_skill("above   \nthe needle\nbelow\t\n"), "needle")

    (match,) = results.matches
    assert (match.line_before, match.line_after) == ("above", "below")


def test_every_match_in_a_file_gets_its_own_neighbours() -> None:
    """Two matches, two different contexts — the neighbours are per match, not per file."""
    results = search_artifacts(_one_skill("a\nneedle one\nb\nneedle two\nc\n"), "needle")

    assert [(m.line_before, m.line_text, m.line_after) for m in results.matches] == [
        ("a", "needle one", "b"),
        ("b", "needle two", "c"),
    ]


def _many_matches(count: int) -> FakeArtifactRepository:
    """One skill whose entry document holds `count` matching lines."""
    body = "".join(f"needle {index}\n" for index in range(count))
    artifact, contents = skill_with_entry("big", body)
    return FakeArtifactRepository([artifact], contents=contents)


def test_a_result_set_above_the_cap_is_truncated() -> None:
    """The mutation check names this test: removing the cap must break it."""
    results = search_artifacts(_many_matches(SEARCH_RESULT_LIMIT + 25), "needle")

    assert results.truncated is True
    assert len(results.matches) == SEARCH_RESULT_LIMIT
    assert results.limit == SEARCH_RESULT_LIMIT


def test_an_under_cap_search_returns_every_match_and_is_not_truncated() -> None:
    """The control the mutation check must leave green: the cap does not clip a small answer."""
    results = search_artifacts(_many_matches(7), "needle")

    assert results.truncated is False
    assert len(results.matches) == 7
    assert [m.line_number for m in results.matches] == [1, 2, 3, 4, 5, 6, 7]


def test_a_search_finding_exactly_the_cap_is_not_truncated() -> None:
    """`truncated` is a reported fact, not `len(matches) == limit` inferred by a caller."""
    results = search_artifacts(_many_matches(4), "needle", limit=4)

    assert len(results.matches) == 4
    assert results.truncated is False


def test_the_cap_is_configurable_so_an_adapter_can_ask_for_less() -> None:
    results = search_artifacts(_many_matches(10), "needle", limit=3)

    assert (len(results.matches), results.truncated, results.limit) == (3, True, 3)


def test_an_empty_query_is_refused_rather_than_matching_everything() -> None:
    with pytest.raises(InvalidQueryError) as raised:
        search_artifacts(_library_with_one_of_everything(), "   ")

    assert raised.value.code is ErrorCode.INVALID_QUERY


def test_search_honours_the_artifact_filter() -> None:
    """One vocabulary for `loom list --tag x` and `loom search --tag x`, so they cannot disagree."""
    tagged, tagged_contents = skill_with_entry("tagged", "needle here\n", tags=("process",))
    plain, plain_contents = skill_with_entry("plain", "needle here\n")
    repository = FakeArtifactRepository(
        [tagged, plain], contents={**tagged_contents, **plain_contents}
    )

    unfiltered = search_artifacts(repository, "needle")
    filtered = search_artifacts(repository, "needle", artifact_filter=ArtifactFilter(tag="process"))

    assert {m.artifact_id for m in unfiltered.matches} == {"skill/tagged", "skill/plain"}
    assert {m.artifact_id for m in filtered.matches} == {"skill/tagged"}


def test_results_are_returned_in_the_default_listing_order() -> None:
    """A golden list. Ruling R8 applies here too, so a truncated answer is reproducible."""
    zulu, zulu_contents = skill_with_entry("zulu", "needle\n")
    alpha, alpha_contents = skill_with_entry("alpha", "needle\n", superseded_by="skill/zulu")
    mid, mid_contents = skill_with_entry("mid", "needle\n")
    repository = FakeArtifactRepository(
        [zulu, alpha, mid], contents={**zulu_contents, **alpha_contents, **mid_contents}
    )

    results = search_artifacts(repository, "needle")

    assert [m.artifact_id for m in results.matches] == ["skill/mid", "skill/zulu", "skill/alpha"]


def test_a_skill_with_no_entry_document_contributes_nothing_and_does_not_raise() -> None:
    repository = FakeArtifactRepository([make_artifact("no-entry")])

    results = search_artifacts(repository, "needle")

    assert (results.matches, results.skipped) == ((), ())
