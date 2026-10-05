"""PyYAML, quarantined behind a typed node model that remembers where things were written.

Two problems solved in one place:

**Positions.** `yaml.safe_load` returns plain Python objects and discards every position, so a
shape complaint about `tags: process` could be phrased but never *located*. `yaml.compose` stops at
the node tree, where every node still carries its `start_mark`. A diagnosis with no line number is
half of what this reader exists to deliver.

**Safety.** Ruling R1's stated concern is a loader that can construct arbitrary Python objects out
of a file that arrives from a user's repository. `compose` constructs *nothing* — it never reaches
a constructor — so it is strictly safer than `safe_load`, not a relaxation of it. A `!!python/...`
tag composes as a node whose `tag` is simply not one of the tags the reader accepts, and is
rejected as a shape error. `tests/infrastructure/test_library_yaml.py` pins that behaviour.

**Typing.** PyYAML ships no type hints, so its whole surface is `Any` under `mypy --strict`. It is
imported in this module and nowhere else; everything the reader touches is the typed model below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from loom.domain.errors import LibraryYamlError

STR_TAG = "tag:yaml.org,2002:str"
"""The tag PyYAML's safe resolver gives a plain or quoted string."""

NULL_TAG = "tag:yaml.org,2002:null"
"""The tag of `~`, `null`, and of a key written with nothing after it."""


@dataclass(frozen=True, slots=True)
class YamlScalar:
    """A leaf. `tag` is kept unresolved so the reader decides what counts as a string.

    Attributes:
        tag: the resolved YAML tag, e.g. `tag:yaml.org,2002:str`. Compared against, never trusted
        to
            be one of a known set — an explicit `!!python/...` tag reaches here verbatim and must
            fail the reader's checks rather than be assumed away.
        value: the raw text of the scalar.
    """

    line: int
    column: int
    tag: str
    value: str

    @property
    def is_null(self) -> bool:
        """Whether this is `~`, `null`, or a key written with nothing after it."""
        return self.tag == NULL_TAG

    @property
    def is_string(self) -> bool:
        """Whether this resolved to a plain string. `2024` and `true` do not."""
        return self.tag == STR_TAG


@dataclass(frozen=True, slots=True)
class YamlSequence:
    """A `[a, b]` or a `- a` block."""

    line: int
    column: int
    items: tuple[YamlNode, ...]


@dataclass(frozen=True, slots=True)
class YamlMapping:
    """A `key: value` block.

    Pairs, not a dict: the reader needs each key's own position to complain about it, and a dict
    would also silently drop a duplicate key.
    """

    line: int
    column: int
    pairs: tuple[tuple[YamlNode, YamlNode], ...]


YamlNode = YamlScalar | YamlSequence | YamlMapping


def compose_document(text: str, *, path: Path) -> YamlNode | None:
    """Parse `text` into the typed node model.

    Returns:
        The root node, or `None` when the document is empty — an empty file declares nothing, which
        is not the same as a file that could not be parsed.

    Raises:
        LibraryYamlError: the text is not a single well-formed YAML document. Carries the line and
            column PyYAML reported.
    """
    try:
        root: Any = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        line, column = _position_of(error)
        raise LibraryYamlError(
            _reason_of(error), path=str(path), line=line, column=column
        ) from error
    if root is None:
        return None
    return _convert(root)


def _convert(node: Any) -> YamlNode:
    """Turn one PyYAML node into the typed model, recursively.

    `Any` in, typed out: this is the boundary of the quarantine.
    """
    line = int(node.start_mark.line) + 1
    column = int(node.start_mark.column) + 1
    if isinstance(node, yaml.MappingNode):
        pairs = tuple((_convert(key), _convert(value)) for key, value in node.value)
        return YamlMapping(line=line, column=column, pairs=pairs)
    if isinstance(node, yaml.SequenceNode):
        return YamlSequence(
            line=line, column=column, items=tuple(_convert(item) for item in node.value)
        )
    return YamlScalar(line=line, column=column, tag=str(node.tag), value=str(node.value))


def _position_of(error: Any) -> tuple[int | None, int | None]:
    """The 1-based position PyYAML attached to a parse failure, if it attached one.

    `problem_mark` is where the parser gave up; `context_mark` is where the construct it was in
    began. The problem is the more useful of the two, so it wins. A `YAMLError` that is not a
    `MarkedYAMLError` — a reader-level failure — carries neither, and the position is genuinely
    unknown rather than guessed.
    """
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    if mark is None:
        return None, None
    return int(mark.line) + 1, int(mark.column) + 1


def _reason_of(error: Any) -> str:
    """PyYAML's own words for the failure, without the position it repeats in its `str()`."""
    problem = getattr(error, "problem", None)
    if problem:
        context = getattr(error, "context", None)
        if context:
            return f"{context}, {problem}"
        return str(problem)
    return str(error).replace("\n", " ").strip()
