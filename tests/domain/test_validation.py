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
    "V8": Severity.ERROR,
    "V9": Severity.ERROR,
    "V10": Severity.ERROR,
    "V11": Severity.WARNING,
}
"""Charter §8's register, transcribed. V10 arrived with ruling R33 — unparseable frontmatter is its
own finding rather than a cascade of false "key is missing" reports. V11 arrived with ruling R46:
an artifact root that is a symlink is never followed, never scanned and so silently absent, and
reporting the absence is the whole of the rule."""


def _register_in_rule_order() -> list[tuple[str, Severity]]:
    """The register as pairs, V1 first and V11 last."""
    return sorted(CHARTER_SECTION_8.items(), key=lambda pair: _rule_number(pair[0]))


def _rule_number(code_value: str) -> int:
    """`V10` sorts after `V9`, which lexicographic order does not.

    Worth the three lines: comparing sorted *strings* would demand the enum be declared V1, V10, V2,
    … to stay green, which is a declaration order no reader of charter §8 would recognise.
    """
    return int(code_value.removeprefix("V"))


def test_the_code_set_is_exactly_the_charter_register() -> None:
    """Closed. Initiative 04 branches on the code, so a member added without a charter row —
    or a row added without a member — has to fail here.

    Declaration order is asserted too, and separately: the enum reads V1 … V11 in rule order, so a
    member appended in the wrong place is visible here rather than only in a report's ordering.
    """
    assert {code.value for code in ValidationCode} == set(CHARTER_SECTION_8)
    assert [code.value for code in ValidationCode] == sorted(CHARTER_SECTION_8, key=_rule_number)


@pytest.mark.parametrize(("code_value", "expected"), _register_in_rule_order())
def test_each_code_carries_the_severity_the_charter_assigns_it(
    code_value: str, expected: Severity
) -> None:
    assert ValidationCode(code_value).severity is expected


def test_v6_and_v11_are_the_only_warnings() -> None:
    """The positive control for the WARNING half of the register: exactly two codes are warnings,
    so a table-wide flip to WARNING cannot pass as 'V6 is still a warning'.

    V11 joined V6 under ruling R46. That it is a warning and nonetheless refuses one artifact's
    install is not a severity question and is not decided here — the register says how much the
    finding matters, and `application/write/install.py` says what install does about it. R22's
    one exception is stated in charter §8 and spec §4, and asserted where the refusal lives.
    """
    warnings = [code for code in ValidationCode if code.severity is Severity.WARNING]
    assert warnings == [ValidationCode.V6, ValidationCode.V11]
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
