"""The library's validation verdict — feature F-4, ruling R22 and ruling R23.

**Ruling R23 is the whole reason this is not a loop over `list_all()`.** V7 (a `library.yaml` entry
or collection member resolving to nothing) and V9 (a duplicate key in `library.yaml`) are faults of
the *document*, so the assembler attaches them to the library rather than to an artifact. They are
reachable only through `library_findings()`. A report built from artifacts alone would leave those
two rows of charter §8's register unable to fail anything — a rule that cannot reach a report can
never make a library invalid, which is the decorative-rule failure R22 and R23 both close.

**Ruling R22 decides validity, and severity decides ruling R22.** `is_valid` means no finding of
severity ERROR, anywhere. A WARNING never makes a library invalid and never blocks: charter §8
makes V6 — an editor swap file under an artifact root — a WARNING precisely so that reporting it
does not stop an artifact installing.
"""

from __future__ import annotations

from collections.abc import Iterable

from loom.application.read.dtos import (
    ArtifactValidation,
    FindingPayload,
    ValidationReport,
)
from loom.domain.repository import ArtifactRepository
from loom.domain.validation import Severity, ValidationFinding


def validate_library(repository: ArtifactRepository) -> ValidationReport:
    """Validate the whole library. Feature F-4.

    Reports **only the artifacts carrying at least one finding**, plus the library-level findings
    and counts taken over everything. A clean artifact is absent from `artifacts`, which is what
    lets a test assert that a rule does not fire on one; `artifact_count` still counts it, so the
    report says how much was checked and not merely how much was wrong.
    """
    artifacts = repository.list_all()
    library_findings = repository.library_findings()

    reported = tuple(
        ArtifactValidation(
            id=artifact.id,
            path=artifact.path,
            is_valid=artifact.is_valid,
            findings=tuple(FindingPayload.of(finding) for finding in artifact.findings),
        )
        for artifact in artifacts
        if artifact.findings
    )

    every_finding = [finding for artifact in artifacts for finding in artifact.findings] + list(
        library_findings
    )

    error_count = _count(every_finding, Severity.ERROR)
    return ValidationReport(
        is_valid=error_count == 0,
        artifact_count=len(artifacts),
        error_count=error_count,
        warning_count=_count(every_finding, Severity.WARNING),
        artifacts=reported,
        library_findings=tuple(FindingPayload.of(finding) for finding in library_findings),
    )


def _count(findings: Iterable[ValidationFinding], severity: Severity) -> int:
    """How many findings carry this severity.

    Counted from `finding.severity`, which ruling R13 guarantees came from the register via
    `for_code()` — `ValidationFinding` rejects a severity that disagrees with its code, so this
    cannot be a second, drifting opinion about how much a rule matters.
    """
    return sum(1 for finding in findings if finding.severity is severity)


__all__ = ["validate_library"]
