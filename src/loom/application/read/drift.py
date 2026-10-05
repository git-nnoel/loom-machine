"""Drift between a library, a manifest and an install target — and the join the three need.

This is where the three sources first have to agree about what a path *is*. Every verdict above it
is correct in the abstract and worthless if the join is wrong: a library file and its installed
copy that fail to line up read as `CREATE` plus `FOREIGN` instead of `UNCHANGED`, and the next
apply rewrites a file it did not need to touch while reporting someone else's file as foreign.

**The key is the target-relative path**, and each source spells it differently:

* the **library** (C-4) holds `ArtifactFile.path` relative to the *artifact root* — `SKILL.md`,
  `references/diagram.png`;
* the **manifest** (C-11) holds the same artifact-root-relative paths, and records **no** root for
  the artifact inside the target;
* the **target** (C-12) holds `TargetFile.path`, already relative to the target root.

`registry.target_path_of` is the join, and it lives in `domain/registry.py` beside `root_path` and
`entry_path` — **ruling R73**, which moved it out of this module: all three answer where something
lives and all three read one `TypeSpec`. Nothing stores the prefix: once per file it would repeat
the same string N times, and once per artifact it would be a second source of truth for something
`TypeSpec` already answers — the two would disagree the first time a type's directory moved, and
the disagreement would surface as install writing to one place and uninstall looking in another.

**Nothing here decides a verdict.** `domain/install_plan.py` owns that table and
`plan_entry_for` is the only constructor used, because the four conflict shapes have four causes
and only the rule knows which fired (R61). This module's whole job is to hand that rule the right
three digests for the right key.

**Nothing here writes.** It is a read use case in the read package, and `application/write/` holds
the use case that *acts* on the same plan. The composition is on this side rather than the other
because `application/read/` may not import `application/write/`: `mcp/tools.py` imports this
package, `import-linter`'s forbidden contracts follow indirect imports, and a `read → write` edge
would break `mcp-is-read-only` the moment the name was re-exported.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from loom.domain.artifact import Artifact
from loom.domain.identity import ArtifactType, parse_artifact_id
from loom.domain.install_plan import InstallPlan, PlanEntry, plan_entry_for
from loom.domain.manifest import Manifest
from loom.domain.registry import spec_for, target_path_of
from loom.domain.repository import ArtifactRepository
from loom.domain.target import TargetFile, TargetRepository

UNHASHED_TARGET_SHA = "<unhashed>"
"""What `PlanEntry.target_sha` carries for a target path whose content was never read.

A symlink is the only producer today: ruling R6 never follows one and never hashes one, so
`TargetFile.sha256` is absent for it. **That absence is not the path's absence.** The target holds
the path — a write would land on something — and passing `None` through to the verdict rule would
say the opposite, which is judged `CREATE` and written straight through the link on the next apply.

So the path is reported as present, carrying a value no digest can equal. The rule then reaches
`LOCAL_EDIT` or `CONFLICT` through the ordinary table rather than through a special case, which is
the right answer and is now one somebody wrote down. The angle brackets are what make the collision
impossible: `hash_bytes` returns lowercase hex and nothing else.
"""


def target_sha_of(file: TargetFile) -> str:
    """The digest the verdict rule judges this target path on. Never `None` — the target holds it.

    Written as a test for **truth** rather than for `is not None` on purpose. T-14 spelled "no
    digest" as the empty string and ruling R68 respells it `None`; both are falsy, so this answer
    does not change when the sentinel does. Getting it wrong in the other direction is the
    expensive mistake: a path reported absent is judged `CREATE` and overwritten.
    """
    return file.sha256 or UNHASHED_TARGET_SHA


def diff_against_target(
    library: ArtifactRepository,
    target: TargetRepository,
    *,
    manifest: Manifest | None,
) -> InstallPlan:
    """What the library, the manifest and the target say about every path any of them holds.

    One entry per path, in path order — `InstallPlan` neither sorts nor deduplicates, so the order
    is decided here and is total, which is what lets two runs over one pair of snapshots be
    compared.

    Args:
        library: contract C-4, the library being installed *from*.
        target: contract C-12, the directory being installed *into*. Read only; this use case
            calls `scan()` and nothing else.
        manifest: contract C-11, what was last installed into this target, or `None` when nothing
            was. **Required, with no default**: a caller that omitted it would judge every path
            `CREATE` and overwrite the whole target, which is the one catastrophe the manifest
            exists to prevent, and a default would let that be a typo rather than a decision.

    Raises:
        ValueError: the manifest records an `artifact_id` that is not a `<type>/<name>` identity,
            so the files it names cannot be located inside the target. See `_manifest_files`.
    """
    artifacts = library.list_all()
    library_files = _library_files(artifacts)
    manifest_files = _manifest_files(manifest)
    target_files = {file.path: target_sha_of(file) for file in target.scan()}
    roots = _artifact_roots(artifacts, manifest)

    entries: list[PlanEntry] = []
    for path in sorted({*library_files, *manifest_files, *target_files}):
        held_by_library = library_files.get(path)
        held_by_manifest = manifest_files.get(path)
        entry = plan_entry_for(
            artifact_id=_owner_of(path, held_by_library, held_by_manifest, roots),
            path=path,
            library_sha=held_by_library.sha256 if held_by_library is not None else None,
            manifest_sha=held_by_manifest.sha256 if held_by_manifest is not None else None,
            target_sha=target_files.get(path),
        )
        # Never `None` here: every path in the union is held by at least one side, which is the
        # case `decide_verdict` answers `None` to. The narrowing is for the type, not for a state.
        if entry is not None:
            entries.append(entry)
    return InstallPlan(entries=tuple(entries))


class _Held(NamedTuple):
    """One side's knowledge of one target path: whose it is, and what digest it carries."""

    artifact_id: str
    sha256: str


def _library_files(artifacts: list[Artifact]) -> dict[str, _Held]:
    """Every file the library would install, keyed by where it would land.

    An artifact with no files — a skill directory whose `SKILL.md` is missing, which is still an
    artifact carrying its V1 finding — contributes nothing and is not an error here. Whether an
    invalid artifact may be installed at all is not this layer's question; nothing in C-9 spells
    the refusal, and T-20 owns the one refusal that is spelled (V11's `SKIPPED`).

    Two artifacts cannot normally claim one target path — an artifact root is `<directory>/<name>`
    and names are unique within a type — so the first claim wins rather than being reconciled by a
    rule nobody wrote. A library that managed it is a library-level fault (charter §8's V8 is the
    nearest), not a plan whose entries should be silently doubled.
    """
    found: dict[str, _Held] = {}
    for artifact in artifacts:
        for file in artifact.files:
            path = target_path_of(artifact.type, artifact.name, file.path)
            found.setdefault(path, _Held(artifact.id, file.sha256))
    return found


def _manifest_files(manifest: Manifest | None) -> dict[str, _Held]:
    """Every file the manifest says was installed, keyed by where it was written.

    The manifest records artifact-root-relative paths and no root, so this is the same join the
    library goes through — deliberately the same function, because a manifest and a library that
    disagreed about where a file lives would report every installed file as `CREATE` plus
    `FOREIGN` and rewrite the target on the next apply.

    Raises:
        ValueError: an `artifact_id` that is not a `<type>/<name>` identity. `ManifestArtifact`
            rejects only the empty string and the store's reader does not check the shape, so a
            hand-edited manifest can carry one. It is refused rather than skipped: skipping it
            would leave that artifact's installed files held by neither the library nor the
            manifest, read `FOREIGN`, and become unprunable and ununinstallable — orphaned by the
            record that exists to make them removable.
    """
    found: dict[str, _Held] = {}
    if manifest is None:
        return found
    for record in manifest.artifacts:
        artifact_type, name = _identity_of(record.artifact_id)
        for file in record.files:
            path = target_path_of(artifact_type, name, file.path)
            found.setdefault(path, _Held(record.artifact_id, file.sha256))
    return found


def _artifact_roots(artifacts: list[Artifact], manifest: Manifest | None) -> dict[str, str]:
    """Every artifact root this install knows about, target-relative, to its artifact id.

    From the library *and* the manifest: an artifact that left the library still has a root inside
    the target holding the files a prune is about to remove, and a foreign path beside them belongs
    to it just as much.
    """
    roots = {
        spec_for(artifact.type).root_path(artifact.name): artifact.id for artifact in artifacts
    }
    if manifest is not None:
        for record in manifest.artifacts:
            artifact_type, name = _identity_of(record.artifact_id)
            roots.setdefault(spec_for(artifact_type).root_path(name), record.artifact_id)
    return roots


def _identity_of(artifact_id: str) -> tuple[ArtifactType, str]:
    """`<type>/<name>` split, or a refusal. See `_manifest_files` for why it is not a skip."""
    identity = parse_artifact_id(artifact_id)
    if identity is None:
        raise ValueError(
            f"the manifest records {artifact_id!r}, which is not a <type>/<name> identity, so "
            "there is no artifact root to locate its files under. A manifest this tool wrote "
            "cannot contain one; reinstalling into this target rewrites it"
        )
    return identity


def _owner_of(
    path: str,
    held_by_library: _Held | None,
    held_by_manifest: _Held | None,
    roots: Mapping[str, str],
) -> str | None:
    """Which artifact this path belongs to, or `None` — **ruling R60**, and only for that case.

    A path the library or the manifest holds belongs to the artifact that declared it. A path only
    the target holds belongs to the artifact whose root contains it, which is how
    `skills/<name>/SKILL.md.swp` comes back `FOREIGN` and still says whose directory it is sitting
    in. `None` is reserved for a path under no artifact root at all: `settings.json`, and every
    path of Claude Code's `synced/` bucket — `skills/synced` is not an artifact root merely by
    being shaped like one, and ruling R44 gives that bucket no named exclusion anywhere.
    """
    if held_by_library is not None:
        return held_by_library.artifact_id
    if held_by_manifest is not None:
        return held_by_manifest.artifact_id
    return _root_containing(path, roots)


def _root_containing(path: str, roots: Mapping[str, str]) -> str | None:
    """The id of the artifact whose root contains `path`, or `None` when none does.

    The longest root wins. Roots of one type cannot nest today — `skills/a` and `skills/a-b` are
    siblings — so this is not a rule the current registry needs; it is what stops the answer being
    decided by dictionary order if one ever does.
    """
    owner: str | None = None
    longest = ""
    for root, artifact_id in roots.items():
        if len(root) > len(longest) and (path == root or path.startswith(f"{root}/")):
            owner, longest = artifact_id, root
    return owner


__all__ = [
    "UNHASHED_TARGET_SHA",
    "diff_against_target",
    "target_sha_of",
]
