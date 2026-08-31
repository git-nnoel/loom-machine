"""The validation register of charter §8, as code.

Two things are load-bearing here:

* **`ValidationCode` is closed.** Initiative 04's SPA branches on the code, so a rename must fail at
  every emitter rather than pass silently as a string nothing handles.
* **Severity belongs to the code, not to the emitter.** Charter §8 fixes the severity of each rule.
  `ValidationCode.severity` is the one place that decision lives; `ValidationFinding` carries the
  value as a field because contract C-3 freezes it there, and rejects any finding whose field
  disagrees with its code. A comment claiming the two agree would not be a mechanism.

This module defines the *vocabulary*. The rules that decide when each code fires belong to the
assembler, not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class Severity(StrEnum):
    """How much a finding matters. Closed."""

    ERROR = "error"
    WARNING = "warning"


class ValidationCode(StrEnum):
    """The closed set of validation rules. Charter §8 is the register; this is its encoding."""

    V1 = "V1"
    """A skill directory with no `SKILL.md`."""

    V2 = "V2"
    """Frontmatter `name` disagreeing with the directory name."""

    V3 = "V3"
    """A cited `references/…` path that does not exist. Exempt when `superseded_by` is set."""

    V4 = "V4"
    """`superseded_by` that does not resolve."""

    V5 = "V5"
    """Missing or empty required frontmatter key."""

    V6 = "V6"
    """Extraneous file under an artifact root. Reported, never deleted, never blocks install."""

    V7 = "V7"
    """A `library.yaml` entry or `collections[].members` id that resolves to nothing."""

    V8 = "V8"
    """Two artifacts of one type whose names differ only by case."""

    V9 = "V9"
    """A duplicate key in `library.yaml` — the same id or collection key declared twice."""

    @property
    def severity(self) -> Severity:
        """The severity charter §8 assigns to this rule."""
        return SEVERITY_BY_CODE[self]


SEVERITY_BY_CODE: Mapping[ValidationCode, Severity] = MappingProxyType(
    {
        ValidationCode.V1: Severity.ERROR,
        ValidationCode.V2: Severity.ERROR,
        ValidationCode.V3: Severity.ERROR,
        ValidationCode.V4: Severity.ERROR,
        ValidationCode.V5: Severity.ERROR,
        ValidationCode.V6: Severity.WARNING,
        ValidationCode.V7: Severity.ERROR,
        ValidationCode.V8: Severity.ERROR,
        ValidationCode.V9: Severity.ERROR,
    }
)
"""Charter §8's severity column. The single source; `ValidationCode.severity` reads it."""


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """Contract C-3. One thing a validation rule found.

    Attributes:
        code: the rule that fired. Closed; consumers branch on this and never on `message`.
        severity: charter §8's severity for `code`. Present because C-3 freezes it on the wire,
            and constrained to agree with `code` so the two cannot drift.
        message: a human sentence. Not contract — it may be reworded without notice.
        path: the file the finding is about, relative to the artifact root, or `None` when the
            finding is about the artifact as a whole. Present-and-null, never omitted.
    """

    code: ValidationCode
    severity: Severity
    message: str
    path: str | None = None

    def __post_init__(self) -> None:
        expected = self.code.severity
        if self.severity is not expected:
            raise ValueError(
                f"{self.code.value} is a {expected.value} finding per charter §8, "
                f"but was constructed with severity {self.severity.value}"
            )

    @classmethod
    def for_code(
        cls, code: ValidationCode, message: str, path: str | None = None
    ) -> ValidationFinding:
        """Build a finding, taking the severity from the register. The intended constructor."""
        return cls(code=code, severity=code.severity, message=message, path=path)
