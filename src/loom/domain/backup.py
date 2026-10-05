"""Contract C-13 — the copy taken before anything in a target is overwritten.

**This is the only undo.** Every other safety mechanism in this initiative is a refusal: the
verdict rule refuses to overwrite an edit, the plan refuses to act on a conflict, apply refuses to
write without a manifest. Those keep a mistake from happening. This is what is left when one
already has, and it is why apply refuses to run at all when the backup cannot be taken (F-9,
`BACKUP_FAILED`) rather than proceeding unprotected.

**A backup lives beside the manifests, under the state root, outside every tree it describes** —
the same reasoning DEC-14 applies to the manifest, and one step stronger. Inside the target it
would be destroyed by the very wipe it exists to recover from; inside the library it would be
committed, and a `git clean` would take it. Outside both, neither can reach it.

**It is a copy of a target, not a record of an install**, which is why this is a module of its own
rather than a section of `manifest.py`. A manifest says what *this tool* put somewhere; a backup
says what was *there*, whoever put it there. T-18's rollback restores one without reading the
other, and the two answer different questions about the same directory.

**A link is described, never dereferenced.** Ruling R94 records a symlink's destination in the
record and recreates the link on restore. Copying what it pointed at would put content from
outside the target into a backup of the target and then materialise it as a regular file, which
is the same escape R6 forbids, reached through the one mechanism meant to undo damage.

**A mode is content, and it is recorded per kept path.** Ruling R110. R56 normalises an
*installed* artifact to `0644`, which is this tool's decision about a file it created; a backup
puts back a file it did not create, and restoring one at `0644` makes a private file
world-readable and an executable inert while every digest says the restore worked. A mode is an
`int`, so recording one here needs nothing `tests/domain/test_purity.py` bars from this layer.

**Paths are `str`, target-relative, `/`-separated** (R21) — C-12's vocabulary exactly, because the
paths handed to `create` come straight off a `PlanEntry`. Nothing here performs I/O and
`tests/domain/test_purity.py` bars `pathlib` from this layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Protocol, runtime_checkable

_NO_LINKS: Mapping[str, str] = MappingProxyType({})

_NO_MODES: Mapping[str, int] = MappingProxyType({})

MAX_MODE = 0o7777
"""The widest permission word a path can carry: twelve bits, setuid and sticky included.

All twelve and not nine, because a backup puts back what was there. A file that was setgid before
this tool removed it is not restored by putting back nine of its bits.
"""


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """Contract C-13. One backup, as a listing shows it.

    Attributes:
        backup_id: what `create` returned and what `restore` is given. Opaque to every consumer:
            the store chooses the spelling, and nothing outside it may parse one.
        created_at: when the backup was taken. Timezone-aware, always, for the reason
            `Manifest.installed_at` is — a naive value read back on another day cannot be compared
            with an aware one without raising far from whichever of the two was wrong.
        target_path: the absolute directory these paths are relative to, as text. A user with two
            targets (R43) has backups of both in one directory, and a listing that did not say
            which target a backup came from would offer to restore one over the other.
        paths: every path the backup describes, target-relative.

            **Not every path it holds bytes for.** A path the target did not hold when the backup
            was taken is described here and stored nowhere, so restoring the backup *removes* it.
            That is what makes a first install undoable: the paths it created were absent before
            it ran, and putting the target back means taking them away again.
        kept: the subset of `paths` the backup holds **bytes** for — the paths the target really
            held when it was taken. **Ruling R92, amending C-13.**

            Recorded rather than inferred, and that is the whole amendment. A store that reads
            "was this path absent?" off its own file tree cannot tell an absence from a loss: a
            `files/<path>` removed after the fact by a stray `rm`, a half-cleaned state directory
            or a filesystem repair reads exactly like a path that was never there, and restoring
            that backup **deletes** a file the user still has — silently, with no error, no
            report and no code. Narrow trigger, unbounded consequence.

            With this field the two are different documents: a path in `kept` whose bytes are
            gone is a damaged backup and is refused before anything moves, and a path outside
            `kept` is removed as R79 requires. The duplication is deliberate and is the point —
            the record is the claim and the tree is the evidence, and a backup is exactly as
            trustworthy as the two agreeing.
        links: the described paths that were **symlinks** when the backup was taken, each mapped
            to the raw destination it named. **Ruling R94, amending C-13.**

            A link has no bytes to copy — ruling R6 never reads through one, and a store that
            did would put content from outside the target into a backup of it. Before this field
            a link was therefore described like an absent path and stored like one, so restoring
            the backup **removed** it and never put it back: the one destructive act in
            `clean --foreign`, the command whose entire safety model is this record, that nothing
            could undo.

            **A link's content is its destination**, which is a short string and belongs in the
            record rather than in a file tree. `restore` recreates the link with exactly this
            text, so a restored link is a link and not a copy of what it pointed at — the
            difference between putting a user's development link back and silently replacing it
            with a snapshot of somebody else's directory.

            Disjoint from `kept`, because a path is bytes or a link and never both, and a subset
            of `paths`, for the reason `kept` is.
        modes: the permission bits each **kept** path carried when the backup was taken.
            **Ruling R110, amending C-13.**

            **The mode is content here, and it is the one piece of it this record used to
            throw away.** A backup exists to put back a file *this tool did not create*, and
            before this field every restored path came back at the `0644` ruling R56 gives an
            **installed** artifact. On a real harness that is 149 private files — a credentials
            document, a control key, every transcript — made world-readable, and 56 executables
            disarmed, by the recovery path, silently, with the content byte-identical so that
            every hash-based check says the restore worked.

            R56 is right about an install and says nothing about a restore, and the distinction
            is the whole of this amendment: an installed file's mode is this tool's to choose,
            and a backed-up file's is the user's to get back.

            **Total over `kept`**, enforced below. A kept path is a regular file and always has
            a mode, so an optional field would mean "no mode recorded" restoring at `0644` —
            which is the defect, reached through the field that closes it.

            **Disjoint from `links`**, because it is keyed within `kept` and those two already
            are. A symlink has no mode of its own worth putting back: `chmod` follows a link, so
            setting one would change the permissions of whatever it names — a file outside the
            target, quite possibly — and `lchmod` is unavailable on Linux. R94 already says a
            link's whole content is its destination.
    """

    backup_id: str
    created_at: datetime
    target_path: str
    paths: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    links: Mapping[str, str] = field(default=_NO_LINKS)
    modes: Mapping[str, int] = field(default=_NO_MODES)

    def __post_init__(self) -> None:
        if not self.backup_id:
            raise ValueError("BackupRecord.backup_id must not be empty: it is what restores it")
        if self.created_at.tzinfo is None:
            raise ValueError(
                "BackupRecord.created_at must be timezone-aware: this value is written to disk "
                "and read back on another day, and it is what orders a listing of backups"
            )
        if not self.target_path:
            raise ValueError(
                "BackupRecord.target_path must not be empty: a backup whose target is unknown "
                "cannot be offered for restore without asking the user to guess"
            )
        object.__setattr__(self, "links", MappingProxyType(dict(self.links)))
        object.__setattr__(self, "modes", MappingProxyType(dict(self.modes)))
        unclaimed = sorted(set(self.kept) - set(self.paths))
        if unclaimed:
            raise ValueError(
                f"this backup keeps bytes for {unclaimed}, which it does not describe: restore "
                "walks `paths`, so bytes outside it would be held forever and put back never. "
                "`kept` is a subset of `paths` (R92), not a second list"
            )
        undescribed = sorted(set(self.links) - set(self.paths))
        if undescribed:
            raise ValueError(
                f"this backup records links at {undescribed}, which it does not describe: "
                "restore walks `paths`, so a link outside it would be recorded forever and "
                "recreated never. `links` is keyed within `paths` (R94), not a second list"
            )
        both = sorted(set(self.links) & set(self.kept))
        if both:
            raise ValueError(
                f"this backup holds both bytes and a link destination for {both}: a path was one "
                "or the other when it was taken, and a restore that had both would have to guess "
                "which the target really held (R94)"
            )
        empty = sorted(path for path, destination in self.links.items() if not destination)
        if empty:
            raise ValueError(
                f"this backup records an empty link destination for {empty}: a link's "
                "destination is its whole content, and an empty one cannot be recreated"
            )
        unkept = sorted(set(self.modes) - set(self.kept))
        if unkept:
            raise ValueError(
                f"this backup records a mode for {unkept}, which it holds no bytes for: a mode "
                "belongs to a file, and `modes` is keyed within `kept` (R110). A path that was "
                "absent is put back by being removed, and a symlink has no mode of its own — "
                "chmod follows one, so setting it would change a file outside the target"
            )
        unrecorded = sorted(set(self.kept) - set(self.modes))
        if unrecorded:
            raise ValueError(
                f"this backup holds bytes for {unrecorded} and records no mode for them: `modes` "
                "is total over `kept` (R110). A restore with no recorded mode puts the file back "
                "at the 0644 an *installed* artifact gets (R56), which makes a private file "
                "world-readable and an executable inert — the defect this field closes"
            )
        outside = sorted(path for path, mode in self.modes.items() if not 0 <= mode <= MAX_MODE)
        if outside:
            raise ValueError(
                f"this backup records a mode outside 0..0o7777 for {outside}: a mode is the "
                "permission word of a path, and the file type bits are not a backup's to restore"
            )


@runtime_checkable
class BackupStore(Protocol):
    """Somewhere to put a copy of a target before writing to it. Contract C-13.

    Three members, and no fourth: this is a seam a fake replaces so apply is testable without a
    disk, and every member a fake implements is a member two tasks can get wrong in two places.

    The store knows which target it is for; `create` is given paths and never a root.
    """

    def create(self, paths: tuple[str, ...]) -> str:
        """Copy every one of these target-relative paths, and return the backup's id.

        A path the target does not hold is **not** an error and not a skip: it is recorded as one
        of the backup's paths, left out of `kept`, and no bytes are stored for it — so a restore
        removes it again.

        A path the target holds as a **symlink** is the third case (R94): no bytes are copied,
        because R6 never reads through one, and the destination it names is recorded in `links`
        instead, so a restore can recreate the link as a link.

        A path whose bytes are copied has its **mode** recorded too (R110). The mode is read
        here and nowhere else: by the time `restore` runs, the file it describes may not exist.

        Raises:
            OSError: the backup could not be taken. A builtin, and deliberately so (ruling R24):
                `application/` is where it becomes `BACKUP_FAILED`, and a store raising that code
                itself would make the translation untestable by pre-supplying its result. Apply
                refuses the whole run rather than writing unprotected (F-9).
        """
        ...

    def restore(self, backup_id: str) -> None:
        """Put every path this backup describes back as it was.

        A path in `kept` is written back from the bytes the backup stored **and at the mode it
        recorded** (R110) — a restore is not an install, so R56's `0644` is not applied to it; a
        path in `links` is recreated as a symlink naming the destination it named before (R94); a
        path it describes and holds neither for was absent when the backup was taken and is
        removed. Nothing else
        in the target is touched — a backup is not a snapshot of the whole directory, and
        restoring one must not delete a file that was never in it.

        This is the mechanism; **choosing** to run it is T-18's rollback use case.

        Raises:
            KeyError: no *complete* backup has this id. Since ruling R92 that covers a backup
                whose record is missing or unreadable **and** one whose record claims bytes the
                store no longer holds: the second is checked before the first path is touched,
                because a half-restored target is a cost worth paying to undo a real install and
                is not a cost worth paying to act on a damaged record.
            OSError: the target could not be written.
        """
        ...

    def list(self) -> tuple[BackupRecord, ...]:
        """Every backup this store holds, oldest first.

        Ordered rather than arbitrary because the question a caller asks is "what is the most
        recent one", and an order decided by the filesystem's directory listing answers it
        differently on two machines.
        """
        ...


__all__ = ["MAX_MODE", "BackupRecord", "BackupStore"]
