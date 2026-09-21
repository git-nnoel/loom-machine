"""The manifest store — DEC-14's location, and the reader that refuses to guess.

Charter §10: this layer is tested against **real files under `tmp_path`**, never a fake
filesystem. That matters more here than anywhere else in the project, because this is the first
code that writes outside the repository: every test in this module points `state_root` at
`tmp_path`, so nothing here can reach a developer's `~/.local/state/` and nothing can reach
`~/.claude/`.

What this layer is blind to is stated once, here: it cannot see whether the digests a manifest
records match anything on a target. Comparing them is the verdict rule's (C-9, C-10) and the
scanner's (C-12), and a store test could not observe it because no target is ever scanned.

**The three behaviours this module exists for are absent, damaged and wrongly-shaped.** They are
three outcomes, not one, and the whole point of the module is that they never collapse into each
other — an absent manifest read as damaged breaks a first install, and a damaged manifest read as
absent overwrites every file the user owns.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from harness_library.domain.artifact import ArtifactFile
from harness_library.domain.errors import ErrorCode, HarnessLibraryError, ManifestError
from harness_library.domain.manifest import Manifest, ManifestArtifact, ManifestStore
from harness_library.infrastructure.manifest_store import (
    MANIFESTS_DIRECTORY_NAME,
    SCHEMA_VERSION,
    FilesystemManifestStore,
    canonical_target_path,
    default_state_root,
    manifest_path_for,
    read_manifest,
    write_manifest,
)

INSTALLED_AT = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)

SKILL_MD = ArtifactFile(path="SKILL.md", sha256="a" * 64, size=120, is_text=True)
DIAGRAM_PNG = ArtifactFile(path="references/diagram.png", sha256="b" * 64, size=4096, is_text=False)


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Where manifests live for the duration of one test. Never the real state directory."""
    return tmp_path / "state"


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """A real install target. It exists, because a user's `~/.claude` does."""
    directory = tmp_path / "target"
    directory.mkdir()
    return directory


def a_manifest(target: Path, **overrides: object) -> Manifest:
    """A valid manifest for `target`, with one field replaced."""
    fields: dict[str, object] = {
        "target_path": canonical_target_path(target),
        "installed_at": INSTALLED_AT,
        "library_git_sha": "c" * 40,
        "backup_id": "2026-09-21T14-29-00Z",
        "artifacts": (
            ManifestArtifact(
                artifact_id="skill/delivery-lead",
                content_hash="d" * 64,
                files=(SKILL_MD, DIAGRAM_PNG),
            ),
            ManifestArtifact(
                artifact_id="agent/phase-reviewer",
                content_hash="e" * 64,
                files=(
                    ArtifactFile(path="phase-reviewer.md", sha256="f" * 64, size=9, is_text=True),
                ),
            ),
        ),
    }
    fields.update(overrides)
    return Manifest(**fields)  # type: ignore[arg-type]


def put_document(target: Path, state_root: Path, text: str) -> Path:
    """Put arbitrary text where this target's manifest belongs, and return that path."""
    path = manifest_path_for(target, state_root=state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def deviate(target: Path, state_root: Path, edit: Callable[[dict[str, Any]], None]) -> Path:
    """Write a real manifest, then change one thing about the document on disk.

    Starting from a document this writer actually produced is what makes each shape test a test of
    a *deviation*: the reader is shown a manifest that differs from a good one in exactly one way,
    so a rejection cannot be the blob being unrelated to anything.
    """
    write_manifest(a_manifest(target), state_root=state_root)
    path = manifest_path_for(target, state_root=state_root)
    document = json.loads(path.read_text(encoding="utf-8"))
    edit(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------------------------------------
# Behaviour 1 — an absent manifest is "nothing installed here yet", not an error.
# ------------------------------------------------------------------------------------------------


def test_an_absent_manifest_is_nothing_installed_here_yet(target: Path, state_root: Path) -> None:
    """A first install must work. This is the test the mutation check must leave green: a reader
    that conflates "no file" with "bad file" reddens this one as well as the corrupt one."""
    assert not manifest_path_for(target, state_root=state_root).exists()

    assert read_manifest(target, state_root=state_root) is None

    # Positive control for the absence assertion above: the same reader, given a manifest, returns
    # one. So `None` here is the missing file speaking, not the reader failing to load.
    write_manifest(a_manifest(target), state_root=state_root)
    assert read_manifest(target, state_root=state_root) is not None


def test_an_absent_manifest_does_not_create_anything(target: Path, state_root: Path) -> None:
    """Reading is a read. A reader that made its own state directory would hide the distinction
    between a target never installed into and one whose manifest was deleted."""
    assert read_manifest(target, state_root=state_root) is None

    assert not state_root.exists()


# ------------------------------------------------------------------------------------------------
# Behaviour 2 — the round trip, asserted as values.
# ------------------------------------------------------------------------------------------------


def test_a_manifest_round_trips_field_by_field(target: Path, state_root: Path) -> None:
    """Written, read back, and equal **as values** — not merely parsed without complaint."""
    written = a_manifest(target)

    write_manifest(written, state_root=state_root)
    read = read_manifest(target, state_root=state_root)

    assert read is not None
    assert read.target_path == written.target_path
    assert read.installed_at == written.installed_at
    assert read.library_git_sha == written.library_git_sha
    assert read.backup_id == written.backup_id
    assert read.artifacts == written.artifacts
    assert read == written


def test_every_file_field_survives_including_a_binary_one(target: Path, state_root: Path) -> None:
    """`is_text` and `size` are what tell a later task a file is binary. Charter §7: binary is
    stored, hashed, exported and installed — so it must come back out of the record intact."""
    write_manifest(a_manifest(target), state_root=state_root)

    read = read_manifest(target, state_root=state_root)

    assert read is not None
    assert read.artifacts[0].files[1] == DIAGRAM_PNG
    assert read.artifacts[0].files[1].is_text is False
    assert read.artifacts[0].files[1].size == 4096
    assert read.artifacts[0].files[0].is_text is True


def test_both_nullable_fields_round_trip_as_null(target: Path, state_root: Path) -> None:
    """A library that is not a git work tree, and a first install that overwrote nothing."""
    written = a_manifest(target, library_git_sha=None, backup_id=None)

    write_manifest(written, state_root=state_root)
    read = read_manifest(target, state_root=state_root)

    assert read is not None
    assert read.library_git_sha is None
    assert read.backup_id is None
    assert read == written


def test_a_manifest_with_no_artifacts_is_not_an_absent_one(target: Path, state_root: Path) -> None:
    """The distinction T-18 and T-19 need: uninstalled is not never-installed."""
    write_manifest(a_manifest(target, artifacts=()), state_root=state_root)

    read = read_manifest(target, state_root=state_root)

    assert read is not None
    assert read.artifacts == ()
    # Control: the *other* target in the same state root has no manifest, and that reads as `None`.
    other = target.parent / "never-installed"
    other.mkdir()
    assert read_manifest(other, state_root=state_root) is None


def test_a_non_utc_offset_survives_the_round_trip(target: Path, state_root: Path) -> None:
    """The rule is "aware", not "UTC". An install run in Brasília records Brasília's offset."""
    installed_at = datetime(2026, 9, 21, 11, 30, tzinfo=timezone(timedelta(hours=-3)))

    write_manifest(a_manifest(target, installed_at=installed_at), state_root=state_root)
    read = read_manifest(target, state_root=state_root)

    assert read is not None
    assert read.installed_at == installed_at
    assert read.installed_at.utcoffset() == timedelta(hours=-3)


def test_the_document_on_disk_has_exactly_the_keys_this_reader_reads(
    target: Path, state_root: Path
) -> None:
    """Writer and reader are one module so a key cannot be added to one side. This asserts the
    shape they agree on, so a change to it is visible in a diff rather than only in a round trip
    that passes because both halves moved together."""
    path = write_manifest(a_manifest(target), state_root=state_root)

    document = json.loads(path.read_text(encoding="utf-8"))

    assert sorted(document) == [
        "artifacts",
        "backup_id",
        "installed_at",
        "library_git_sha",
        "schema_version",
        "target_path",
    ]
    assert document["schema_version"] == SCHEMA_VERSION
    assert sorted(document["artifacts"][0]) == ["artifact_id", "content_hash", "files"]
    assert sorted(document["artifacts"][0]["files"][0]) == ["is_text", "path", "sha256", "size"]


# ------------------------------------------------------------------------------------------------
# Behaviour 3 — a damaged manifest fails loudly, and says where.
# ------------------------------------------------------------------------------------------------


def test_a_corrupt_manifest_fails_loudly_and_names_the_line(target: Path, state_root: Path) -> None:
    """The mutation check's subject. Silently returning an empty manifest here would make a
    damaged file look like a fresh target, and the next install would judge every one of the
    user's files `CREATE` and overwrite them."""
    path = put_document(
        target,
        state_root,
        '{\n  "schema_version": 1,\n  "target_path": not-a-value\n}\n',
    )

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.code is ErrorCode.MANIFEST_UNREADABLE
    assert raised.value.line == 3
    assert raised.value.column is not None
    assert raised.value.path == str(path)
    assert f":{raised.value.line}:{raised.value.column}:" in str(raised.value)


def test_an_empty_manifest_file_is_damaged_and_not_absent(target: Path, state_root: Path) -> None:
    """A truncated write leaves a zero-byte file. That is the damaged case, not the absent one —
    the distinction the atomic write exists to make rare and this reader exists to make loud."""
    put_document(target, state_root, "")

    with pytest.raises(ManifestError):
        read_manifest(target, state_root=state_root)


def test_a_manifest_that_is_not_text_is_reported_as_that_and_not_as_a_syntax_error(
    target: Path, state_root: Path
) -> None:
    """L23: `UnicodeDecodeError` is a subclass of `ValueError`, and so is `json.JSONDecodeError`.
    A reader that caught the broad type in the wrong order would report every binary file as a
    document with a syntax error on line 1, sending the user to look at text that is not there."""
    path = manifest_path_for(target, state_root=state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00\x00not text at all")

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.code is ErrorCode.MANIFEST_UNREADABLE
    assert "UTF-8" in raised.value.reason
    assert raised.value.line is None


def test_a_document_that_is_not_an_object_names_the_document(
    target: Path, state_root: Path
) -> None:
    put_document(target, state_root, "[]\n")

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.location == "the document"
    assert "a list" in raised.value.reason


# ------------------------------------------------------------------------------------------------
# Behaviour 4 — a schema-valid but wrong-shaped manifest is also a loud failure, and names where.
# ------------------------------------------------------------------------------------------------


def _set_content_hash_to_a_number(document: dict[str, Any]) -> None:
    document["artifacts"][0]["content_hash"] = 7


def _set_a_file_size_to_a_string(document: dict[str, Any]) -> None:
    document["artifacts"][0]["files"][1]["size"] = "4096"


def _add_an_unknown_top_level_key(document: dict[str, Any]) -> None:
    document["installed_by"] = "someone"


def _add_an_unknown_artifact_key(document: dict[str, Any]) -> None:
    document["artifacts"][1]["mode"] = "0644"


def _remove_the_backup_id(document: dict[str, Any]) -> None:
    del document["backup_id"]


def _make_target_path_a_list(document: dict[str, Any]) -> None:
    document["target_path"] = ["/one", "/other"]


def _make_artifacts_null(document: dict[str, Any]) -> None:
    document["artifacts"] = None


def _make_is_text_a_number(document: dict[str, Any]) -> None:
    document["artifacts"][0]["files"][0]["is_text"] = 1


def _make_a_file_size_a_boolean(document: dict[str, Any]) -> None:
    document["artifacts"][0]["files"][0]["size"] = True


@pytest.mark.parametrize(
    ("edit", "location"),
    [
        pytest.param(_set_content_hash_to_a_number, "artifacts[0].content_hash", id="wrong-type"),
        pytest.param(_set_a_file_size_to_a_string, "artifacts[0].files[1].size", id="deep-type"),
        pytest.param(_add_an_unknown_top_level_key, "installed_by", id="unknown-key"),
        pytest.param(_add_an_unknown_artifact_key, "artifacts[1].mode", id="unknown-nested-key"),
        pytest.param(_remove_the_backup_id, "backup_id", id="missing-key"),
        pytest.param(_make_target_path_a_list, "target_path", id="list-for-a-string"),
        pytest.param(_make_artifacts_null, "artifacts", id="null-for-a-list"),
        pytest.param(_make_is_text_a_number, "artifacts[0].files[0].is_text", id="int-for-a-bool"),
        pytest.param(_make_a_file_size_a_boolean, "artifacts[0].files[0].size", id="bool-for-int"),
    ],
)
def test_a_wrong_shaped_manifest_is_refused_and_names_where(
    target: Path,
    state_root: Path,
    edit: Callable[[dict[str, Any]], None],
    location: str,
) -> None:
    """One deviation from a document this writer produced, and the error names the field.

    Asserted on `location`, not on the fact that something was raised: "it failed" would pass for
    a reader that rejected every manifest, including the good ones the round-trip tests write.

    Two of these rows are the `bool`-is-an-`int` trap in both directions: `isinstance(True, int)`
    is `True` in Python, so a reader that checked `isinstance(value, int)` alone would silently
    read `"size": true` as a one-byte file.
    """
    deviate(target, state_root, edit)

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.location == location
    assert raised.value.code is ErrorCode.MANIFEST_UNREADABLE
    assert location in str(raised.value)


def test_a_good_manifest_survives_the_same_helper(target: Path, state_root: Path) -> None:
    """Positive control for every row above: `deviate` with no deviation round-trips cleanly, so
    each rejection is the edit speaking and not the rewrite."""
    deviate(target, state_root, lambda document: None)

    assert read_manifest(target, state_root=state_root) == a_manifest(target)


def test_an_installed_at_without_an_offset_is_refused_with_its_location(
    target: Path, state_root: Path
) -> None:
    """The domain refuses a naive instant; the reader has to refuse it *with a location*, or the
    only diagnosis a user gets is a `ValueError` from a dataclass they have never heard of."""
    deviate(target, state_root, lambda d: d.__setitem__("installed_at", "2026-09-21T14:30:00"))

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.location == "installed_at"
    assert "offset" in raised.value.reason


def test_an_unparseable_installed_at_is_refused_with_its_location(
    target: Path, state_root: Path
) -> None:
    deviate(target, state_root, lambda d: d.__setitem__("installed_at", "last Tuesday"))

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.location == "installed_at"


def test_a_domain_invariant_broken_on_disk_arrives_as_a_coded_error(
    target: Path, state_root: Path
) -> None:
    """A hand-edited manifest recording one artifact twice breaks `Manifest`'s own rule. It must
    still reach the caller as `MANIFEST_UNREADABLE` with a location, not as a bare `ValueError`
    from a dataclass: this reader's whole contract is that a damaged manifest arrives coded."""

    def duplicate_the_first_artifact(document: dict[str, Any]) -> None:
        document["artifacts"].append(document["artifacts"][0])

    deviate(target, state_root, duplicate_the_first_artifact)

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.code is ErrorCode.MANIFEST_UNREADABLE
    assert "skill/delivery-lead" in str(raised.value)


def test_an_unknown_schema_version_says_so_rather_than_calling_it_corrupt(
    target: Path, state_root: Path
) -> None:
    """A manifest from a later `hl` is not damaged. Told it is, a user deletes a good file and
    hunts a bug that is not there; told the truth, they upgrade."""
    deviate(target, state_root, lambda d: d.__setitem__("schema_version", SCHEMA_VERSION + 1))

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.location == "schema_version"
    assert "not damaged" in raised.value.reason
    assert str(SCHEMA_VERSION + 1) in raised.value.reason


def test_every_way_a_manifest_can_fail_carries_one_code(target: Path, state_root: Path) -> None:
    """C-6 and C-14: one code for every unusable manifest, so `cli/` and initiative 03 each write
    one branch rather than re-deriving a taxonomy from the exception types they can see."""
    put_document(target, state_root, "{oops}")

    with pytest.raises(HarnessLibraryError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.code is ErrorCode.MANIFEST_UNREADABLE


# ------------------------------------------------------------------------------------------------
# Behaviour 5 — where the file lives. DEC-14 and R43.
# ------------------------------------------------------------------------------------------------


def test_two_targets_get_two_manifests(tmp_path: Path, state_root: Path) -> None:
    """R43: `--target PATH` accepts any directory, and the manifest is keyed by a hash of that
    path — which is what makes a second target near-free rather than a rewrite. Asserted on the
    paths, because "they round-trip separately" would also pass if both wrote the same file and
    the second simply overwrote the first."""
    first = tmp_path / "claude"
    second = tmp_path / "other-harness"
    first.mkdir()
    second.mkdir()

    first_path = manifest_path_for(first, state_root=state_root)
    second_path = manifest_path_for(second, state_root=state_root)

    assert first_path != second_path
    assert first_path.parent == second_path.parent


def test_writing_one_targets_manifest_leaves_the_others_byte_identical(
    tmp_path: Path, state_root: Path
) -> None:
    """F-13's seed at store level: two targets share one state root and do not share a record."""
    first = tmp_path / "claude"
    second = tmp_path / "other-harness"
    first.mkdir()
    second.mkdir()
    second_path = write_manifest(a_manifest(second), state_root=state_root)
    before = second_path.read_bytes()

    write_manifest(a_manifest(first, backup_id="a-different-backup"), state_root=state_root)

    assert second_path.read_bytes() == before
    first_read = read_manifest(first, state_root=state_root)
    second_read = read_manifest(second, state_root=state_root)
    assert first_read is not None
    assert second_read is not None
    assert first_read.backup_id == "a-different-backup"
    assert second_read.backup_id == "2026-09-21T14-29-00Z"


def test_every_spelling_of_one_target_reaches_one_manifest(target: Path, state_root: Path) -> None:
    """A user writes `~/.claude`, `~/.claude/` and `.` on three different days. If those keyed
    three manifests, the second install would find no record of the first and judge every file
    the first one wrote `CREATE`."""
    write_manifest(a_manifest(target), state_root=state_root)
    spellings = [
        Path(f"{target}/"),
        target / ".",
        target / "sub" / "..",
    ]

    for spelling in spellings:
        assert manifest_path_for(spelling, state_root=state_root) == manifest_path_for(
            target, state_root=state_root
        )
        assert read_manifest(spelling, state_root=state_root) is not None


def test_the_manifest_lives_outside_the_target(target: Path, state_root: Path) -> None:
    """DEC-14. Inside the target it would be a file the plan, the drift report, uninstall and
    `clean --foreign` would each have to learn to ignore — four places, four chances to forget."""
    path = write_manifest(a_manifest(target), state_root=state_root)

    assert not path.is_relative_to(target)
    assert path.parent == state_root / MANIFESTS_DIRECTORY_NAME
    assert list(target.iterdir()) == []


def test_the_writer_creates_the_state_directory(target: Path, state_root: Path) -> None:
    """A first install on a fresh machine has no `~/.local/state/harness-library` yet."""
    assert not state_root.exists()

    write_manifest(a_manifest(target), state_root=state_root)

    assert (state_root / MANIFESTS_DIRECTORY_NAME).is_dir()


def test_a_write_leaves_exactly_one_file_behind(target: Path, state_root: Path) -> None:
    """The write goes through a temporary file and `os.replace`. A leftover `.tmp` would be read
    by nobody and cleaned by nobody, and would grow one file per install forever."""
    write_manifest(a_manifest(target), state_root=state_root)
    write_manifest(a_manifest(target, backup_id="a-second-install"), state_root=state_root)

    written = sorted((state_root / MANIFESTS_DIRECTORY_NAME).iterdir())

    assert len(written) == 1
    read = read_manifest(target, state_root=state_root)
    assert read is not None
    assert read.backup_id == "a-second-install"


def test_the_default_state_root_is_dec14s_path() -> None:
    """DEC-14, computed and never created. This test touches no filesystem at all — it is the one
    place the real `~/.local/state` is named, and naming it is as far as it goes."""
    assert default_state_root().parts[-3:] == (".local", "state", "harness-library")
    assert default_state_root().is_absolute()


def test_the_manifest_is_named_for_the_target_and_not_after_it(
    target: Path, state_root: Path
) -> None:
    """The file name is a digest, so it holds no separator and no character a filesystem might
    refuse, whatever the target's depth. The full path is recorded *inside* the document."""
    path = manifest_path_for(target, state_root=state_root)

    assert path.suffix == ".json"
    assert len(path.stem) == 64
    assert target.name not in path.stem
    write_manifest(a_manifest(target), state_root=state_root)
    read = read_manifest(target, state_root=state_root)
    assert read is not None
    assert read.target_path == canonical_target_path(target)


# ------------------------------------------------------------------------------------------------
# Ruling R74 on disk, and the `ManifestStore` seam (T-16)
# ------------------------------------------------------------------------------------------------


def test_a_hand_edited_artifact_id_arrives_as_a_located_coded_error(
    target: Path, state_root: Path
) -> None:
    """**Ruling R74's whole reason for living on the entity.** `ManifestArtifact` refuses an id
    that is not `<type>/<name>`, `_build` turns that `ValueError` into a `ManifestError`, and the
    fault therefore arrives with the right code, the right exit status and the **field path**
    inside the document — none of which a guard at the join could have given it.

    Without the guard this document read back fine and blew up two layers later, in
    `application/read/drift.py`, as a bare `ValueError` with no location and no code.
    """
    deviate(target, state_root, lambda d: d["artifacts"][0].__setitem__("artifact_id", "nonsense"))

    with pytest.raises(ManifestError) as raised:
        read_manifest(target, state_root=state_root)

    assert raised.value.code is ErrorCode.MANIFEST_UNREADABLE
    assert raised.value.location == "artifacts[0]"
    assert "not a <type>/<name> identity" in str(raised.value)


def test_a_manifest_this_tool_wrote_round_trips_through_the_same_guard(
    target: Path, state_root: Path
) -> None:
    """The positive control. Every id in the fixture is well formed, so R74's guard must not be
    refusing documents this tool produces — the failure mode that would make it look correct
    while breaking every install."""
    write_manifest(a_manifest(target), state_root=state_root)

    read = read_manifest(target, state_root=state_root)

    assert read is not None
    assert [record.artifact_id for record in read.artifacts] == [
        "skill/delivery-lead",
        "agent/phase-reviewer",
    ]


def test_the_store_object_writes_where_the_function_does(target: Path, state_root: Path) -> None:
    """`FilesystemManifestStore` is the `ManifestStore` seam apply writes through — it exists
    because `application/` may not import this package and ruling R63 makes the manifest write a
    step of apply. It must land in exactly the place the function lands in, or a manifest written
    by an install would be invisible to the reader the next one uses."""
    FilesystemManifestStore(state_root).write(a_manifest(target))

    assert manifest_path_for(target, state_root=state_root).is_file()
    read = read_manifest(target, state_root=state_root)
    assert read is not None
    assert read.target_path == canonical_target_path(target)


def test_the_store_object_satisfies_the_domain_protocol() -> None:
    """Structurally, never by inheritance — the shape ruling R14 settled for C-4."""
    assert issubclass(FilesystemManifestStore, ManifestStore)
