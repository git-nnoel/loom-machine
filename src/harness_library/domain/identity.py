"""Artifact identity: the string `<type>/<name>`.

Charter §7 — identity is derived from the tree, never stored. `library.yaml` keys and
`collections[].members` are written in this form, so the split has to survive a round trip;
it is implemented once, here, rather than by whoever needs it next.

Names are compared **case-sensitively** (charter §7): two artifacts differing only by case are a
validation error, not a silent overwrite, because the install target's filesystem may disagree with
this one about whether they are the same path.
"""

from __future__ import annotations

from enum import StrEnum

ID_SEPARATOR = "/"


class ArtifactType(StrEnum):
    """The kinds of thing a harness library stores. Closed."""

    SKILL = "skill"
    AGENT = "agent"


def make_artifact_id(artifact_type: ArtifactType, name: str) -> str:
    """Build the canonical `<type>/<name>` identity.

    Raises:
        ValueError: if `name` is empty or contains the separator.
    """
    if not name:
        raise ValueError("artifact name must not be empty")
    if ID_SEPARATOR in name:
        raise ValueError(f"artifact name must not contain {ID_SEPARATOR!r}: {name!r}")
    return f"{artifact_type.value}{ID_SEPARATOR}{name}"


def parse_artifact_id(value: str) -> tuple[ArtifactType, str] | None:
    """Split a `<type>/<name>` identity, or return `None` if it is not one.

    `None` rather than a raise: the caller is usually validating user-authored
    `library.yaml` data, where an unparseable id is a finding to report (V7), not a crash.
    """
    head, separator, name = value.partition(ID_SEPARATOR)
    if not separator or not name or ID_SEPARATOR in name:
        return None
    try:
        artifact_type = ArtifactType(head)
    except ValueError:
        return None
    return artifact_type, name
