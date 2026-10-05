"""Feature F-4 — the library's verdict.

Two rulings decide everything here and both have a failure mode that looks like success:

* **ruling R23** — V7 and V9 exist *only* at library level. A report built from artifacts alone
  passes every artifact-level test and silently makes two rows of charter §8 unable to fail
  anything. The mutation check for this task is aimed exactly there.
* **ruling R22** — severity decides validity. A report that counted findings rather than ERROR
  findings would call a library with one editor swap file invalid and block an install over it.
"""

from __future__ import annotations

from loom.application.read import validate_library
from loom.domain.validation import Severity, ValidationCode
from tests.application.fakes import FakeArtifactRepository, finding, make_artifact


def test_a_clean_library_is_valid_and_reports_no_artifacts() -> None:
    repository = FakeArtifactRepository([make_artifact("alpha"), make_artifact("beta")])

    report = validate_library(repository)

    assert report.is_valid is True
    assert report.artifact_count == 2
    assert (report.error_count, report.warning_count) == (0, 0)
    assert report.artifacts == ()


def test_only_artifacts_carrying_findings_appear_in_the_report() -> None:
    """A clean artifact is absent, which is what makes "this rule did not fire" assertable."""
    repository = FakeArtifactRepository(
        [make_artifact("clean"), make_artifact("broken", findings=(finding(ValidationCode.V1),))]
    )

    report = validate_library(repository)

    assert [a.id for a in report.artifacts] == ["skill/broken"]
    assert report.artifact_count == 2


def test_a_finding_reaches_the_report_carrying_its_machine_code() -> None:
    """Contract C-3. Initiative 04's SPA branches on `code`, never on `message`."""
    repository = FakeArtifactRepository(
        [
            make_artifact(
                "broken",
                findings=(finding(ValidationCode.V3, "cites references/gone.md", "SKILL.md"),),
            )
        ]
    )

    reported = validate_library(repository).artifacts[0].findings[0]

    assert reported.code is ValidationCode.V3
    assert reported.severity is Severity.ERROR
    assert reported.path == "SKILL.md"


def test_a_warning_alone_leaves_the_library_valid() -> None:
    """Ruling R22, and its positive control is the sibling below: an ERROR *does* flip `is_valid`,
    so this assertion is capable of failing."""
    repository = FakeArtifactRepository(
        [make_artifact("swap", findings=(finding(ValidationCode.V6, path="SKILL.md.swp"),))]
    )

    report = validate_library(repository)

    assert report.is_valid is True
    assert (report.error_count, report.warning_count) == (0, 1)
    assert report.artifacts[0].is_valid is True


def test_an_error_makes_the_library_invalid() -> None:
    repository = FakeArtifactRepository(
        [make_artifact("broken", findings=(finding(ValidationCode.V1),))]
    )

    report = validate_library(repository)

    assert report.is_valid is False
    assert (report.error_count, report.warning_count) == (1, 0)


def test_a_library_level_v7_reaches_the_report_and_makes_the_library_invalid() -> None:
    """**Ruling R23.** The mutation check names this test.

    V7 belongs to no artifact — a `library.yaml` entry that resolves to nothing has, by
    definition, no artifact to hang itself on. If the report is built from `list_all()` alone this
    fails, and the rule becomes decorative: charter §8 declares it an ERROR and it could never
    make a library invalid.
    """
    repository = FakeArtifactRepository(
        [make_artifact("alpha")],
        library_findings=[finding(ValidationCode.V7, "skill/ghost resolves to nothing")],
    )

    report = validate_library(repository)

    assert [f.code for f in report.library_findings] == [ValidationCode.V7]
    assert report.is_valid is False
    assert report.error_count == 1
    assert report.artifacts == ()


def test_a_library_level_v9_reaches_the_report_too() -> None:
    """Ruling R23's other rule. A duplicate key silently discards a block's tags; that is the
    precise silent-data-loss failure this product exists to eliminate, so it must reach a report."""
    repository = FakeArtifactRepository(
        [make_artifact("alpha")],
        library_findings=[finding(ValidationCode.V9, "'skill/alpha' declared twice")],
    )

    report = validate_library(repository)

    assert [f.code for f in report.library_findings] == [ValidationCode.V9]
    assert report.is_valid is False


def test_counts_span_artifacts_and_the_library_together() -> None:
    """One number, not two: a caller asking "how bad is it" must not have to add them up."""
    repository = FakeArtifactRepository(
        [
            make_artifact(
                "broken",
                findings=(finding(ValidationCode.V1), finding(ValidationCode.V6, path="a.swp")),
            )
        ],
        library_findings=[finding(ValidationCode.V7), finding(ValidationCode.V9)],
    )

    report = validate_library(repository)

    assert (report.error_count, report.warning_count) == (3, 1)
    assert report.is_valid is False
