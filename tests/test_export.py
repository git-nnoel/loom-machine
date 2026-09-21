"""Exporting a collection of the **committed fixture library**. F-16, ruling R45 — cross-layer.

The fifth cross-layer module in this suite, and it has to be, for the shape of reason
`tests/test_single_writer.py` gives. F-16's second criterion is that *a binary file round-trips
byte-identically*, and a fake library cannot prove it: the bytes a fake hands over are the bytes
the test wrote into it a line earlier, so what is really being asserted there is that a dictionary
returns what was put in it. Only a real `FilesystemArtifactRepository` over a real committed file
can show that a scan, a read and an archive together leave a PNG unchanged.

**No golden over the whole fixture** (L59). This module asserts one collection's path list and
one file's bytes; adding an artifact to the fixture library must not redden it, because the blast
radius of a fixture change is the one thing a golden over it guarantees.

Read-only: the fixture is never written to, nothing is written to `~/.claude/`, and this module
touches no `tmp_path` because an export produces bytes rather than a file.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from harness_library.application.read import export_collection
from harness_library.infrastructure.repository import FilesystemArtifactRepository
from tests.infrastructure.conftest import FIXED_TIMESTAMPS, FIXTURE_LIBRARY

COLLECTION = "housekeeping"
"""The fixture collection whose one member holds a real binary file. `library.yaml` declares it."""

MESSY_ENTRY = "skills/messy/SKILL.md"
MESSY_DIAGRAM = "skills/messy/references/diagram.png"

DIAGRAM_ON_DISK = FIXTURE_LIBRARY / "skills" / "messy" / "references" / "diagram.png"
"""The committed PNG. Read here for comparison and never written."""


@pytest.fixture
def library() -> FilesystemArtifactRepository:
    """The committed fixture library, opened over real files with R5 held still."""
    return FilesystemArtifactRepository(FIXTURE_LIBRARY, timestamps=FIXED_TIMESTAMPS)


def test_a_real_binary_file_round_trips_through_the_archive(
    library: FilesystemArtifactRepository,
) -> None:
    """**F-16's binary criterion, against a file nobody wrote in this test.**

    `skill/messy` carries a real committed PNG beside a markdown entry, and charter §7 says
    binary content is stored, hashed, exported and installed — never searched. An export that
    decoded anything would be the one place that rule failed, and it would fail silently: a
    mangled PNG is still a file of plausible length.

    The control is the entry document in the same archive: it comes back whole too, so "the
    bytes survived" is not a statement about an empty archive.
    """
    exported = export_collection(library, COLLECTION)
    archive = zipfile.ZipFile(io.BytesIO(exported.data))

    assert archive.read(MESSY_DIAGRAM) == DIAGRAM_ON_DISK.read_bytes()
    assert archive.read(MESSY_ENTRY).startswith(b"---")


def test_the_archive_holds_the_collections_files_and_nothing_the_scanner_refused(
    library: FilesystemArtifactRepository,
) -> None:
    """**The path list, against a real tree** — and the sharp half is what is *absent*.

    `skills/messy/` really contains a `node_modules/` vendor tree, a `SKILL.md.swp` editor swap
    file and a symlink resolving outside the library. The scanner refuses all three as V6
    warnings (charter §8, R6), so they are not in `Artifact.files`, so they cannot reach the
    archive — the export applies no filter of its own and needs none. A fake library could not
    show this at all, because nothing would have put them there.

    The positive control is the first assertion: the files that *should* be in the archive are,
    so "the swap file is absent" cannot mean "everything is absent".
    """
    exported = export_collection(library, COLLECTION)

    assert sorted(exported.entries) == [MESSY_ENTRY, MESSY_DIAGRAM]
    assert exported.unresolved_member_ids == ()
    assert not any("node_modules" in name for name in exported.entries)
    assert not any(name.endswith(".swp") for name in exported.entries)
    assert not any("elsewhere" in name for name in exported.entries)


def test_two_exports_of_the_committed_library_are_byte_identical(
    library: FilesystemArtifactRepository,
) -> None:
    """Determinism against a real scan, not only against a dictionary. Two repositories are
    opened, so this is two independent walks of the same tree rather than one snapshot read
    twice — which is what a caller comparing yesterday's archive with today's really does."""
    again = FilesystemArtifactRepository(FIXTURE_LIBRARY, timestamps=FIXED_TIMESTAMPS)

    assert export_collection(library, COLLECTION).data == export_collection(again, COLLECTION).data
