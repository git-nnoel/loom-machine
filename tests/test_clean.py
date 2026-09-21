"""F-10's other half, against the committed fixture target — real files, real scan, real deletes.

**The third cross-layer module in this suite, and it has to be.** The criterion is that *every
path of the `synced/` tree is in the listing, with no named exclusion anywhere in the source*, and
that claim spans two layers by construction. R44's absence of an exclusion lives in
`infrastructure/target.py`'s scan — the one place a filter could be written and is not — while the
decision not to filter *afterwards* lives in `application/write/clean.py`. Neither layer alone can
witness it: at the application layer the target is a fake that is handed its entries by the test,
so a fake agreeing that `synced/` is foreign proves only that the test author said so.

Three more facts only real files can carry, and they are the ones a careless clean gets wrong:

* a foreign **directory** is never listed and never removed — `synced/` is leaves, not a tree —
  and the emptied directories are still there afterwards;
* a foreign **symlink** is unlinked as itself and never followed, so a link resolving out of the
  target does not turn this command into a delete somewhere else on the machine — and, since
  ruling R94, the backup puts it back *as a link*, which is the one thing this command's safety
  model could not do before;
* the installed files and the manifest survive a clean untouched.

So: a real `FilesystemTargetRepository`, a real `FilesystemBackupStore`, a real manifest store, a
real `FilesystemWriteLock`, a real `apply_install` and a real `clean_foreign`. The library is the
application fake, because the library side is not what is being proven here.

**Nothing writes outside `tmp_path`.** The committed fixture is copied, never written to, and
`default_state_root()` is never called.
"""

from __future__ import annotations

import ast
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness_library.application.read.drift import diff_against_target
from harness_library.application.write import (
    CleanResult,
    apply_install,
    clean_foreign,
    plan_install,
)
from harness_library.domain.identity import ArtifactType
from harness_library.domain.manifest import Manifest
from harness_library.infrastructure.backup import FilesystemBackupStore
from harness_library.infrastructure.lock import FilesystemWriteLock
from harness_library.infrastructure.manifest_store import (
    FilesystemManifestStore,
    read_manifest,
)
from harness_library.infrastructure.target import FilesystemTargetRepository
from tests.application.fakes import FakeArtifactRepository, make_artifact, make_file
from tests.infrastructure.conftest import FIXTURE_TARGET

SKILL_NAME = "delivery-lead"
AGENT_NAME = "scribe"

INSTALLED = (
    "skills/delivery-lead/SKILL.md",
    "skills/delivery-lead/references/cost-and-time.md",
    "skills/delivery-lead/references/diagram.png",
    "agents/scribe.md",
)
"""Every fixture path a library really could install, and therefore every path clean must leave.

The symlink beside them is **not** here: the library scanner never follows one (R6, charter §7),
so no artifact declares it and nothing installs it — which is precisely why it comes back
`FOREIGN` and lands in this command's listing.
"""

SYNCED_ROOT = "skills/synced"
SYNCED_MARKER = "skills/synced/.bucket-7c1f9a2e"
SYNCED_SKILL = "skills/synced/7c1f9a2e_4b0d3f61/remote-helper/SKILL.md"
SYNCED_NESTED_DIRECTORY = "skills/synced/7c1f9a2e_4b0d3f61/remote-helper"
"""The bucket is **two directories deep**, which is where a careless answer eats it: a clean that
acted on directories would take `skills/synced` whole, and one that acted on the artifact-shaped
`remote-helper` inside it would take that."""

SWAP = "skills/delivery-lead/SKILL.md.swp"
SETTINGS = "settings.json"
SYMLINK = "skills/delivery-lead/references/elsewhere.md"
"""The committed symlink, resolving **outside** the target root (R6, `tests/fixtures/README.md`).
Foreign like everything else here, and the one path whose removal could reach another directory
entirely if it were followed instead of unlinked."""

CLEANED_AT = datetime(2026, 9, 21, 20, 15, tzinfo=UTC)
"""When every run in this module happened. A parameter, never a clock."""


# -------------------------------------------------------------------------------------------
# Plumbing. It passes arguments and collects evidence; it renders no verdict (L29).
# -------------------------------------------------------------------------------------------


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Where the manifests, the backups and the sentinel go. Never `default_state_root()`."""
    return tmp_path / "state"


@pytest.fixture
def target_root(tmp_path: Path) -> Path:
    """A writable copy of the committed fixture target, with the symlink's destination beside it.

    `symlinks=True`, so the committed link is copied as a link rather than as its contents — the
    whole point of it. Its destination is four levels up from `references/`, which lands beside
    the copied target, so the file it names really exists here and "the destination is still
    there afterwards" is an assertion rather than a coincidence.
    """
    root = tmp_path / "target"
    shutil.copytree(FIXTURE_TARGET, root, symlinks=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target-escape.md").write_bytes(b"# a file outside the target entirely\n")
    assert (root / SYMLINK).is_symlink()
    return root


def a_library() -> FakeArtifactRepository:
    """A library holding exactly what the fixture target already has installed, byte for byte.

    Built from the committed tree rather than from literals, so the install below is a pure
    `MANIFEST_REPAIR` — library and target agree, no manifest records it — and writes no file.
    That leaves the fixture's bytes untouched and still gives clean a manifest to respect, which
    is the arrangement this module needs: a target where **everything installable is recorded**
    and everything else is genuinely foreign.

    The symlink is left out for the reason the library scanner leaves it out (R6): nothing
    follows one, so no artifact ever declares it.
    """
    skill_files = {
        "SKILL.md": (FIXTURE_TARGET / "skills/delivery-lead/SKILL.md").read_bytes(),
        "references/cost-and-time.md": (
            FIXTURE_TARGET / "skills/delivery-lead/references/cost-and-time.md"
        ).read_bytes(),
        "references/diagram.png": (
            FIXTURE_TARGET / "skills/delivery-lead/references/diagram.png"
        ).read_bytes(),
    }
    agent_files = {"scribe.md": (FIXTURE_TARGET / "agents/scribe.md").read_bytes()}

    skill = make_artifact(
        SKILL_NAME,
        files=tuple(make_file(path, body) for path, body in skill_files.items()),
    )
    agent = make_artifact(
        AGENT_NAME,
        artifact_type=ArtifactType.AGENT,
        files=tuple(make_file(path, body) for path, body in agent_files.items()),
    )
    return FakeArtifactRepository(
        [skill, agent],
        contents={
            **{(skill.id, path): body for path, body in skill_files.items()},
            **{(agent.id, path): body for path, body in agent_files.items()},
        },
    )


def install(library: FakeArtifactRepository, target_root: Path, state_root: Path) -> Manifest:
    """One real apply into the copied fixture, so the target has something clean must not touch."""
    target = FilesystemTargetRepository(target_root)
    apply_install(
        plan_install(library, target, manifest=None, unscannable=()),
        library,
        target,
        FilesystemBackupStore(state_root, target_root, now=lambda: CLEANED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: CLEANED_AT),
        manifest=None,
        target_path=str(target_root),
        installed_at=CLEANED_AT,
    )
    recorded = read_manifest(target_root, state_root=state_root)
    assert recorded is not None
    return recorded


def clean(
    library: FakeArtifactRepository,
    target_root: Path,
    state_root: Path,
    *,
    manifest: Manifest,
    remove: bool,
) -> CleanResult:
    """One real `clean_foreign` over `target_root`, planned from the target as it is now."""
    target = FilesystemTargetRepository(target_root)
    return clean_foreign(
        diff_against_target(library, target, manifest=manifest),
        target,
        FilesystemBackupStore(state_root, target_root, now=lambda: CLEANED_AT),
        FilesystemManifestStore(state_root),
        lock=FilesystemWriteLock(target_root, state_root=state_root, now=lambda: CLEANED_AT),
        manifest=manifest,
        installed_at=CLEANED_AT,
        remove=remove,
    )


def files_under(root: Path) -> set[str]:
    """Every file and symlink under `root`, target-relative. Directories are deliberately out."""
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }


# -------------------------------------------------------------------------------------------
# R44 — the sync bucket is listed, leaf by leaf, and removed only when asked
# -------------------------------------------------------------------------------------------


def test_every_leaf_of_the_sync_bucket_is_in_the_listing(
    target_root: Path, state_root: Path
) -> None:
    """**R44 end to end, against the committed fixture.**

    Claude Code's bucket is `skills/synced/`, two directories deep, holding a `.bucket-<uuid>`
    marker and a skill under `<uuid>_<uuid>/remote-helper/`. Neither the library nor the manifest
    knows either path, so both are `FOREIGN` and both are named — which is exactly what a named
    exclusion would have hidden, along with whatever lands there next.

    The bucket's **root** is not in the listing and must not be: C-12 reports files, and a tree
    is not a path this command acts on.
    """
    library = a_library()
    manifest = install(library, target_root, state_root)

    result = clean(library, target_root, state_root, manifest=manifest, remove=False)

    assert SYNCED_MARKER in result.listed
    assert SYNCED_SKILL in result.listed
    assert SYNCED_ROOT not in result.listed
    assert SYNCED_NESTED_DIRECTORY not in result.listed


def code_without_docstrings(module: Path) -> str:
    """One module's source with every docstring and comment removed, as text.

    `ast` drops comments on parse and this drops the docstrings — module, class, function and the
    attribute docstrings this codebase writes after almost every constant. What is left is what
    the interpreter would *act* on, which is the only place a named exclusion could live and the
    only place searching for one means anything. A prose mention of the bucket is the opposite of
    a violation: it is a module explaining why it has no exclusion.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        node.body = [  # type: ignore[attr-defined]
            statement
            for statement in body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        ] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_source_names_no_exclusion_for_the_sync_bucket() -> None:
    """**R44 as a fact about the source, because a green suite cannot say this.**

    Every test above would pass over a build that special-cased the bucket somewhere and happened
    not to reach the case. This is the assertion that the *name* is absent from anything the
    interpreter runs: no filter, no prefix test, no allow-list and no deny-list under `src/`
    mentions it. The docstrings that explain why there is no exclusion are stripped first — they
    are the reason the rule holds, not a breach of it.

    The positive control is the last assertion: the same search over the same stripped source
    finds the artifact-root prefix `skills/`, which really is in the code — so an empty result
    cannot mean the stripping removed everything.
    """
    source = Path(__file__).resolve().parent.parent / "src"
    stripped = {path: code_without_docstrings(path) for path in sorted(source.rglob("*.py"))}
    mentions = sorted(
        path.relative_to(source).as_posix() for path, code in stripped.items() if "synced" in code
    )

    assert mentions == [], (
        "ruling R44 forbids a named exclusion for Claude Code's sync bucket anywhere, and these "
        f"modules name it in code: {mentions}. The bucket is foreign like anything else the "
        "library and the manifest both disown; it is protected by the listing and the backup, "
        "never by a name — a name would hide whatever lands in that directory next"
    )
    assert any("skills" in code for code in stripped.values())


def test_the_bucket_survives_a_listing_and_goes_only_when_removal_is_asked_for(
    target_root: Path, state_root: Path
) -> None:
    """**"Removed only when asked", asserted on the files.**

    The default call lists and touches nothing — the whole structural half of "list before
    acting", and what T-22's CLI shows before it asks. The second call is the same run with the
    user's yes, and the same paths go.

    Asserted on the target's contents, never on either report: a report saying "I removed
    nothing" is exactly what a run that removed everything and lied would also say.
    """
    library = a_library()
    manifest = install(library, target_root, state_root)

    clean(library, target_root, state_root, manifest=manifest, remove=False)

    assert (target_root / SYNCED_MARKER).is_file()
    assert (target_root / SYNCED_SKILL).is_file()

    clean(library, target_root, state_root, manifest=manifest, remove=True)

    assert not (target_root / SYNCED_MARKER).exists()
    assert not (target_root / SYNCED_SKILL).exists()


# -------------------------------------------------------------------------------------------
# What a clean leaves behind — directories, links, and everything the manifest knows
# -------------------------------------------------------------------------------------------


def test_the_emptied_directories_are_left_behind(target_root: Path, state_root: Path) -> None:
    """**A foreign directory is never removed, at either depth.**

    C-12's `delete` refuses a directory and the listing never contains one, so a cleaned
    `synced/` leaves `skills/synced/` and `skills/synced/<uuid>_<uuid>/remote-helper/` standing
    and empty — visible, harmless and removable by hand. Removing them would mean deciding that
    nothing else in them matters, which is a decision this command is the least entitled to make:
    a directory that was empty a moment ago may not be by the time the removal reaches it.

    The positive control is the last assertion: the files really did go, so "the directory is
    still there" cannot mean nothing happened.
    """
    library = a_library()
    manifest = install(library, target_root, state_root)

    clean(library, target_root, state_root, manifest=manifest, remove=True)

    assert (target_root / SYNCED_ROOT).is_dir()
    assert (target_root / SYNCED_NESTED_DIRECTORY).is_dir()
    assert list((target_root / SYNCED_NESTED_DIRECTORY).iterdir()) == []


def test_a_foreign_symlink_is_unlinked_as_itself_and_its_destination_survives(
    target_root: Path, state_root: Path
) -> None:
    """R6 on the removal path. The committed link resolves **outside** the target root, so a
    clean that followed it instead of unlinking it would delete a file in a directory this tool
    was never pointed at — which is the whole reason R6 never follows one.

    Asserted on both sides: the link is gone, and the file it named is byte-identical.
    """
    library = a_library()
    manifest = install(library, target_root, state_root)
    destination = target_root.parent / "outside" / "target-escape.md"
    before = destination.read_bytes()

    result = clean(library, target_root, state_root, manifest=manifest, remove=True)

    assert SYMLINK in result.removed
    assert not (target_root / SYMLINK).is_symlink()
    assert not (target_root / SYMLINK).exists()
    assert destination.read_bytes() == before


def test_everything_the_manifest_records_survives_a_clean(
    target_root: Path, state_root: Path
) -> None:
    """The other half of the safety model: clean's list is C-9's `FOREIGN`, and an installed path
    is not one. Asserted on the installed file's **bytes** and on the record, which clean rewrites
    only to name its backup.

    The positive control is the last assertion: the run really did remove things, so "the
    installed file is still there" cannot mean this command never deletes.
    """
    library = a_library()
    manifest = install(library, target_root, state_root)
    before = {path: (target_root / path).read_bytes() for path in INSTALLED}

    result = clean(library, target_root, state_root, manifest=manifest, remove=True)

    assert {path: (target_root / path).read_bytes() for path in INSTALLED} == before
    recorded = read_manifest(target_root, state_root=state_root)
    assert recorded is not None
    assert recorded.artifacts == manifest.artifacts
    assert recorded.backup_id == result.backup_id
    assert files_under(target_root) == set(INSTALLED)


def test_a_cleaned_target_is_put_back_by_restoring_the_backup(
    target_root: Path, state_root: Path
) -> None:
    """**R88's other half: the backup is the only way back, so it has to work.**

    Nothing in this project describes a foreign path — no library, no manifest — so the copy
    taken before the first removal is the sole record of the swap file, the settings, the symlink
    and the bucket that will ever exist. Restoring it has to reproduce the whole set, and it is
    asserted per path against the set the target held before the clean ran.

    **The symlink comes back as a symlink, and that is ruling R94.** R6 forbids reading through
    a link, so no bytes are stored for one; until T-20 that meant the link was described and
    never restored, so the single most destructive thing this command does — removing a path
    this tool never wrote — was the one thing its backup could not undo. A link's content is its
    destination, the record now carries it, and `restore` recreates the link.

    Asserted on `is_symlink` and on the destination, not on the path merely existing: a regular
    file holding a copy of `target-escape.md` would satisfy "the path is back" and would be a
    different target from the one that was backed up — the user's development link silently
    replaced by a snapshot of somebody else's directory.
    """
    library = a_library()
    manifest = install(library, target_root, state_root)
    before = files_under(target_root)
    link_destination = (target_root / SYMLINK).readlink()

    result = clean(library, target_root, state_root, manifest=manifest, remove=True)
    assert result.backup_id is not None
    assert not (target_root / SYMLINK).exists(), "the clean really did remove it"

    FilesystemBackupStore(state_root, target_root, now=lambda: CLEANED_AT).restore(result.backup_id)

    assert files_under(target_root) == before
    assert (target_root / SETTINGS).read_bytes() == (FIXTURE_TARGET / SETTINGS).read_bytes()
    assert (target_root / SWAP).read_bytes() == (FIXTURE_TARGET / SWAP).read_bytes()
    assert (target_root / SYNCED_SKILL).read_bytes() == (FIXTURE_TARGET / SYNCED_SKILL).read_bytes()
    assert (target_root / SYMLINK).is_symlink()
    assert (target_root / SYMLINK).readlink() == link_destination
    assert (target_root.parent / "outside" / "target-escape.md").is_file()


def test_the_committed_fixture_target_is_untouched(target_root: Path) -> None:
    """The fixture is copied and never written to. Charter §10 keeps these trees forever, and a
    test that cleaned the committed one would delete most of them once and pass ever after."""
    assert (FIXTURE_TARGET / SYNCED_SKILL).is_file()
    assert (FIXTURE_TARGET / SYMLINK).is_symlink()
    assert (FIXTURE_TARGET / SETTINGS).is_file()
