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

**Paths are `str`, target-relative, `/`-separated** (R21) — C-12's vocabulary exactly, because the
paths handed to `create` come straight off a `PlanEntry`. Nothing here performs I/O and
`tests/domain/test_purity.py` bars `pathlib` from this layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


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
    """

    backup_id: str
    created_at: datetime
    target_path: str
    paths: tuple[str, ...] = ()

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
        of the backup's paths and no bytes are kept for it, so a restore removes it again.

        Raises:
            OSError: the backup could not be taken. A builtin, and deliberately so (ruling R24):
                `application/` is where it becomes `BACKUP_FAILED`, and a store raising that code
                itself would make the translation untestable by pre-supplying its result. Apply
                refuses the whole run rather than writing unprotected (F-9).
        """
        ...

    def restore(self, backup_id: str) -> None:
        """Put every path this backup describes back as it was.

        A path the backup holds bytes for is written back; a path it describes and holds no bytes
        for was absent when the backup was taken and is removed. Nothing else in the target is
        touched — a backup is not a snapshot of the whole directory, and restoring one must not
        delete a file that was never in it.

        This is the mechanism; **choosing** to run it is T-18's rollback use case.

        Raises:
            KeyError: no backup has this id.
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


__all__ = ["BackupRecord", "BackupStore"]
