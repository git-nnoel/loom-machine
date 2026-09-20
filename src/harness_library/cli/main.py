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
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, TextIO

import typer

from harness_library.application.read import (
    ArtifactFilter,
    Payload,
    SortKey,
    get_collection,
    list_artifacts,
    list_collections,
    search_artifacts,
    validate_library,
)
from harness_library.application.read import (
    get_artifact as read_artifact,
)
from harness_library.cli import rendering
from harness_library.cli.composition import open_library
from harness_library.cli.exit_codes import OK, VALIDATION_FAILED, exit_status_for
from harness_library.cli.logging import configure_logging
from harness_library.domain.errors import HarnessLibraryError
from harness_library.domain.identity import ArtifactType
from harness_library.domain.repository import ArtifactRepository

app = typer.Typer(
    name="hl",
    help="Read, search and validate a Claude Code harness library.",
    no_args_is_help=True,
    add_completion=False,
)


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
