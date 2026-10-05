"""Contract C-13 on disk — where a backup goes, and what restoring one means.

**Under the state root, beside the manifests, outside every tree it describes.** DEC-14 put the
manifest there for three reasons and all three apply here harder. Inside the target, a backup is
destroyed by the wipe it exists to recover from and has to be hidden from the plan, the drift
report, uninstall and `clean --foreign` — four places that would each have to remember. Inside the
library it is committed, and `git clean` takes it. Outside both, neither can reach it.

```
<state_root>/backups/<backup_id>/
    backup.json          the record: id, when, which target, which paths, which bytes were kept
                         and at which mode, and which paths were links and where they pointed
    files/<path>         the bytes of every path the target actually held, each one 0600
```

**Which paths the backup kept bytes for is recorded, not inferred — ruling R92, amending C-13.**
T-16 inferred it from the tree, on the argument that two spellings of one fact drift. The
argument was right about drift and wrong about which risk was larger: with only the tree to read,
`files/<path>` *removed after the fact* — a stray `rm`, a half-cleaned state directory, a
filesystem repair — is indistinguishable from a path that was never there, and the restore
**deletes** a file the user still has. Silently: no error, no report, no code.

So `backup.json` carries `kept`, and the two documents are checked against each other before a
restore moves a byte. A path in `kept` with no bytes is a damaged backup and the whole restore is
refused; a path outside `kept` was absent and is removed, exactly as R79 requires. The
duplication is the mechanism: the record is the claim, the tree is the evidence, and a backup is
trustworthy exactly as far as the two agree.

**`backup.json` is written last, and its presence is what makes a backup complete.** A `create`
killed halfway leaves a directory of files and no record; `list()` passes over it, and `restore`
refuses it. That is the opposite posture to `read_manifest`, which is loud about a damaged
document, and the difference is what each failure costs: a damaged manifest read as empty
overwrites every file a user owns, while a half-written backup offered for restore would put half
a target back — and one skipped from a listing costs only a rollback point that was never whole.

**A symlink is recorded as its destination — ruling R94, amending C-13.** T-19 found that
`create` simply could not take one: the copy went through `read_bytes`, which refuses a link
(R6), so `clean --foreign` over a real target raised an uncoded `ValueError` part-way through.
The workaround described the link, stored nothing and therefore **removed it and never put it
back** — a hole in the one command whose entire safety model is this store.

A link's content *is* its destination: a short string, which belongs in the record beside the
other claims rather than in the file tree. `restore` recreates the link with that exact text, so
what comes back is a link and not a copy of what it pointed at. The alternative — following it —
would put content from outside the target into a backup of the target and then materialise it as
a regular file, which is the escape R6 exists to prevent reached through the undo mechanism.

**A mode is recorded and put back — ruling R110, amending C-13.** T-23 found that a restored
file came back at `0644` whatever it had been: on the real harness, 149 private files made
world-readable and 56 executables disarmed, by the *recovery* path, with the content
byte-identical so that every digest-based check said it had worked. The mode was gone before
`restore` ran — the copy went through `write`, which applies R56's `0644` to a file this tool did
not create — so `create` now reads the source mode into `BackupRecord.modes` and `restore` writes
through `write_with_mode`. **R56 is unchanged for an install**; the distinction between the two is
the fix.

**The target is reached through `FilesystemTargetRepository`, never through `Path` directly.** The
three-stage path safety, the refusal to follow a symlink and the `0644`/`0755` modes of R56 all
live there, and a second implementation of any of them here would be a second answer to "may this
path be written". The backup's own `files/` directory is read and written through the same class
for the same reason: it is a directory of content addressed by relative path, which is exactly
what that repository is.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loom.domain.backup import BackupRecord
from loom.infrastructure.manifest_store import canonical_target_path
from loom.infrastructure.target import FilesystemTargetRepository

BACKUPS_DIRECTORY_NAME = "backups"
"""The directory holding one subdirectory per backup, under the state root. Beside `manifests/`."""

RECORD_FILENAME = "backup.json"
"""The record, written last. Its presence is what makes a backup complete."""

FILES_DIRECTORY_NAME = "files"
"""Where the saved bytes go, under each backup, mirroring the target's own layout."""

BACKUP_FILE_MODE = 0o600
"""The mode every copy under `files/` is written with. Ruling R110, the second half.

**A backup holds whatever the target held**, and on a real harness that includes a credentials
document, a control key and every session transcript. Written through `write` it took R56's
`0644`, so `clean --foreign --remove` published 149 private files into the state root before a
restore was ever asked for — the same exposure as the one D-2 named, one directory away.

`0600` rather than the source's own mode, deliberately: the record is what a restore reads the
mode from, so the copy does not have to carry it, and a source mode of `0000` or `0200` copied
faithfully would make the backup unreadable by the restore that has to read it back.
"""

SCHEMA_VERSION = 4
"""The version of the on-disk record. **4 since ruling R110 added `modes`**; 3 was R94's `links`
and 2 was R92's `kept`.

The same reasoning as the manifest's: this reader rejects nothing it does not understand loudly,
so without a version a record written by a later `loom` would be indistinguishable from a damaged
one. A backup is regenerated by the next install, so a version this build does not read is a cheap
failure — but it should still be a legible one.

**An older backup is therefore not offered**, and that is the answer to "what does reading a
pre-amendment backup do". `_read_record` passes over it, `list()` omits it and `restore` refuses
it with `KeyError`, which `rollback_install` reports as `BackupNotFoundError`.

R92 argued this for version 1 — reading the old record and inferring `kept` from the `files/`
tree would carry forward the exact indistinguishability it exists to close — and version 2 is
turned away for the plainer reason that this reader has one version. A version-2 record could in
principle be read with `links = {}`, which is a true statement about it, but it would be a second
code path through the one document whose job is to be trustworthy, in order to preserve a rollback
point on a tool that has not shipped. A backup is regenerated by the next install.

**Version 3 is turned away on R92's own argument, not on version 2's.** Reading one with
`modes = {}` is not a true statement about it: every path it kept had a mode, and the record
simply did not write one down. `BackupRecord` refuses that record outright — `modes` is total
over `kept` — and the alternative, defaulting each one to `0644`, is the defect R110 closes,
performed by the code that closes it. A rollback point written by a build that lost the mode is
not a rollback point worth offering.
"""

_ENCODING = "utf-8"

_ID_FORMAT = "%Y-%m-%dT%H-%M-%SZ"
"""How a backup id spells the instant it was taken.

Colons are not in it because a backup id is a directory name and Windows will not have one; the
shape matches the `backup_id` C-11 already carries as an example. Opaque to every consumer —
`BackupRecord.created_at` is the value anything sorting or displaying a backup reads.
"""


def default_backups_root(state_root: Path) -> Path:
    """Where backups live under a state root. Computes; never creates."""
    return state_root / BACKUPS_DIRECTORY_NAME


class FilesystemBackupStore:
    """Backups of one install target, under one state root. Implements contract C-13.

    The protocol stays in `domain/backup.py` and is satisfied structurally — this class does not
    inherit it — which is the shape ruling R14 settled for C-4 and C-12 keeps.

    Attributes are all injected, and the clock among them: `created_at` is read from disk in a
    listing and compared in a test, so a store that reached for `datetime.now` internally would
    make every assertion about ordering depend on how fast the suite ran.
    """

    def __init__(
        self,
        state_root: Path,
        target_root: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Open the backup store for one target.

        Args:
            state_root: the directory backups live under, beside the manifests.
                `manifest_store.default_state_root()` in production, `tmp_path` in every test.
            target_root: the install target these backups are of. Must exist — ruling R71 keeps
                the decision to create a target in the composition root (T-22), and a backup store
                that created one as a side effect of being built would take that decision away.
            now: the clock. Defaults to the real one; a test passes a fixed instant.

        Raises:
            FileNotFoundError: `target_root` is not a directory.
        """
        self._root = default_backups_root(state_root)
        self._target = FilesystemTargetRepository(target_root)
        self._target_path = canonical_target_path(target_root)
        self._now = now if now is not None else (lambda: datetime.now(UTC))

    # -- Contract C-13 ---------------------------------------------------------------------------

    def create(self, paths: tuple[str, ...]) -> str:
        """Copy every path the target holds bytes for, record every path asked for, return the id.

        The two are deliberately different sets, and **the record now says which is which**
        (R92). A path the target does not hold — everything a `CREATE` is about to write — is
        recorded in `paths`, left out of `kept` and stored nowhere, so `restore` removes it and a
        first install is undoable like any other.

        **A symlink is the third case, and since ruling R94 it is kept too** — as its
        destination rather than as bytes. This store may not read through a link (R6, and
        `FilesystemTargetRepository.read_bytes` refuses one outright), so nothing lands under
        `files/` for it; the raw text it names goes in `links`, and `restore` recreates the link
        from that. T-19 found the case and could only describe it: the link went in `paths`,
        outside `kept`, with nothing stored — so a restore removed it and never put it back,
        which made `clean --foreign` un-undoable for exactly the kind of path a user creates on
        purpose. Before that workaround the read raised a bare `ValueError` part-way through a
        copy.

        Raises:
            OSError: the backup directory could not be made, or a path could not be copied. The
                caller refuses the whole install on it (F-9); see `domain/backup.py`.
        """
        created_at = self._now()
        directory = self._reserve(created_at)
        saved = directory / FILES_DIRECTORY_NAME
        saved.mkdir(parents=True, exist_ok=True)
        into = FilesystemTargetRepository(saved)

        # One scan, through C-12's own member rather than a second `Path.is_symlink` here: the
        # decision "is this a link" belongs to the repository that already refuses to read one,
        # and a second answer to it in this module is the drift the module docstring warns about.
        linked = {file.path for file in self._target.scan() if file.is_symlink}

        kept: list[str] = []
        links: dict[str, str] = {}
        modes: dict[str, int] = {}
        for path in paths:
            if path in linked:
                links[path] = self._target.read_link(path)
            elif self._target.exists(path):
                # The mode is read **before** the copy, off the file the record is about. After
                # it, the only mode anywhere is the copy's, which is this store's and not the
                # user's — which is exactly how it was lost before ruling R110.
                modes[path] = self._target.read_mode(path)
                into.write_with_mode(path, self._target.read_bytes(path), BACKUP_FILE_MODE)
                kept.append(path)

        record = BackupRecord(
            backup_id=directory.name,
            created_at=created_at,
            target_path=self._target_path,
            paths=tuple(paths),
            # Appended as each copy succeeds rather than computed from a second `exists` pass:
            # the claim `restore` checks has to be about the bytes that really landed, and a
            # second walk of the target could answer about a file that moved in between.
            kept=tuple(kept),
            links=links,
            modes=modes,
        )
        # Last, and only now: an interrupted copy leaves a directory with no record, which
        # `list` passes over and `restore` refuses rather than putting half a target back.
        self._write_record(directory, record)
        return record.backup_id

    def restore(self, backup_id: str) -> None:
        """Put every path this backup describes back as it was, and touch nothing else.

        **The record decides, and the tree has to agree with it** (R92). A path in `kept` is
        written back from the bytes under `files/`; a path in `links` is recreated as a symlink
        naming what it named before (R94); a path in neither was absent when the backup was
        taken, so putting the target back means removing it again (R79). A path in `kept` whose
        bytes are *gone* is none of the three, and is the case this ordering exists for: it is a
        damaged backup, and acting on it would delete a file the record never claimed was absent.

        **A restored link is a link**, with the same raw destination. Writing back a copy of what
        it pointed at would silently replace the user's development link with a snapshot of
        somebody else's directory, which is a different target from the one that was backed up.

        Raises:
            KeyError: no complete backup has this id. A directory with no readable record is not
                a backup, and — since R92 — neither is one whose record claims bytes the store no
                longer holds. **Checked before the first path moves**, unlike an unreadable
                `files/<path>`, which surfaces as `OSError` part-way through: a restore that
                cannot finish is recoverable by restoring again, and a restore that acts on a
                record it has already caught lying is not recoverable at all.
            OSError: the target could not be written.
        """
        directory = self._root / backup_id
        record = self._read_record(directory)
        if record is None:
            raise KeyError(f"no backup {backup_id!r} in {self._root}")

        held = self._bytes_of(directory, record)
        kept = set(record.kept)

        for path in record.paths:
            destination = record.links.get(path)
            if destination is not None:
                # A link, put back as a link. `write_link` replaces whatever is at the path now,
                # including a regular file a clean-and-reinstall left there.
                self._target.write_link(path, destination)
            # `held is not None` cannot fail while `path in kept`: `_bytes_of` refuses a record
            # claiming any kept bytes it cannot find, so a `None` here means `kept` is empty. It
            # is written as a condition rather than an assertion because that is the narrowing
            # mypy can see, and a narrowing the type checker performs cannot rot.
            elif held is not None and path in kept:
                # **`write_with_mode` and never `write`** — ruling R110. `write` ends at R56's
                # `0644`, which is right for an artifact this tool installs and wrong for a file
                # it is putting back: it publishes a `0600` credentials document and disarms a
                # `0700` hook, while the bytes compare identical and every digest says the
                # restore worked. `modes` is total over `kept` (C-13), so the lookup is a
                # lookup and not a guess.
                self._target.write_with_mode(path, held.read_bytes(path), record.modes[path])
            elif self._target.exists(path):
                # Absent when the backup was taken, so putting the target back means removing it.
                self._target.delete(path)

    def _bytes_of(self, directory: Path, record: BackupRecord) -> FilesystemTargetRepository | None:
        """The backup's `files/` tree, having checked it holds everything the record claims.

        Refuses a record whose `kept` names bytes the tree no longer holds.

        The whole of ruling R92's protection, and it is one comparison. Before it, the two
        documents were one — "no bytes under `files/`" *meant* "absent when the backup was taken"
        — so a deleted byte-file made the restore delete a live target path with nothing to
        report. Now the record says what should be there, and a disagreement is a fault.

        Raises:
            KeyError: spelled as "this is not a complete backup", which is what it is and what
                the store already answers for a directory with no record at all. The remedy is
                the same — go and look at where backups live — so `rollback_install` maps it to
                `BackupNotFoundError` and needs no second code.
        """
        saved = directory / FILES_DIRECTORY_NAME
        held = FilesystemTargetRepository(saved) if saved.is_dir() else None
        missing = sorted(path for path in record.kept if held is None or not held.exists(path))
        if missing:
            raise KeyError(
                f"backup {record.backup_id!r} in {self._root} is not complete: it records bytes "
                f"for {missing} and no longer holds them. Restoring it would remove those paths "
                "from the target as though they had been absent when it was taken (R92), so it "
                "is refused instead and nothing has been changed"
            )
        return held

    def list(self) -> tuple[BackupRecord, ...]:
        """Every complete backup under this state root, oldest first.

        **Every backup, not only this target's.** One state root holds the backups of every target
        a user has installed into (R43), and a listing that silently hid the others would make
        "where did my backup go" unanswerable from the tool. `BackupRecord.target_path` is what a
        caller filters on, and it is there so that it can.
        """
        if not self._root.is_dir():
            return ()
        records = [
            record
            for directory in sorted(self._root.iterdir())
            if (record := self._read_record(directory)) is not None
        ]
        records.sort(key=lambda record: (record.created_at, record.backup_id))
        return tuple(records)

    # -- The on-disk record ----------------------------------------------------------------------

    def _reserve(self, created_at: datetime) -> Path:
        """Make this backup's directory, giving it a name no existing backup has.

        Two installs in one second are not a race this tool needs to win — charter §12 keeps a
        single writer (R50) — but they are entirely possible in a test and in a script, and a
        second backup silently overwriting the first would destroy the copy the first one was
        protecting. The suffix is a count, not a random value, so the name stays readable.
        """
        stem = created_at.strftime(_ID_FORMAT)
        self._root.mkdir(parents=True, exist_ok=True)
        candidate = self._root / stem
        attempt = 1
        while candidate.exists():
            attempt += 1
            candidate = self._root / f"{stem}-{attempt}"
        candidate.mkdir()
        return candidate

    def _write_record(self, directory: Path, record: BackupRecord) -> None:
        """Write `backup.json`. Not atomic, because its presence is the completeness marker.

        A half-written record fails to parse, which `_read_record` answers `None` to — the same
        outcome as no record at all, and the same outcome the partial copy above deserves.
        """
        document = {
            "schema_version": SCHEMA_VERSION,
            "backup_id": record.backup_id,
            "created_at": record.created_at.isoformat(),
            "target_path": record.target_path,
            "paths": list(record.paths),
            "kept": list(record.kept),
            "links": dict(record.links),
            "modes": dict(record.modes),
        }
        (directory / RECORD_FILENAME).write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding=_ENCODING
        )

    def _read_record(self, directory: Path) -> BackupRecord | None:
        """One backup's record, or `None` when this directory does not hold a complete one.

        Quiet on every failure, which is the opposite of `read_manifest` and is argued in the
        module docstring: an unreadable backup is one that cannot be restored, and the honest
        thing to do with it is not to offer it.
        """
        path = directory / RECORD_FILENAME
        if not path.is_file():
            return None
        try:
            document: Any = json.loads(path.read_text(encoding=_ENCODING))
        except (OSError, ValueError):
            return None
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            return None
        try:
            return BackupRecord(
                backup_id=str(document["backup_id"]),
                created_at=datetime.fromisoformat(str(document["created_at"])),
                target_path=str(document["target_path"]),
                paths=tuple(str(path) for path in document["paths"]),
                # Required, not defaulted: a record with no `kept` is a schema-1 record, which the
                # version check above has already turned away. Defaulting it to `()` here would
                # quietly read every path as "absent when taken" and delete the lot.
                kept=tuple(str(path) for path in document["kept"]),
                # Required for the same reason, one amendment later (R94): a record with no
                # `links` is a schema-2 record, already turned away, and defaulting it would read
                # every link as "absent when taken" and delete the user's link instead of
                # restoring it — the precise defect this field closes.
                links={
                    str(path): str(destination) for path, destination in document["links"].items()
                },
                # Required for the same reason, one amendment further (R110): a record with no
                # `modes` is a schema-3 record, already turned away. `BackupRecord` refuses a
                # kept path with no mode, so a `modes` block that has lost an entry raises
                # `ValueError` here and the backup is not offered — a damaged record is not a
                # record, which is this reader's posture for every other way one can be wrong.
                modes={str(path): int(mode) for path, mode in document["modes"].items()},
            )
        except (KeyError, TypeError, ValueError):
            return None


__all__ = [
    "BACKUPS_DIRECTORY_NAME",
    "BACKUP_FILE_MODE",
    "FILES_DIRECTORY_NAME",
    "RECORD_FILENAME",
    "SCHEMA_VERSION",
    "FilesystemBackupStore",
    "default_backups_root",
]
