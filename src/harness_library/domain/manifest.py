"""Contract C-11 — what was last installed into one target.

The manifest is the only reason any of initiative 02 is reversible. Rollback restores what it
names, uninstall removes what it names, prune removes what left the library, and `LOCAL_EDIT`
exists at all only because something remembers what this tool wrote. Take the manifest away and
install is a `cp -a` again: it cannot tell a file it wrote from a file the user wrote, so it must
either refuse everything or overwrite everything.

**It is a record, not a judgement.** `install_plan.py` decides what to do about a path; this module
only remembers what was done. They are separate modules because T-18's rollback and T-19's prune
read the record without ever building a plan, and because a rename landing on one and not the other
should fail loudly rather than typecheck.

**The per-file digests are C-1's `ArtifactFile`, reused rather than restated.** That type was built
for this: its docstring already says initiative 02 judges install *per path*. A parallel
`ManifestFile` with the same four fields would be a second definition of "a file we know about",
and the two would drift on the first field either one gains.

**Absent is not empty.** A target with no manifest was never installed into; a target whose
manifest records no artifacts was installed into and then emptied. The reader keeps those apart —
`infrastructure/manifest_store.py` answers `None` for the first and a `Manifest` with no artifacts
for the second — so nothing here needs an `empty()` constructor, and nothing here should grow one.

**Paths are `str`, never `pathlib.Path`** (R21). This layer performs no I/O and
`tests/domain/test_purity.py` bars `pathlib` from it beyond what `import-linter` can see. A manifest
records an *absolute* target path — the location of a directory on this machine — and that is still
text to every consumer of it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from harness_library.domain.artifact import ArtifactFile


@dataclass(frozen=True, slots=True)
class ManifestArtifact:
    """One artifact as it was installed. Part of contract C-11.

    Attributes:
        artifact_id: the canonical `<type>/<name>` identity this record is about.
        content_hash: the artifact's `content_hash` at the moment it was installed — charter §7's
            hash over sorted `(relative path, bytes)`, excluding file mode (R9, R56). Recorded
            alongside the per-file digests, not instead of them: the whole-artifact hash answers
            "has this artifact moved on" in one comparison, and the per-file digests are what the
            verdict rule judges a single path on.
        files: every file that was written, with the digest each held when it was written. Paths
            are relative to the **artifact root**, exactly as the scanner produced them, so a
            consumer joins them onto the artifact's root within the target rather than storing the
            same prefix once per file.
    """

    artifact_id: str
    content_hash: str
    files: tuple[ArtifactFile, ...] = ()

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ValueError("ManifestArtifact.artifact_id must not be empty")
        if not self.content_hash:
            raise ValueError(
                f"ManifestArtifact.content_hash must not be empty for {self.artifact_id!r}: an "
                "empty digest compares unequal to every real one, so the next install would "
                "report an untouched artifact as changed"
            )
        duplicates = sorted(
            path for path, count in Counter(file.path for file in self.files).items() if count > 1
        )
        if duplicates:
            raise ValueError(
                f"{self.artifact_id} records {duplicates} more than once: two digests for one "
                "path give the verdict rule two answers, and it would take whichever the lookup "
                "happened to build last"
            )


@dataclass(frozen=True, slots=True)
class Manifest:
    """Contract C-11. What was last installed into one target, and from where.

    Attributes:
        target_path: the absolute directory this manifest describes, as text (R21). One manifest
            per target (R43); the store keys the file by a digest of this path, which is what makes
            a second target cost nothing but a second file.
        installed_at: when the install that produced this record finished. Timezone-aware, always,
            for the reason `Artifact.updated_at` is: a naive value mixed with an aware one raises
            inside a comparison, far from whichever of the two was wrong.
        library_git_sha: the library's commit at install time, or `None` when the library is not a
            git work tree or was dirty. This is the field that answers "which version is on this
            machine" across clones, and `None` is an honest answer to it rather than a missing one.
        backup_id: the backup taken before this install, or `None` when none was needed — a first
            install into an empty target overwrites nothing. T-16 fills it; C-13 owns what the id
            means.
        artifacts: one record per artifact installed, in the order the install wrote them. Empty is
            a value: a target that was installed into and then uninstalled has a manifest with no
            artifacts, which is not the same fact as having no manifest at all.
    """

    target_path: str
    installed_at: datetime
    library_git_sha: str | None = None
    backup_id: str | None = None
    artifacts: tuple[ManifestArtifact, ...] = ()

    def __post_init__(self) -> None:
        if not self.target_path:
            raise ValueError(
                "Manifest.target_path must not be empty: the manifest is keyed by this path, and "
                "an empty one keys every target to the same file"
            )
        if self.installed_at.tzinfo is None:
            raise ValueError(
                "Manifest.installed_at must be timezone-aware: this value is written to disk and "
                "read back on another day, and a naive instant cannot be compared with an aware "
                "one without raising far from whichever of the two was wrong"
            )
        duplicates = sorted(
            artifact_id
            for artifact_id, count in Counter(
                artifact.artifact_id for artifact in self.artifacts
            ).items()
            if count > 1
        )
        if duplicates:
            raise ValueError(
                f"this manifest records {duplicates} more than once: uninstall and rollback both "
                "act on 'the files this manifest names for this artifact', and two records give "
                "that question two answers"
            )


__all__ = ["Manifest", "ManifestArtifact"]
