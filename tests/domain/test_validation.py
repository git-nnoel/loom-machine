"""The validation register — charter §8."""

from __future__ import annotations

import pytest

from harness_library.domain.validation import (
    SEVERITY_BY_CODE,
    Severity,
    ValidationCode,
    ValidationFinding,
)

CHARTER_SECTION_8 = {
    "V1": Severity.ERROR,
    "V2": Severity.ERROR,
    "V3": Severity.ERROR,
    "V4": Severity.ERROR,
    "V5": Severity.ERROR,
    "V6": Severity.WARNING,
    "V7": Severity.ERROR,
}


def test_the_code_set_is_exactly_v1_to_v7() -> None:
    """Closed. Initiative 04 branches on the code, so a member added without a charter row —
    or a row added without a member — has to fail here."""
    assert [code.value for code in ValidationCode] == sorted(CHARTER_SECTION_8)


@pytest.mark.parametrize(("code_value", "expected"), sorted(CHARTER_SECTION_8.items()))
def test_each_code_carries_the_severity_the_charter_assigns_it(
    code_value: str, expected: Severity
) -> None:
    assert ValidationCode(code_value).severity is expected


def test_v6_is_the_only_warning() -> None:
    """The positive control for the WARNING half of the register: exactly one code is a warning,
    so a table-wide flip to WARNING cannot pass as 'V6 is still a warning'."""
    warnings = [code for code in ValidationCode if code.severity is Severity.WARNING]
    assert warnings == [ValidationCode.V6]
    assert SEVERITY_BY_CODE[ValidationCode.V1] is Severity.ERROR


def test_for_code_takes_the_severity_from_the_register() -> None:
    finding = ValidationFinding.for_code(ValidationCode.V6, "stray swap file", "SKILL.md.swp")
    assert finding.severity is Severity.WARNING
    assert finding.code is ValidationCode.V6
    assert finding.path == "SKILL.md.swp"


def test_path_defaults_to_none_for_a_whole_artifact_finding() -> None:
    finding = ValidationFinding.for_code(ValidationCode.V1, "no SKILL.md")
    assert finding.path is None


def test_a_finding_cannot_contradict_its_code() -> None:
    """One decision, one object. A caller that could downgrade V1 to a warning by hand would be a
    second source of truth for charter §8's severity column."""
    with pytest.raises(ValueError, match="V1"):
        ValidationFinding(code=ValidationCode.V1, severity=Severity.WARNING, message="no SKILL.md")
    with pytest.raises(ValueError, match="V6"):
        ValidationFinding(code=ValidationCode.V6, severity=Severity.ERROR, message="swap file")


def test_findings_are_frozen() -> None:
    finding = ValidationFinding.for_code(ValidationCode.V5, "missing description")
    with pytest.raises(AttributeError):
        finding.message = "something else"  # type: ignore[misc]
