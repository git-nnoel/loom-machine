"""Feature F-3 rendered — and rulings R25 and R27, which are about what a search *admits*.

The search itself is decided and proven in `application/read/search.py`. What only this layer can
break is the reporting: a CLI that computed its own matches, or that dropped the skipped-file list
on the way to the terminal, would turn a partial answer into an apparently complete one.
"""

from __future__ import annotations

from harness_library.cli.exit_codes import BAD_REQUEST
from tests.cli.conftest import Invoke, error_of, payload_of


def test_a_phrase_in_a_reference_file_is_found_with_its_path_and_line(hl: Invoke) -> None:
    """F-3: the match carries where it is, not merely that it exists."""
    payload = payload_of(hl("search", "delivery", "--json"))

    assert payload["query"] == "delivery"
    assert payload["matches"]
    first = payload["matches"][0]
    assert first["artifact_id"]
    assert first["path"]
    assert first["line_number"] >= 1
    assert "delivery" in first["line_text"].lower()


def test_the_skipped_files_are_reported_and_never_called_binary(hl: Invoke) -> None:
    """**Rulings R25 and R27.** A file that was not searched is named, with a reason, and the
    reason is never the word "binary" — the fixture's PNG is skipped because nothing would have
    searched a non-markdown file, which is true of a valid-UTF-8 HTML asset too."""
    payload = payload_of(hl("search", "delivery", "--json"))

    assert payload["skipped"], "R27: a search that skipped files in silence is the failure mode"
    reasons = {skipped["reason"] for skipped in payload["skipped"]}
    assert reasons <= {"not_a_markdown_reference", "unreadable_as_text"}
    assert not any("binary" in skipped["message"].lower() for skipped in payload["skipped"])


def test_the_skipped_files_are_visible_in_the_human_rendering_too(hl: Invoke) -> None:
    """R27 is about what a *user* sees. A payload carrying the omission that the terminal drops is
    an omission that is still silent where it matters."""
    result = hl("search", "delivery")

    assert result.exit_code == 0
    assert "not searched" in result.stdout
    assert "not_a_markdown_reference" in result.stdout


def test_a_result_set_reports_whether_it_was_truncated(hl: Invoke) -> None:
    """`truncated` is a field on every result, not only on a clipped one: a caller must be able to
    read "this answer is complete" as positively as "this answer is partial"."""
    payload = payload_of(hl("search", "delivery", "--json"))

    assert payload["truncated"] is False
    assert payload["limit"] == 200


def test_a_search_matching_nothing_succeeds_with_no_matches(hl: Invoke) -> None:
    """An empty answer is a legitimate answer and must not be confused with a failure."""
    payload = payload_of(hl("search", "zzz-no-such-phrase-zzz", "--json"))

    assert payload["matches"] == []
    assert payload["truncated"] is False


def test_a_blank_query_is_rejected_rather_than_answered(hl: Invoke) -> None:
    """The positive control for the searches above: this command *can* fail. An empty needle is a
    substring of every line, so answering it would fill the cap from an arbitrary corner."""
    result = hl("search", "   ", "--json")

    assert result.exit_code == BAD_REQUEST
    assert error_of(result)["code"] == "INVALID_QUERY"
    assert result.stdout == ""


def test_a_filter_narrows_the_search_the_same_way_it_narrows_a_listing(hl: Invoke) -> None:
    """`hl search --tag x` and `hl list --tag x` share `select_artifacts`, so they cannot disagree
    about what a tag means; this asserts the CLI actually passes the filter through."""
    payload = payload_of(hl("search", "delivery", "--tag", "process", "--json"))
    searched = {match["artifact_id"] for match in payload["matches"]}

    assert searched <= {"skill/delivery-lead", "skill/messy"}
