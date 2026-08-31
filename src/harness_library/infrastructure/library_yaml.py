"""The `library.yaml` reader.

This is the only place a user's hand-authored metadata enters the system, so it is the only place a
typo can be caught with a line number instead of turned into a silent wrong answer. Every
downstream consumer — the tag filter, the collections view, the supersession ranking — trusts
whatever this returns, so the reader is loud by default: an unknown key, a value of the wrong type
or a file that does not parse is a hard failure carrying a location, never a quietly-empty result.

**The seam this reader does not cross.** It validates *shape* — is this parseable YAML, are these
the right types, is this key well-formed. It does **not** validate *resolution*: whether
`skill/delivery-lead` names an artifact that exists on disk is rule V7, and belongs to the
assembler, which sees the whole library at once. Producing a `LibraryMetadata` that names an
artifact which does not exist is correct behaviour here. For the same reason the reader does not
check that a key parses as `<type>/<name>` — `parse_artifact_id` returns `None` for exactly that
case so V7 can report it.

**Where V9 falls on that seam.** A duplicate key is neither: the document parses, and both blocks
are fully understood. So it is neither a raise nor a resolution question — the reader *records* each
repeat as a `DuplicateKey` and the assembler turns it into a V9 ERROR finding, the same division of
labour V6 already uses between the scanner and the assembler. Raising instead would report the
duplicate and nothing else about the library, and would leave a rule in charter §8's register that
can never make `is_valid` false.

**Absent, empty, and malformed are three different things.**

* **Absent** — no `library.yaml` at all. `LibraryMetadata.empty()`. A library that declares no
  metadata is a valid library, not a broken one.
* **Empty** — the file exists and declares nothing (`""`, `~`, `artifacts:` with nothing under it).
  Also `LibraryMetadata.empty()`; the author said "nothing" and meant it.
* **Malformed** — the file exists and cannot be used. `LibraryYamlError`, with the line. Returning
  empty metadata here would make a typo look like "the user has no tags", which is the failure mode
  this product exists to eliminate rather than reproduce.

**A null-valued key is the empty form of its type.** `tags:` with nothing after it yields no tags,
`superseded_by:` yields `None`, an entry `skill/foo:` yields the empty declaration. YAML's only
idiom for "nothing here" is a bare key, so rejecting it would fail a file whose meaning is
unambiguous. What null never does is become a *non-empty* value: `tags:` is an empty tuple, never a
one-element tuple holding `None`.
"""

from __future__ import annotations

from pathlib import Path

from harness_library.domain.errors import LibraryYamlError
from harness_library.domain.metadata import (
    ArtifactMetadata,
    Collection,
    DuplicateKey,
    LibraryMetadata,
)
from harness_library.infrastructure._yaml_document import (
    YamlMapping,
    YamlNode,
    YamlScalar,
    YamlSequence,
    compose_document,
)

LIBRARY_YAML_FILENAME = "library.yaml"
"""The name of the metadata file, relative to the library root. Spec §3.4."""

_ARTIFACTS_KEY = "artifacts"
_COLLECTIONS_KEY = "collections"

_TOP_LEVEL_KEYS = (_ARTIFACTS_KEY, _COLLECTIONS_KEY)
_ARTIFACT_KEYS = ("tags", "superseded_by")
_COLLECTION_KEYS = ("title", "description", "members")


def read_library_metadata(library_root: Path) -> LibraryMetadata:
    """Read `<library_root>/library.yaml` into `LibraryMetadata`.

    Args:
        library_root: the library's root directory.

    Returns:
        What the file declares, or `LibraryMetadata.empty()` when there is no file to read. Ids
        named here are **not** checked against the tree; that is V7's job.

    Raises:
        LibraryYamlError: the file exists but cannot be used — unparseable YAML, an unknown key, or
        a
            value of the wrong type. Carries a line number wherever the failure has a position,
            which is every case except a file that cannot be decoded at all.
    """
    path = library_root / LIBRARY_YAML_FILENAME
    if not path.exists():
        return LibraryMetadata.empty()

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise LibraryYamlError(
            f"{LIBRARY_YAML_FILENAME} is not valid UTF-8 text", path=str(path)
        ) from error
    except OSError as error:
        raise LibraryYamlError(
            f"{LIBRARY_YAML_FILENAME} exists but could not be read: {error.strerror or error}",
            path=str(path),
        ) from error

    root = compose_document(text, path=path)
    if root is None:
        return LibraryMetadata.empty()
    return _read_document(root, path=path)


def _read_document(root: YamlNode, *, path: Path) -> LibraryMetadata:
    """Interpret the root node. The document is a mapping of two optional keys.

    Duplicate keys are collected **after** interpretation, so a document that is genuinely unusable
    still raises with its line exactly as it did before — a duplicate is a fault worth reporting,
    not a reason to stop reading.
    """
    artifacts: dict[str, ArtifactMetadata] = {}
    collections: list[Collection] = []

    for key, value in _mapping_pairs(root, what="the document", path=path):
        name = _key_name(key, allowed=_TOP_LEVEL_KEYS, within="the document", path=path)
        if name == _ARTIFACTS_KEY:
            artifacts = _read_artifacts(value, path=path)
        else:
            collections = _read_collections(value, path=path)

    return LibraryMetadata(
        artifacts=artifacts,
        collections=tuple(collections),
        duplicate_keys=_collect_duplicate_keys(root),
    )


def _read_artifacts(node: YamlNode, *, path: Path) -> dict[str, ArtifactMetadata]:
    """`artifacts:` — a mapping of `<type>/<name>` id to what the library declares about it."""
    artifacts: dict[str, ArtifactMetadata] = {}
    for key, value in _mapping_pairs(node, what=f"{_ARTIFACTS_KEY!r}", path=path):
        artifact_id = _string(key, what=f"an {_ARTIFACTS_KEY} key", path=path)
        artifacts[artifact_id] = _read_artifact(value, artifact_id=artifact_id, path=path)
    return artifacts


def _read_artifact(node: YamlNode, *, artifact_id: str, path: Path) -> ArtifactMetadata:
    """One entry under `artifacts:`.

    A null entry declares nothing, which is a value and not an error.
    """
    within = f"{artifact_id!r}"
    tags: tuple[str, ...] = ()
    superseded_by: str | None = None

    for key, value in _mapping_pairs(node, what=within, path=path):
        name = _key_name(key, allowed=_ARTIFACT_KEYS, within=within, path=path)
        if name == "tags":
            tags = _string_list(value, what=f"'tags' of {within}", path=path)
        else:
            superseded_by = _optional_string(value, what=f"'superseded_by' of {within}", path=path)

    return ArtifactMetadata(tags=tags, superseded_by=superseded_by)


def _read_collections(node: YamlNode, *, path: Path) -> list[Collection]:
    """`collections:` — a mapping of collection key to its title, description and members."""
    collections: list[Collection] = []
    for key, value in _mapping_pairs(node, what=f"{_COLLECTIONS_KEY!r}", path=path):
        collection_key = _string(key, what=f"a {_COLLECTIONS_KEY} key", path=path)
        if not collection_key:
            raise LibraryYamlError(
                "a collection key must not be empty",
                path=str(path),
                line=key.line,
                column=key.column,
            )
        collections.append(_read_collection(value, key=collection_key, path=path))
    return collections


def _read_collection(node: YamlNode, *, key: str, path: Path) -> Collection:
    """One entry under `collections:`."""
    within = f"collection {key!r}"
    title: str | None = None
    description: str | None = None
    members: tuple[str, ...] = ()

    for name_node, value in _mapping_pairs(node, what=within, path=path):
        name = _key_name(name_node, allowed=_COLLECTION_KEYS, within=within, path=path)
        if name == "title":
            title = _optional_string(value, what=f"'title' of {within}", path=path)
        elif name == "description":
            description = _optional_string(value, what=f"'description' of {within}", path=path)
        else:
            members = _string_list(value, what=f"'members' of {within}", path=path)

    return Collection(key=key, members=members, title=title, description=description)


# ------------------------------------------------------------------------------------------------
# V9 — duplicate keys, observed and recorded, never decided here.
# ------------------------------------------------------------------------------------------------


def _collect_duplicate_keys(root: YamlNode) -> tuple[DuplicateKey, ...]:
    """Every key this document declares twice, in the order the repeats appear.

    This is the whole reason R16 keeps the reader on `yaml.compose` rather than `yaml.safe_load`:
    the composed tree keeps `YamlMapping.pairs` as a *list*, so both declarations are still visible.
    `safe_load` would have collapsed them into a dict before this function could look, and the first
    block's tags would vanish with no diagnostic — the precise silent-data-loss failure charter §8
    added V9 to close.

    Every mapping in the document is checked, not only `artifacts:` and `collections:`. Charter §8
    heads the rule "a duplicate key in `library.yaml`"; a repeated artifact id and a repeated
    collection key are its two named instances, and a `tags:` written twice inside one entry
    discards a block just as silently. Deciding severity or wording is not this function's
    job — see `DuplicateKey`.
    """
    found: list[DuplicateKey] = []
    _walk_for_duplicates(root, context=(), found=found)
    return tuple(found)


def _walk_for_duplicates(
    node: YamlNode, *, context: tuple[str, ...], found: list[DuplicateKey]
) -> None:
    """Depth-first over the node tree, recording repeats as they are met."""
    if isinstance(node, YamlSequence):
        for item in node.items:
            _walk_for_duplicates(item, context=context, found=found)
        return
    if not isinstance(node, YamlMapping):
        return

    first_line_of: dict[str, int] = {}
    for key, value in node.pairs:
        name = key.value if isinstance(key, YamlScalar) else None
        if name is not None:
            first_line = first_line_of.get(name)
            if first_line is None:
                first_line_of[name] = key.line
            else:
                found.append(
                    DuplicateKey(key=name, line=key.line, first_line=first_line, context=context)
                )
        nested = (*context, name) if name is not None else context
        _walk_for_duplicates(value, context=nested, found=found)


# ------------------------------------------------------------------------------------------------
# Shape helpers. Each returns the value or raises with a location; none of them coerce.
# ------------------------------------------------------------------------------------------------


def _mapping_pairs(
    node: YamlNode, *, what: str, path: Path
) -> tuple[tuple[YamlNode, YamlNode], ...]:
    """The pairs of a mapping. A null node is an empty mapping; anything else is a shape error."""
    if isinstance(node, YamlMapping):
        return node.pairs
    if isinstance(node, YamlScalar) and node.is_null:
        return ()
    raise LibraryYamlError(
        f"{what} must be a mapping of keys to values, but is {_describe(node)}",
        path=str(path),
        line=node.line,
        column=node.column,
    )


def _key_name(node: YamlNode, *, allowed: tuple[str, ...], within: str, path: Path) -> str:
    """A known key, or a located complaint.

    An unknown key is an error rather than something ignored: `tag:` for `tags:` and `member:` for
    `members:` are exactly how a user's metadata vanishes with no explanation.
    """
    name = _string(node, what=f"a key of {within}", path=path)
    if name not in allowed:
        raise LibraryYamlError(
            f"{name!r} is not a key of {within}; expected one of {', '.join(allowed)}",
            path=str(path),
            line=node.line,
            column=node.column,
        )
    return name


def _string(node: YamlNode, *, what: str, path: Path) -> str:
    """A required string. `2024` and `true` are not strings — quote them or fix them."""
    if isinstance(node, YamlScalar) and node.is_string:
        return node.value
    raise LibraryYamlError(
        f"{what} must be a string, but is {_describe(node)}",
        path=str(path),
        line=node.line,
        column=node.column,
    )


def _optional_string(node: YamlNode, *, what: str, path: Path) -> str | None:
    """A string, or `None` for a key written with nothing after it."""
    if isinstance(node, YamlScalar) and node.is_null:
        return None
    return _string(node, what=what, path=path)


def _string_list(node: YamlNode, *, what: str, path: Path) -> tuple[str, ...]:
    """A list of strings, in declaration order.

    A null node is the empty list. A **scalar is not silently promoted to a one-item list** — that
    is the `tags: process` case, and quietly accepting it would teach the file a second syntax that
    only this reader understands, so it is diagnosed with the line and the correction.
    """
    if isinstance(node, YamlScalar):
        if node.is_null:
            return ()
        raise LibraryYamlError(
            f"{what} must be a list of strings, but is a single value; "
            f"write it as a list, e.g. [{node.value}]",
            path=str(path),
            line=node.line,
            column=node.column,
        )
    if not isinstance(node, YamlSequence):
        raise LibraryYamlError(
            f"{what} must be a list of strings, but is {_describe(node)}",
            path=str(path),
            line=node.line,
            column=node.column,
        )
    return tuple(_string(item, what=f"every entry of {what}", path=path) for item in node.items)


def _describe(node: YamlNode) -> str:
    """How to name a node in a complaint aimed at whoever wrote the file, not at a Python reader."""
    if isinstance(node, YamlMapping):
        return "a mapping"
    if isinstance(node, YamlSequence):
        return "a list"
    if node.is_null:
        return "empty"
    return f"a single value ({node.value!r})"
