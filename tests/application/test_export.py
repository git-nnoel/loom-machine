"""`ExportCollection` — a curated group of artifacts as a plain zip. T-21, F-16, ruling **R45**.

Fakes only, zero disk (charter §10). The archive machinery is **real** — `zipfile` over real
bytes — so the round trip below is a round trip; what is faked is only where the bytes come from.
What this layer therefore cannot prove is that a file read off a real disk survives it, which is
`tests/test_export.py`'s job against the committed fixture's PNG.

Where the use case is **defined** is asserted in `tests/test_architecture.py`, which is the only
thing in this project that can see it: spec §5 puts an export on the read side, and
`mcp-is-read-only` stays green whichever package it sits in (T-15's mutation proved exactly that).
"""

from __future__ import annotations

import inspect
import io
import zipfile

import pytest

from harness_library.application.read import ExportedCollection, export_collection
from harness_library.domain.errors import CollectionNotFoundError, ErrorCode
from harness_library.domain.identity import ArtifactType
from harness_library.domain.metadata import Collection
from harness_library.domain.validation import ValidationCode
from tests.application.fakes import (
    FakeArtifactRepository,
    finding,
    make_artifact,
    make_file,
)

SKILL_NAME = "delivery-lead"
SKILL_ID = "skill/delivery-lead"
ENTRY = "SKILL.md"
REFERENCE = "references/checklist.md"

AGENT_NAME = "scribe"
AGENT_ID = "agent/scribe"
AGENT_ENTRY = "scribe.md"

ENTRY_BYTES = b"---\nname: delivery-lead\n---\n\n# the entry\n"
REFERENCE_BYTES = b"- one\n- two\n"
AGENT_BYTES = b"---\nname: scribe\n---\n\n# the agent\n"

DIAGRAM = "references/diagram.png"
DIAGRAM_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) + b"\x00\xff\xfe\r\n"
"""A real binary blob: a PNG signature, every byte value, and the two sequences a text round trip
mangles — a bare `\\r\\n` and bytes that are not valid UTF-8. If any layer decoded this, it would
not come back."""


def a_library() -> FakeArtifactRepository:
    """One skill of two files, one agent, and a collection naming both plus a ghost.

    The ghost is deliberate and mirrors the committed `library.yaml`: a declared member that
    resolves to nothing is a V7 ERROR and must not stop the export.
    """
    skill = make_artifact(
        SKILL_NAME,
        files=(make_file(ENTRY, ENTRY_BYTES), make_file(REFERENCE, REFERENCE_BYTES)),
    )
    agent = make_artifact(
        AGENT_NAME,
        artifact_type=ArtifactType.AGENT,
        files=(make_file(AGENT_ENTRY, AGENT_BYTES),),
    )
    return FakeArtifactRepository(
        [skill, agent],
        contents={
            (SKILL_ID, ENTRY): ENTRY_BYTES,
            (SKILL_ID, REFERENCE): REFERENCE_BYTES,
            (AGENT_ID, AGENT_ENTRY): AGENT_BYTES,
        },
        collections=[
            Collection(
                key="delivery",
                title="Delivery",
                members=(SKILL_ID, AGENT_ID, "skill/also-never-existed"),
            ),
            Collection(key="empty"),
        ],
    )


def opened(exported: ExportedCollection) -> zipfile.ZipFile:
    """The archive, as a real zip. Every assertion below reads through this, not through
    `entries` alone: `entries` is a report and the archive is the artefact."""
    return zipfile.ZipFile(io.BytesIO(exported.data))


# -------------------------------------------------------------------------------------------
# F-16 — the path list, and the binary round trip
# -------------------------------------------------------------------------------------------


def test_the_zip_holds_exactly_the_collections_files_at_their_target_paths() -> None:
    """**F-16's criterion, as a path list, and it is `==` rather than a containment.**

    Exactly, because R45 deferred the plugin format out of this initiative: there is no manifest
    inside the archive, no `library.yaml` and no directory this tool invented, and an extra entry
    is a claim about a format nobody has designed. The names are target-relative, through the
    same forward join install writes with (R73), so the archive unzips over a harness.
    """
    exported = export_collection(a_library(), "delivery")

    assert list(exported.entries) == [
        "skills/delivery-lead/SKILL.md",
        "skills/delivery-lead/references/checklist.md",
        "agents/scribe.md",
    ]
    assert opened(exported).namelist() == list(exported.entries)


def test_a_binary_file_round_trips_byte_identically() -> None:
    """**F-16's second criterion.** Charter §7: binary content is stored, hashed, exported and
    installed — never searched — so an export that decoded anything would be the one place that
    rule failed.

    The control is the text file in the same archive: it comes back whole too, so "the bytes
    survived" is not a claim about an empty archive.
    """
    skill = make_artifact(
        SKILL_NAME,
        files=(
            make_file(ENTRY, ENTRY_BYTES),
            make_file(DIAGRAM, DIAGRAM_BYTES, is_text=False),
        ),
    )
    library = FakeArtifactRepository(
        [skill],
        contents={(SKILL_ID, ENTRY): ENTRY_BYTES, (SKILL_ID, DIAGRAM): DIAGRAM_BYTES},
        collections=[Collection(key="housekeeping", members=(SKILL_ID,))],
    )

    archive = opened(export_collection(library, "housekeeping"))

    assert archive.read("skills/delivery-lead/references/diagram.png") == DIAGRAM_BYTES
    assert archive.read("skills/delivery-lead/SKILL.md") == ENTRY_BYTES


def test_a_file_kind_artifact_lands_at_its_own_path_and_not_inside_itself() -> None:
    """The join the `DIRECTORY` formula gets wrong. An agent **is** its entry document, so its
    root is `agents/scribe.md` and joining its one file onto that root would give
    `agents/scribe.md/scribe.md` — a path no archive should contain and no target could hold."""
    archive = opened(export_collection(a_library(), "delivery"))

    assert "agents/scribe.md" in archive.namelist()
    assert archive.read("agents/scribe.md") == AGENT_BYTES


def test_members_are_exported_in_declaration_order() -> None:
    """A collection is a curated sequence, exactly as `get_collection` treats it: re-sorting it
    would discard the only thing its author expressed."""
    same = a_library()
    reversed_order = FakeArtifactRepository(
        same.list_all(),
        contents=same.contents,
        collections=[Collection(key="delivery", members=(AGENT_ID, SKILL_ID))],
    )

    exported = export_collection(reversed_order, "delivery")

    assert exported.entries[0] == "agents/scribe.md"
    assert exported.entries[1:] == (
        "skills/delivery-lead/SKILL.md",
        "skills/delivery-lead/references/checklist.md",
    )


def test_two_exports_of_one_library_are_byte_identical() -> None:
    """Determinism, and it is not free: `ZipInfo` defaults its timestamp to *now*, so an archive
    built twice would differ in every entry and no caller could compare two of them.

    Each entry is stamped with the artifact's `updated_at` instead — the only instant this tool
    knows about a file (R5), deterministic for a given library state, and an honest answer to
    "when was this last changed".
    """
    library = a_library()

    assert (
        export_collection(library, "delivery").data == export_collection(library, "delivery").data
    )


# -------------------------------------------------------------------------------------------
# What is reported rather than exported
# -------------------------------------------------------------------------------------------


def test_a_member_that_resolves_to_nothing_is_reported_and_contributes_no_entry() -> None:
    """Named here as well as in the validation report (V7), because a caller showing one
    collection should not have to validate the whole library to discover that part of its
    archive is missing. A symlinked artifact root (V11) arrives the same way: the scan produced
    no artifact for it, so the collection's member resolves to nothing."""
    exported = export_collection(a_library(), "delivery")

    assert exported.unresolved_member_ids == ("skill/also-never-existed",)
    assert not any("never-existed" in name for name in exported.entries)


def test_a_collection_whose_every_member_is_missing_still_exports() -> None:
    """An empty archive is a true answer about a declared collection, and a different fact from
    the collection not existing — which the next test makes loud."""
    library = FakeArtifactRepository(
        [], collections=[Collection(key="ghosts", members=("skill/nowhere",))]
    )

    exported = export_collection(library, "ghosts")

    assert exported.entries == ()
    assert exported.unresolved_member_ids == ("skill/nowhere",)
    assert opened(exported).namelist() == []


def test_an_unknown_collection_is_refused_rather_than_exported_empty() -> None:
    """Charter §13's posture, and `get_collection`'s rule. An empty archive for an unrecognised
    key would read as "this collection is empty", which is confidently wrong.

    The positive control is in the same test: a key the library really declares exports.
    """
    library = a_library()

    with pytest.raises(CollectionNotFoundError) as refused:
        export_collection(library, "no-such-collection")

    assert refused.value.code is ErrorCode.COLLECTION_NOT_FOUND
    assert export_collection(library, "empty").entries == ()


def test_an_invalid_artifact_is_exported_like_any_other() -> None:
    """Charter §10 and feature F-2's posture. An artifact that is invisible because it is broken
    is the failure this product exists to close; an export that silently dropped one would
    reproduce it in the one place a user takes the library somewhere else."""
    broken = make_artifact(
        SKILL_NAME,
        files=(make_file(ENTRY, ENTRY_BYTES),),
        findings=(finding(ValidationCode.V2, "the frontmatter name disagrees"),),
    )
    assert not broken.is_valid
    library = FakeArtifactRepository(
        [broken],
        contents={(SKILL_ID, ENTRY): ENTRY_BYTES},
        collections=[Collection(key="delivery", members=(SKILL_ID,))],
    )

    exported = export_collection(library, "delivery")

    assert exported.entries == ("skills/delivery-lead/SKILL.md",)


def test_export_takes_no_write_lock() -> None:
    """**R82's converse, said out loud.** Every write use case takes a `WriteLock`; this is a
    read use case and takes none (R85). Reads hold their own snapshot and cannot interleave with
    anything, and a lock here would serialise the one operation that is always safe.

    Asserted on the signature rather than in prose, because "it does not take a lock" is exactly
    the kind of claim that stops being true without anything failing.
    """
    assert "lock" not in inspect.signature(export_collection).parameters
