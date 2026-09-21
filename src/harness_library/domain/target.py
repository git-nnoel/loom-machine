"""Contract C-12 — what an install target is, and the one seam that reaches it.

A target is **not** a library. The library has a type registry, artifact roots and a layout this
project defines; a target is a directory on a user's machine holding paths, most of which this tool
did not put there and must never touch. So this protocol has no notion of an artifact, no notion of
a type, and no rule about what a path means. It reports what is on disk and it writes what it is
told to write; every judgement about a path belongs to `install_plan.py`, one layer over.

That division is what makes apply testable without a disk: a fake implementing these members is
the whole of the filesystem as far as T-15's plan and T-16's apply can see. There are **seven**
since ruling R97 — five that judge and move bytes, and `read_link` / `write_link`, which exist
because a link's content is its destination and R6 forbids reaching it any other way.

**Symlinks are recorded, never followed** (ruling R6, charter §7). `is_symlink` is a field rather
than a reason to omit the entry, because the library scanner's posture — skip it and report it —
is exactly wrong here: install is about to decide whether to *write* that path, and a path it
cannot see is a path it would create straight through the link. A link resolving outside the
target is how a copy writes where it should not, and this is the layer that must see it.

**The scan is a point-in-time snapshot**, the same statement charter §7 makes about the library and
`domain/repository.py` repeats for C-4. A file changing between the scan and the apply yields a
torn read: the plan judged a digest the target no longer holds. This is accepted for a
single-user tool and is written down rather than left silently true — T-17's advisory lock keeps
two `hl` processes apart, and nothing keeps a user's editor out.

**Paths are `str`, never `pathlib.Path`** (R21), and always relative to the target root, using
`/` as the separator. `PlanEntry.path` is the same vocabulary, so the two join without a
conversion. This layer performs no I/O; `tests/domain/test_purity.py` bars `pathlib` from it.

**There is no `is_text`.** C-12 gives `TargetFile` four fields and no member needs a fifth: content
in a target is hashed, written and read as bytes, never searched and never diffed here. Charter §7
keeps one implementation of that rule — `infrastructure.scanner.is_text` over real bytes — and this
module does not add a second.

T-21 met the question twice and needed the field neither time. `$EDITOR` is handed bytes and lets
the editor decide what they are; `resolve target`, which has to put an `ArtifactFile` in the
manifest, **carries** the flag from whichever side already decided it — the previous record, or the
library's own `ArtifactFile` — because `application/` may not import `infrastructure/` and a third
answer to "is this text" is exactly what charter §7 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TargetFile:
    """Contract C-12. One path found in an install target, and what the scan knows about it.

    Deliberately thinner than C-1's `ArtifactFile`, which it mirrors field for field except for
    `is_text`. The two are separate types because they answer different questions: an
    `ArtifactFile` is a file *this library owns*, and a `TargetFile` is a path that merely *exists*
    somewhere we are about to write. Collapsing them would let a foreign path be mistaken for one
    of ours by its type alone.

    Attributes:
        path: relative to the target root, `/`-separated. Never absolute, never empty.
        sha256: `hashing.hash_bytes` of the file's contents, lowercase hex — and **`None` for a
            symlink**, which is never read. Ruling R68 replaced T-14's empty-string sentinel:
            `""` is a value that compares, sorts and renders like a digest while being none, and
            `None` is the spelling every other optional field in C-10 and C-11 already uses.
        size: the file's size in bytes. For a symlink this is the link's own `lstat` size, the
            length of the path it names, and not the size of whatever it points at.
        is_symlink: whether this path is a symbolic link. The branchable fact; never followed.

    **`None` is not "the target does not hold this path".** The entry exists, so the target holds
    it; what is missing is only its content. A consumer that passed this straight through as
    `PlanEntry.target_sha` would tell the verdict rule the path is absent, which is judged
    `CREATE` and written straight through the link on the next apply.
    `application.read.drift.target_sha_of` is where that is handled, once.

    **The one invariant, and it runs one way.** A symlink carries no content digest, because R6
    forbids reading through it and the alternative — hashing the destination — is the escape the
    ruling exists to prevent. The converse is deliberately *not* enforced: a regular entry is not
    required to carry a digest. Enforcing it would mean a scanner that reported a link as an
    ordinary file raised here instead of returning a wrong answer, and a raise is not something a
    test of the flag can distinguish from every other test of the same scan failing. The rule
    worth having is the one about what must never be hashed.
    """

    path: str
    sha256: str | None
    size: int
    is_symlink: bool

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("TargetFile.path must not be empty")
        if self.size < 0:
            raise ValueError(f"TargetFile.size must not be negative: {self.size}")
        if self.is_symlink and self.sha256 is not None:
            raise ValueError(
                f"{self.path!r} is a symlink and carries the digest {self.sha256!r}: ruling R6 "
                "says a link is never followed and never hashed as content, so a digest here "
                "could only have come from reading through it"
            )


@runtime_checkable
class TargetRepository(Protocol):
    """Read and write access to one install target. Contract C-12.

    **Seven members since ruling R97**, and the count is not incidental: this is the seam a fake
    replaces, and every member a fake has to implement is a member two tasks can get wrong in two
    places. Five of them are the original contract; `read_link` and `write_link` arrived on
    `FilesystemTargetRepository` alone in T-20, because a backup that could not put a symlink back
    made `clean --foreign` un-undoable for one (R94) and amending a contract is a plan-level
    decision. R97 is that decision — a ruling that amends a contract in prose and is carried into
    no protocol is R23's recorded failure, and the seam is only a seam where the protocol says so.
    """

    def scan(self) -> tuple[TargetFile, ...]:
        """Every path in the target, in a deterministic order.

        **Nothing is filtered.** Not an editor swap file, not a vendor tree, not a dotfile, and
        not Claude Code's own `synced/` bucket — ruling R44 says that bucket is foreign like
        anything else the library and the manifest both disown, and a named exclusion here would
        silently hide whatever else lands in that directory. The library scanner filters because
        it is deciding what an artifact *contains*; this one is reporting what is *there*.

        Directories are not entries; the files under them are, each with the directory in its
        path. A symlink is one entry and is not descended into, whatever it points at.

        Returns:
            A point-in-time snapshot. See the module docstring: a file changing after the scan
            makes the plan's digest for it stale, which is accepted and stated rather than locked
            against.

        Raises:
            OSError: a path exists and cannot be read or listed. This is a fault and never an
                absence: a file omitted from the scan is a file no side of the verdict rule knows
                the target holds, which is judged `CREATE` and overwritten on the next apply.
        """
        ...

    def read_bytes(self, path: str) -> bytes:
        """The raw bytes at one target-relative path.

        Bytes and never text: a target holds binary, and a `read_text` here would invite a
        round-trip through `str` that does not survive one.

        Raises:
            ValueError: the path is empty, absolute, climbs out of the target with `..`, passes
                through a symlinked directory, or is itself a symlink — which R6 never follows.
            FileNotFoundError: the target holds nothing at that path.
        """
        ...

    def write(self, path: str, data: bytes) -> None:
        """Write `data` at one target-relative path, creating the directories it needs.

        Raises:
            ValueError: as `read_bytes`, including the refusal to write *through* a symlink.
            OSError: the path could not be written.
        """
        ...

    def delete(self, path: str) -> None:
        """Remove one file, or one symlink, at a target-relative path.

        A symlink is removed as itself — unlinking a link is the opposite of following one — so
        this is the single member that accepts a symlinked final component. A directory is never
        removed: uninstall removes the files a manifest names and nothing else (F-12).

        Raises:
            ValueError: the path is empty, absolute, climbs out with `..`, or passes through a
                symlinked directory.
            FileNotFoundError: the target holds nothing at that path.
            IsADirectoryError: the path is a directory.
        """
        ...

    def exists(self, path: str) -> bool:
        """Whether anything is at this target-relative path.

        A symlink counts, including one whose destination is gone: the question is whether a write
        would land on something, and a dangling link is very much something.

        Raises:
            ValueError: the path is empty, absolute, climbs out with `..`, or passes through a
                symlinked directory. A malformed path is a mistake to report, not an absence to
                answer `False` to.
        """
        ...

    def read_link(self, path: str) -> str:
        """The raw destination a symlink at this target-relative path names, unresolved.

        **Contract C-12 since ruling R97.** A link's content is not bytes — R6 forbids reading
        through it, so `read_bytes` refuses one outright and `scan` reports it with no digest.
        Its content is the text it points at, and this is the only member that answers with it.

        `readlink` and never `resolve`: the destination is wanted as text rather than as a place,
        a relative destination keeps the `..` components that are the whole diagnosis, and
        resolving would both follow the link and turn a dangling one — which a backup must still
        be able to put back — into an error.

        Raises:
            ValueError: the path is empty, absolute, climbs out with `..`, passes through a
                symlinked directory, or **is not a symlink at all**. A caller asking a regular
                file for its destination has confused two kinds of path, and answering would
                invent one.
            FileNotFoundError: the target holds nothing at that path.
        """
        ...

    def write_link(self, path: str, destination: str) -> None:
        """Create a symlink at this target-relative path naming `destination`, replacing whatever
        is there.

        **Contract C-12 since ruling R97**, and the inverse of `read_link` rather than a variant
        of `write`: `write` puts bytes at a path and refuses to do it through a link, while this
        one puts a link at the path itself.

        The destination is written **verbatim** and is never resolved, joined or checked. It is
        the text the link carried when it was recorded, and a restore that "corrected" it would
        put back a different link from the one it removed. Where it points is not this seam's
        business — nothing here follows it, and a dangling link is restored as a dangling link,
        which is what was there.

        Raises:
            ValueError: the path is empty, absolute, climbs out with `..`, passes through a
                symlinked directory, or `destination` is empty — a link's destination is its
                whole content.
            OSError: the link could not be created.
        """
        ...


__all__ = ["TargetFile", "TargetRepository"]
