"""The `hl` command-line application — the first surface a human actually touches.

Every command has the same shape and holds no logic of its own:

```
resolve the root  →  open the library  →  call one use case  →  render
```

Everything interesting was decided below and proven there. What is decided *here*, and nowhere
else, is: which exit status a failure produces (contract C-6), that diagnoses go to stderr while
payloads go to stdout (charter §11), and that `--json` emits the frozen C-7 payload verbatim
(ruling R7).

**On adding a command.** `_run` is the whole convention: wrap the body, and every error in the
taxonomy already maps to the right status and the right stream. A command that catches its own
exceptions has opted out of contract C-6 without saying so.

---

## The write path (T-22)

Six of these commands change a user's harness, and two things about them are decided here and
nowhere else.

**`INCOMPLETE = 6` is not an error and is never raised.** The payload goes to stdout naming every
entry that was left alone and why, and the command then exits 6 — `hl validate`'s shape exactly
(ruling R57). A script must be able to tell *"you must decide"* from *"it broke"*, and routing it
through `_run` would put a diagnosis on stderr for a run in which nothing went wrong.

**`hl install --resolve` runs two write use cases, in sequence and never nested.** The lock is
per target and not per process (C-16, R82), so a second acquire inside the first is refused, and
`ManifestStore` has one member (C-15), so nothing inside `application/` can re-read a record
between them. The second use case is therefore handed **the manifest the first one wrote** —
`ApplyResult.manifest`, never `TargetSession.manifest`, which was read before the command
started. A resolve given the stale one drops from the record every artifact the apply just
installed, and their files become `FOREIGN`: untouchable by install, unremovable by uninstall.

**The apply runs first and the resolution second, and that order is load-bearing.** The other way
round, `--resolve target` destroys the very file the user asked to keep: recording the target's
digest makes the path (library `L`, manifest `T`, target `T`), which C-9 judges `UPDATE`, which
apply writes. Feature F-15 requires that file to be byte-identical afterwards and ruling R100
says the overwrite belongs to *the next* install, so the resolution is the last thing the command
does. See `--resolve`'s help: it settles a refusal and does not pin a file.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, TextIO

import typer

from harness_library.application.read import (
    ArtifactFilter,
    Payload,
    SortKey,
    diff_against_target,
    export_collection,
    get_collection,
    list_artifacts,
    list_backups,
    list_collections,
    search_artifacts,
    validate_library,
)
from harness_library.application.read import (
    get_artifact as read_artifact,
)
from harness_library.application.write import (
    ApplyResult,
    apply_install,
    clean_foreign,
    compare_versions,
    plan_install,
    prune_target,
    pruned_entries,
    resolve_conflict,
    rollback_install,
    uninstall_artifact,
)
from harness_library.cli import payloads, rendering
from harness_library.cli.composition import (
    TargetNotInstalledError,
    TargetSession,
    open_editor,
    open_library,
    open_target,
)
from harness_library.cli.exit_codes import INCOMPLETE, OK, VALIDATION_FAILED, exit_status_for
from harness_library.cli.logging import configure_logging
from harness_library.domain.errors import (
    BackupNotFoundError,
    HarnessLibraryError,
    TargetUnwritableError,
)
from harness_library.domain.identity import ArtifactType
from harness_library.domain.install_plan import InstallPlan, PlanEntry
from harness_library.domain.manifest import Manifest
from harness_library.domain.repository import ArtifactRepository
from harness_library.domain.resolution import Resolution

app = typer.Typer(
    name="hl",
    help="Read, search, validate and install a Claude Code harness library.",
    no_args_is_help=True,
    add_completion=False,
)


class ResolveSide(StrEnum):
    """The three spellings of `--resolve`. **This layer's vocabulary, not the domain's.**

    `domain.resolution.Resolution` has two members because a *side* is one of two things — the
    library's version or the target's — and `$EDITOR` is not a third side: it shows both and
    decides nothing. That module says in as many words that the flag with three spellings is
    T-22's, and this is it. A `StrEnum` so Typer renders the choices and a typo is exit 2 rather
    than a token nothing handles.
    """

    LIBRARY = "library"
    """Write the library's version over the target's, and record it. Takes a backup (R88)."""

    TARGET = "target"
    """Keep what is on the target's disk and repair the record to match. Writes no file."""

    EDIT = "edit"
    """Open both versions in `$EDITOR` and decide nothing. The run stays incomplete."""


@dataclass(frozen=True, slots=True)
class CliContext:
    """What every command needs from the invocation.

    Attributes:
        library: the `--library` flag, or `None`. Resolution happens per command rather than in the
            callback so that `hl --help` and a bad flag never touch the filesystem, and so a
            resolution failure is reported through `_run` like every other failure.
    """

    library: Path | None


@app.callback()
def main(
    ctx: typer.Context,
    library: Annotated[
        Path | None,
        typer.Option(
            "--library",
            help="The library root. Overrides $HL_LIBRARY; defaults to the current directory.",
            show_default=False,
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Emit debug logs (to stderr).")
    ] = False,
) -> None:
    """Global options. Logging is configured here so every command inherits stderr-only output."""
    configure_logging(verbose=verbose)
    ctx.obj = CliContext(library=library)


@app.command("list")
def list_command(
    ctx: typer.Context,
    artifact_type: Annotated[
        ArtifactType | None, typer.Option("--type", help="Only artifacts of this type.")
    ] = None,
    tag: Annotated[
        str | None, typer.Option("--tag", help="Only artifacts carrying this tag.")
    ] = None,
    collection: Annotated[
        str | None, typer.Option("--collection", help="Only members of this collection.")
    ] = None,
    invalid_only: Annotated[
        bool, typer.Option("--invalid-only", help="Only artifacts with an ERROR finding.")
    ] = False,
    no_superseded: Annotated[
        bool, typer.Option("--no-superseded", help="Hide superseded artifacts (shown by default).")
    ] = False,
    sort: Annotated[SortKey, typer.Option("--sort", help="Ordering.")] = SortKey.NAME,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the JSON payload.")] = False,
) -> None:
    """List the artifacts in the library.

    Superseded artifacts appear by default, ranked below their successors (ruling R8). Invalid
    artifacts appear too, carrying their findings — a library you cannot see the faults of is the
    problem this tool exists to solve.
    """
    with _run(as_json):
        payload = list_artifacts(
            _open(ctx),
            artifact_filter=ArtifactFilter(
                type=artifact_type,
                tag=tag,
                collection=collection,
                invalid_only=invalid_only,
                include_superseded=not no_superseded,
            ),
            sort_key=sort,
        )
        _emit(payload, as_json, rendering.render_artifact_list)


@app.command("show")
def show_command(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument(help="The artifact's `<type>/<name>` id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit the JSON payload.")] = False,
) -> None:
    """Show one artifact in full.

    **An invalid artifact is shown, not raised on** (feature F-2). A skill directory with no
    `SKILL.md` is rendered with its V1 finding and a null entry document, because that is precisely
    the artifact a user needs to see. Only an id that is not in the library is an error.
    """
    with _run(as_json):
        payload = read_artifact(_open(ctx), artifact_id)
        _emit(payload, as_json, rendering.render_artifact_detail)


@app.command("search")
def search_command(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Text to look for, matched case-insensitively.")],
    artifact_type: Annotated[
        ArtifactType | None, typer.Option("--type", help="Only artifacts of this type.")
    ] = None,
    tag: Annotated[
        str | None, typer.Option("--tag", help="Only artifacts carrying this tag.")
    ] = None,
    collection: Annotated[
        str | None, typer.Option("--collection", help="Only members of this collection.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the JSON payload.")] = False,
) -> None:
    """Search the entry documents and markdown references.

    Files that were not searched are reported with a reason (rulings R4, R25 and R27). A result set
    that reached the cap is marked truncated rather than passed off as complete.
    """
    with _run(as_json):
        payload = search_artifacts(
            _open(ctx),
            query,
            artifact_filter=ArtifactFilter(type=artifact_type, tag=tag, collection=collection),
        )
        _emit(payload, as_json, rendering.render_search_results)


@app.command("validate")
def validate_command(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the JSON payload.")] = False,
) -> None:
    """Validate the whole library.

    Exits non-zero when any ERROR finding exists and zero when the only findings are WARNINGs
    (feature F-4, ruling R22). A stray editor swap file is a V6 warning and must never fail a
    build. The verdict is `report.is_valid`, decided by the use case — this command reports it and
    does not recompute it.
    """
    with _run(as_json):
        report = validate_library(_open(ctx))
        _emit(report, as_json, rendering.render_validation_report)
        raise typer.Exit(OK if report.is_valid else VALIDATION_FAILED)


@app.command("collections")
def collections_command(
    ctx: typer.Context,
    key: Annotated[
        str | None, typer.Argument(help="A collection key. Omit to list every collection.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the JSON payload.")] = False,
) -> None:
    """List the declared collections, or show one with its members resolved.

    A declared member that resolves to nothing is listed as unresolved rather than dropped; it is
    also a V7 ERROR in `hl validate`.
    """
    with _run(as_json):
        repository = _open(ctx)
        if key is None:
            _emit(list_collections(repository), as_json, rendering.render_collection_list)
        else:
            _emit(get_collection(repository, key), as_json, rendering.render_collection_detail)


@app.command("mcp")
def mcp_command(ctx: typer.Context) -> None:
    """Serve this library to an MCP client over stdio. Read-only; four tools.

    A client spawns this command and speaks JSON-RPC to it on stdin and stdout, so **stdout is the
    transport and carries nothing else** (charter §11). Every diagnosis and every log line goes to
    stderr, including the loud failure on a directory that is not a library: a byte of prose on
    stdout would reach the client as a malformed frame and kill the connection with nothing in it
    to diagnose.

    Composition happens here, above `mcp/`: the library is resolved by contract C-8's precedence
    like every other command and handed in ready, so the server cannot be pointed at a different
    library from the one `hl list` shows (ruling R28).

    **The import is deferred into the body on purpose**, and it is the only one in this module that
    is. The MCP SDK costs ~1.3 s to import and this is the only command that touches it; at module
    scope every `hl list`, `hl show`, `hl search`, `hl validate` and `hl collections` paid for it
    too. T-9 measured the whole of `hl list` at 2.2 s against a 16 ms scan, so 99 % of what a user
    waited for was an import for a command they had not run. Deferring it is invisible to `hl mcp`,
    which pays the same cost either way, and the layer contract is unmoved: `cli` sits above `mcp`
    (R28) whether the import is written here or at the top of the file, and `import-linter` reads
    both.
    """
    from harness_library.mcp import serve_stdio

    with _run(as_json=False):
        serve_stdio(_open(ctx))


# ------------------------------------------------------------------------------------------------
# The write path — six commands over ten use cases (T-22)
# ------------------------------------------------------------------------------------------------

TargetOption = Annotated[
    Path | None,
    typer.Option(
        "--target",
        help="The directory to install into. Defaults to ~/.claude. Never created (R71).",
        show_default=False,
    ),
]
"""`--target`, spelled once. Ruling R43 makes a target an explicit parameter of every write."""

JsonOption = Annotated[bool, typer.Option("--json", help="Emit the JSON payload.")]


@app.command("install")
def install_command(
    ctx: typer.Context,
    artifact_id: Annotated[
        str | None,
        typer.Argument(
            help="With --resolve: the one artifact to settle. Meaningless without it.",
            show_default=False,
        ),
    ] = None,
    target: TargetOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the plan and write nothing at all.")
    ] = False,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="Also remove installed files the library no longer holds."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Install an artifact that does not validate. Not V11 (R99)."),
    ] = False,
    resolve: Annotated[
        ResolveSide | None,
        typer.Option(
            "--resolve",
            help=(
                "Settle one artifact's refused paths, after the install. "
                "'library' writes the library's version over yours. "
                "'target' KEEPS your copy and repairs the record — it settles the refusal and "
                "does NOT pin the file, so the NEXT hl install writes the library's version "
                "over the copy you kept (there is no keep-mine-forever). "
                "'edit' opens both versions in $EDITOR and decides nothing."
            ),
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Install this library into a target, and say what it would not do.

    **Everything safe is written and everything that needs a decision is left exactly as it is**
    (DEC-11, F-9). An artifact whose target copy was edited out of band, one the library and the
    target disagree about, one that does not validate (R75) and one whose root is a symlink (V11,
    R46) are each named in the report with a reason, untouched, and the run exits
    `INCOMPLETE = 6` — which is not a failure.

    A backup is taken before the first byte and the run refuses to start without one (F-9), the
    record is written before the first file so that a crash can only ever over-claim (R63), and
    the whole of it is under this target's single-writer lock (R50).

    **`--resolve` needs an artifact and runs after the install.** `NothingToResolveError` is
    therefore raised *after* the install has happened when the artifact turns out to be refusing
    nothing — the install is not undone, and `hl diff` says what is actually refused.
    """
    with _run(as_json):
        _check_install_arguments(artifact_id, resolve, dry_run=dry_run, as_json=as_json)
        library = _open(ctx)
        session = open_target(target)
        plan = _plan(library, session, manifest=session.manifest, force=force)
        rendered = payloads.PlanPayload.of(plan, target_path=session.target_path)

        if dry_run:
            dry = payloads.InstallPayload.of_plan(rendered, prune=prune, force=force)
            _emit(dry, as_json, rendering.render_install)
            raise typer.Exit(OK if dry.is_complete else INCOMPLETE)

        result = apply_install(
            plan,
            library,
            session.target,
            session.backups,
            session.manifests,
            lock=session.lock,
            manifest=session.manifest,
            target_path=session.target_path,
            installed_at=_now(),
            prune=prune,
        )

        resolution: payloads.ResolutionPayload | None = None
        left_alone = result.left_alone
        if resolve is not None and artifact_id is not None:
            resolution, left_alone = _settle(
                library, session, result, artifact_id=artifact_id, side=resolve, force=force
            )
        complete = not left_alone and (resolution is None or resolution.is_complete)

        payload = payloads.InstallPayload.of_apply(
            result,
            rendered,
            prune=prune,
            force=force,
            left_alone=left_alone,
            resolution=resolution,
            is_complete=complete,
        )
        _emit(payload, as_json, rendering.render_install)
        raise typer.Exit(OK if complete else INCOMPLETE)


@app.command("diff")
def diff_command(
    ctx: typer.Context, target: TargetOption = None, as_json: JsonOption = False
) -> None:
    """Report the drift between this library, the record and a target. Reads; writes nothing.

    `diff_against_target`, the **read** use case, so this command takes no lock (R85) and cannot
    reach the write path at all. It therefore describes a target an install is midway through
    writing, which charter §12 states rather than fixes.

    **Exits 0 whatever it finds**, like `hl list`: this is a report. `hl install --dry-run` is the
    command whose exit status says whether the plan can be applied without a decision — it runs
    the write-side planner and so also names the artifacts install would refuse.
    """
    with _run(as_json):
        library = _open(ctx)
        session = open_target(target)
        plan = diff_against_target(library, session.target, manifest=session.manifest)
        _emit(
            payloads.PlanPayload.of(plan, target_path=session.target_path),
            as_json,
            rendering.render_plan,
        )


@app.command("uninstall")
def uninstall_command(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument(help="The artifact's `<type>/<name>` id.")],
    target: TargetOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove exactly the files the record names for one artifact, and nothing beside them.

    The list of paths comes from the manifest and from nowhere else — not a walk of the
    artifact's directory — so a file this tool did not install survives without anything here
    having to know it exists (F-12, R44). A backup is taken first, so `hl rollback` undoes it.

    An emptied directory is left behind: removing it would mean deciding that nothing else in it
    matters, which is the decision this command exists not to make.
    """
    with _run(as_json):
        session = open_target(target)
        result = uninstall_artifact(
            session.target,
            session.backups,
            session.manifests,
            lock=session.lock,
            manifest=_installed(session, "uninstall from"),
            artifact_id=artifact_id,
            installed_at=_now(),
        )
        _emit(
            payloads.UninstallPayload.of(result, target_path=session.target_path),
            as_json,
            rendering.render_uninstall,
        )


@app.command("rollback")
def rollback_command(
    ctx: typer.Context,
    backup_id: Annotated[
        str | None,
        typer.Argument(help="Which backup to put back. Omit for this target's most recent."),
    ] = None,
    target: TargetOption = None,
    as_json: JsonOption = False,
) -> None:
    """Put a target back the way it was before an install, an uninstall, a prune or a clean.

    **Not an uninstall.** Uninstall removes what this tool installed; a rollback restores what
    was *there*, whoever put it there — and removes again what a first install created (R79),
    which is what makes the very first install undoable.

    Omitting the id takes this target's most recent backup. Naming one takes that one, which is
    the difference between undoing the last install and undoing three; `BackupStore` keeps them
    all.
    """
    with _run(as_json):
        session = open_target(target)
        manifest = _installed(session, "roll back")
        chosen = _backup_id(session, manifest, backup_id)
        if chosen is None:
            # Ruling R112. Not a failure, so not raised: the payload goes to stdout naming no
            # backup and the command exits 0, which is `INCOMPLETE`'s shape and `hl clean`'s.
            _emit(
                payloads.RollbackPayload.of_nothing(target_path=session.target_path),
                as_json,
                rendering.render_rollback,
            )
            return
        result = rollback_install(
            session.target,
            session.backups,
            session.manifests,
            lock=session.lock,
            manifest=manifest,
            backup_id=chosen,
            installed_at=_now(),
        )
        _emit(
            payloads.RollbackPayload.of(result, target_path=session.target_path),
            as_json,
            rendering.render_rollback,
        )


@app.command("backups")
def backups_command(
    ctx: typer.Context,
    target: TargetOption = None,
    as_json: JsonOption = False,
) -> None:
    """List this target's rollback points, with the ids `hl rollback` takes. Ruling R113.

    A backup is taken before anything is written, removed or restored, and kept — nothing here
    deletes one. `hl rollback` with no id puts back the last row; naming one puts back that one,
    which is the difference between undoing the last install and undoing three.

    Reads only, so it takes **no lock** (R85) and needs no manifest: a target whose record was
    deleted still has its backups, and that is exactly when a user comes looking for them.
    """
    with _run(as_json):
        session = open_target(target)
        _emit(
            payloads.BackupsPayload.of(
                list_backups(session.backups, target_path=session.target_path),
                target_path=session.target_path,
            ),
            as_json,
            rendering.render_backups,
        )


@app.command("clean")
def clean_command(
    ctx: typer.Context,
    target: TargetOption = None,
    foreign: Annotated[
        bool,
        typer.Option("--foreign", help="Act on paths neither the library nor the record knows."),
    ] = False,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="Act on installed paths the library no longer holds."),
    ] = False,
    remove: Annotated[
        bool, typer.Option("--remove", help="Actually delete the listed paths. Off by default.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """List what this target holds that nothing wants any more — and delete it only when asked.

    **The listing is the safety model** (ruling R96, C-9). Without `--remove` nothing is deleted;
    with it, the whole listing is produced and backed up before the first file goes, so a failure
    part-way through still leaves a complete statement of what was going to.

    Two selectors, because they are two different facts and two different risks. `--foreign` is
    the default: paths neither the library nor the record knows — a user's `settings.json`, an
    editor swap file, Claude Code's own `synced/` bucket. **None of them can be rebuilt from
    anything**, so the backup taken here is the only way back that will ever exist, and there is
    no named exclusion anywhere in this tool protecting any of them (R44) — they are protected by
    being shown to you first. `--prune` is the other: files this tool installed and the library
    has since dropped, which are safe only because a path whose copy was edited comes back
    `conflict` instead.
    """
    with _run(as_json):
        if foreign and prune:
            raise typer.BadParameter(
                "--foreign and --prune name two different sets of paths with two different "
                "risks, and they are removed under two different record orderings. Run one, "
                "look at what it says, then run the other",
                param_hint="--prune",
            )
        library = _open(ctx)
        session = open_target(target)
        manifest = _installed(session, "clean")
        plan = _plan(library, session, manifest=manifest, force=False)

        payload: payloads.CleanPayload
        if prune:
            if remove:
                pruned = prune_target(
                    plan,
                    session.target,
                    session.backups,
                    session.manifests,
                    lock=session.lock,
                    manifest=manifest,
                    installed_at=_now(),
                )
                payload = payloads.CleanPayload.of_prune(pruned, target_path=session.target_path)
            else:
                payload = payloads.CleanPayload.of_prunable(
                    pruned_entries(plan), target_path=session.target_path
                )
        else:
            cleaned = clean_foreign(
                plan,
                session.target,
                session.backups,
                session.manifests,
                lock=session.lock,
                manifest=manifest,
                installed_at=_now(),
                remove=remove,
            )
            payload = payloads.CleanPayload.of_clean(
                cleaned, target_path=session.target_path, removed_requested=remove
            )
        _emit(payload, as_json, rendering.render_clean)


@app.command("export")
def export_command(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="The collection key, as `library.yaml` declares it.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Where to write the archive. Defaults to ./<key>.zip."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Write one collection's artifacts to a plain zip. Feature F-16, ruling R45.

    Exactly the collection's artifacts' files and nothing else: no manifest inside the archive,
    no `library.yaml`, no metadata sidecar. The entry names are **target-relative paths**, so the
    archive unzips over a harness and lands where the same artifacts would have installed.

    Two exports of one unchanged library are byte-identical — each entry is timestamped from the
    artifact rather than from the clock — so two of them can be compared. A member that resolves
    to nothing contributes no entry and is reported; it is also a V7 error in `hl validate`.
    """
    with _run(as_json):
        exported = export_collection(_open(ctx), key)
        destination = output if output is not None else Path(f"{exported.key}.zip")
        _write_archive(destination, exported.data)
        _emit(
            payloads.ExportPayload.of(exported, output=str(destination)),
            as_json,
            rendering.render_export,
        )


# ------------------------------------------------------------------------------------------------
# The write path's plumbing. It composes and translates; it decides nothing
# ------------------------------------------------------------------------------------------------


def _now() -> datetime:
    """When this run happened. **The composition root owns the instant** (ruling R66).

    Every write use case takes `installed_at` as a parameter and none of them reads a clock, so
    that an assertion about the record one of them writes never depends on when the suite ran.
    This is the one call that reads the real one.
    """
    return datetime.now(UTC)


def _plan(
    library: ArtifactRepository,
    session: TargetSession,
    *,
    manifest: Manifest | None,
    force: bool,
) -> InstallPlan:
    """The write-side plan, with V11's unscannable roots handed in. Rulings R46, R53, R75.

    `symlinked_roots()` is passed at every call site rather than defaulted inside `plan_install`,
    because C-4's member and the refusal are two facts that must survive each other being
    dropped: the warning is on `AssembledLibrary.findings` and the refusal is built from these
    values, and wiring one through the other would make each untestable without the other.
    """
    return plan_install(
        library,
        session.target,
        manifest=manifest,
        unscannable=library.symlinked_roots(),
        force=force,
    )


def _settle(
    library: ArtifactRepository,
    session: TargetSession,
    result: ApplyResult,
    *,
    artifact_id: str,
    side: ResolveSide,
    force: bool,
) -> tuple[payloads.ResolutionPayload, tuple[PlanEntry, ...]]:
    """Run `--resolve` after the apply, and say whether the whole command is complete.

    **The plan is recomputed and the manifest comes from `result`** — the record the apply just
    wrote, never `session.manifest`, which was read before the command started. `ManifestStore`
    has one member (C-15), so there is no way for `application/` to refresh it and this is the
    only place the hand-off can happen. Given the stale one, `_manifest_after_resolve` copies
    over an `artifacts` tuple that never heard of anything the apply installed, and every file it
    just wrote is disowned.

    **Sequential, never nested.** The apply released this target's lock when it returned and the
    resolution takes it again; a second acquire inside the first is refused outright, because the
    lock is per target rather than per process (C-16).

    Returns:
        The payload, and **what the apply left alone that this resolution did not take on**.
        Subtracting the resolved artifact's entries is what keeps the report honest: those paths
        were refused by the apply and have since been decided, and the resolution's own payload
        carries whatever it could not take. Every refused path therefore appears exactly once,
        and the caller's completeness test is the ordinary "nothing left alone".

        A comparison settles nothing, so `edit` hands back the apply's list untouched and the
        run stays incomplete — which is the honest answer to "I looked at it".
    """
    replanned = _plan(library, session, manifest=result.manifest, force=force)

    if side is ResolveSide.EDIT:
        with tempfile.TemporaryDirectory(prefix="hl-resolve-") as workspace:
            # Outside the target, and removed however the run ends: nothing is read back from an
            # editor (R54), so whatever the user leaves in the buffer goes with the directory.
            comparison = compare_versions(
                replanned,
                library,
                session.target,
                open_editor(Path(workspace)),
                lock=session.lock,
                artifact_id=artifact_id,
            )
        return (
            payloads.ResolutionPayload.of_comparison(comparison, side=side.value),
            result.left_alone,
        )

    resolved = resolve_conflict(
        replanned,
        library,
        session.target,
        session.backups,
        session.manifests,
        lock=session.lock,
        manifest=result.manifest,
        artifact_id=artifact_id,
        resolution=Resolution(side.value),
        target_path=session.target_path,
        installed_at=_now(),
    )
    return (
        payloads.ResolutionPayload.of_resolution(resolved),
        tuple(entry for entry in result.left_alone if entry.artifact_id != artifact_id),
    )


def _check_install_arguments(
    artifact_id: str | None, resolve: ResolveSide | None, *, dry_run: bool, as_json: bool
) -> None:
    """The four combinations `hl install` will not accept. Exit 2, before anything is opened.

    Raises:
        typer.BadParameter: an artifact without `--resolve` (install already installs every
            artifact, so naming one would silently mean something it does not); `--resolve`
            without an artifact (resolution is per artifact and never per run, R54);
            `--resolve` with `--dry-run`, which would have to write the record it promises not
            to write; or `--resolve edit` with `--json`.

            **The last one is charter §11, not tidiness.** An editor is a terminal program and
            inherits this process's stdout — that is what makes a TUI editor usable at all — so
            its output lands on the channel `--json` promises carries one payload and nothing
            else. There is no way to have both and no sense in wanting them: a caller parsing
            JSON is not sitting in front of the editor it would be waiting for.
    """
    if resolve is None and artifact_id is not None:
        raise typer.BadParameter(
            "hl install installs every artifact in the library. Naming one is only meaningful "
            "with --resolve library|target|edit, which settles that one artifact's refused paths",
            param_hint="ARTIFACT_ID",
        )
    if resolve is not None and artifact_id is None:
        raise typer.BadParameter(
            "resolution is per artifact and never per run (R54): name the artifact to settle. "
            "hl diff lists the paths this target refuses and whose they are",
            param_hint="--resolve",
        )
    if resolve is not None and dry_run:
        raise typer.BadParameter(
            "--resolve writes a record, so there is no dry run of it. Use hl install --dry-run "
            "to see what is refused, then run --resolve on one artifact",
            param_hint="--dry-run",
        )
    if resolve is ResolveSide.EDIT and as_json:
        raise typer.BadParameter(
            "$EDITOR takes over this terminal and writes to the same stdout --json promises "
            "carries one payload and nothing else. Run --resolve edit on its own, then "
            "--resolve library|target --json with the decision you reached",
            param_hint="--json",
        )


def _installed(session: TargetSession, operation: str) -> Manifest:
    """This target's manifest, or a refusal. **Never a default and never an empty one.**

    Charter §13's posture, at its sharpest. Uninstall, rollback, prune and clean each act on a
    record, and an absent record is not an empty one: `clean --foreign` against a target nothing
    was ever installed into means *"every path here is foreign, remove them all"* — `rm -rf`
    reached through a plan. `clean_foreign` deliberately makes that inexpressible by requiring a
    manifest and says the answer belongs here; this is the answer.

    Raises:
        TargetNotInstalledError: nothing has been installed into this target. `ARTIFACT_NOT_FOUND`
            and exit 3, `NothingToResolveError`'s reading of that code: the thing you asked to act
            on is not here, so go and look at what is.
    """
    if session.manifest is None:
        raise TargetNotInstalledError(session.root, operation)
    return session.manifest


def _backup_id(session: TargetSession, manifest: Manifest, requested: str | None) -> str | None:
    """Which backup to put back: the one named, this target's most recent, or **none at all**.

    `list_backups` is the filter and it lives in `application/read/` (R113): `BackupStore.list()`
    returns **every** target's backups (R43), a user who installs into two directories must not
    roll one back over the other, and `hl backups` needs the same definition of "this target's"
    that this choice uses.

    **Ruling R112 — "there is nothing to put back" is a fact, and the record is what tells it
    from a failure.** A run that wrote nothing takes no backup: a `MANIFEST_REPAIR`-only install
    is the common case, and answering `hl rollback` after one with `BACKUP_FAILED` told a script
    *the backup could not be taken* about a run that needed none. So the two are separated by
    `Manifest.backup_id`, which is C-11's record of the backup the last run took:

    * no backup here, and the record claims none — nothing happened, so there is nothing to
      undo. `None`, and the caller reports it and exits 0.
    * no backup here, and the record **names one** — that backup is missing, which is a failure
      and keeps `BACKUP_FAILED`. This branch is why the predicate is not simply "the store is
      empty": a backup written by an older build is one this reader declines to offer (see
      `infrastructure/backup.py`'s `SCHEMA_VERSION`), and reporting *nothing to put back* for a
      rollback point still sitting on the user's disk would be the tool lying about its own undo.

    Raises:
        BackupNotFoundError: the record names a backup this target does not have. A named id
            that does not exist is not checked here at all: the store decides that, and it also
            decides that a directory with no readable record is not a backup.
    """
    if requested is not None:
        return requested
    mine = list_backups(session.backups, target_path=session.target_path)
    if mine:
        return mine[-1].backup_id
    if manifest.backup_id is None:
        return None
    raise BackupNotFoundError(manifest.backup_id)


def _write_archive(destination: Path, data: bytes) -> None:
    """Put the export where the user asked for it.

    Raises:
        TargetUnwritableError: the archive could not be written. The **archive's** destination
            and not the install target — the two share a status because they share a remedy,
            which is to look at the path that was passed. Flagged for a ruling: C-14's status 7
            is named for the install target, and an export has no install target at all.
    """
    try:
        destination.write_bytes(data)
    except OSError as error:
        raise TargetUnwritableError(str(destination), str(error)) from error


def _open(ctx: typer.Context) -> ArtifactRepository:
    """The library this invocation is about. Contract C-8's precedence, applied once per command."""
    context: CliContext = ctx.ensure_object(CliContext)
    return open_library(context.library)


def _emit[PayloadT: Payload](
    payload: PayloadT, as_json: bool, render: Callable[[PayloadT, TextIO], None]
) -> None:
    """Write one payload, in whichever of the two renderings was asked for.

    `sys.stdout` is looked up at call time rather than captured at import, so a test runner that
    replaces the stream sees the output — the same reason `cli.logging` resolves `sys.stderr` late.
    """
    if as_json:
        rendering.emit_json(payload, sys.stdout)
    else:
        render(payload, sys.stdout)


@contextmanager
def _run(as_json: bool) -> Iterator[None]:
    """Turn every failure in the taxonomy into a diagnosis on stderr and an exit status.

    Contract C-6 lives here: the status comes from the **table**, keyed by `error.code`, so adding
    a code to the taxonomy without giving it a status fails a test rather than silently exiting
    with whatever the last branch happened to return.

    Diagnoses go to **stderr in both modes** (charter §11). stdout carries payloads and nothing
    else, so `hl list --json | jq` is as safe on the failure path as on the success path, and
    `hl mcp`'s stdout-purity requirement is not a special case bolted on later.

    `LibraryRootError` had a branch of its own until **ruling R29** gave it `NOT_A_LIBRARY`. It is
    now an ordinary member of the taxonomy, so the special case is gone: keeping it would report
    `code: null` for a condition that has a code, which is the taxonomy lying about itself.
    """
    try:
        yield
    except HarnessLibraryError as error:
        _fail(
            code=error.code.value,
            message=str(error),
            status=exit_status_for(error.code),
            as_json=as_json,
        )


def _fail(*, code: str | None, message: str, status: int, as_json: bool) -> None:
    """Write the diagnosis to stderr and leave with `status`."""
    if as_json:
        # JSON in, JSON out — including on the failure path, so a wrapper parses one format
        # instead of sniffing whether the run succeeded before deciding how to read stderr.
        sys.stderr.write(json.dumps({"error": {"code": code, "message": message}}) + "\n")
    else:
        prefix = f"error [{code}]" if code is not None else "error"
        sys.stderr.write(f"{prefix}: {message}\n")
    raise typer.Exit(status)


__all__ = ["app", "main"]


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    app()
