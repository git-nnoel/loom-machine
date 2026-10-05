# Loom — a walkthrough

From nothing, to a library you can read, to an install you can undo.

Everything below was run against this repository on 2026-10-05. Where output is shown, it is real.

---

## 1. Install the tool

Loom needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/git-nnoel/loom-machine.git
cd loom-machine
uv sync
```

That puts the `loom` command in `.venv/bin/`. It is **not** on your `PATH` by default:

```bash
export PATH="$PWD/.venv/bin:$PATH"   # or: alias loom='uv run loom'
loom --help
```

---

## 2. Understand the two trees

Loom only makes sense once you have these straight.

| | What it is | Example |
|---|---|---|
| **The library** | Where you *author*. Canonical, versioned in git. | this repo, or your own |
| **The target** | Where a harness *reads from*. Derived, overwritable. | `~/.claude/` |

The library is the source of truth. A target is a copy Loom writes and can take back.

A library has `skills/<name>/SKILL.md` and `agents/<name>.md`, plus an optional `library.yaml`.
A target has the same layout and usually a lot of other things Loom will never touch.

**Tell Loom where the library is** — once, in your shell:

```bash
export LOOM_LIBRARY=~/code/my-library
```

Or pass `--library <path>` per command. It is never guessed from the current directory.

---

## 3. Read your library

Try these against this repo's test fixtures, which are deliberately full of broken artifacts:

```bash
loom --library tests/fixtures/library list
```

```
ID                          KIND       STATUS   TAGS               SUPERSEDED BY         FILES
skill/broken-links          directory  INVALID  -                  -                     2
skill/delivery-lead         directory  ok       process, planning  -                     2
...
skill/legacy-orchestration  directory  ok       -                  skill/delivery-lead   1

11 artifact(s), sorted by name.
```

Superseded artifacts are listed last and labelled, never hidden.

| Command | What it does |
|---|---|
| `loom list` | Every artifact. `--type`, `--tag`, `--collection`, `--invalid-only`, `--sort`, `--no-superseded` |
| `loom show <id>` | One artifact: its text, files, frontmatter and any findings |
| `loom search <query>` | Across entry documents and `.md` references, with the line either side |
| `loom validate` | Every rule violation, with the rule code |
| `loom collections` | The sets declared in `library.yaml` |

All of them take `--json`. **`--json` is the stable contract; the columnar text is not** — script against the JSON.

### `loom validate` is the one to run first

```bash
loom --library tests/fixtures/library validate
```

It reports eleven rules. The ones worth knowing:

| | Catches |
|---|---|
| **V1** | A skill directory with no `SKILL.md` — it loads as nothing and nobody tells you |
| **V2** | Frontmatter `name` disagreeing with the directory name |
| **V3** | A cited `references/…` path that does not exist |
| **V10** | Frontmatter that does not parse — usually an unquoted `:` in a description |
| **V11** | A symlinked artifact root, which is never followed and would otherwise be invisible |

A **WARNING** never blocks an install. An **ERROR** does.

Exit code is non-zero when any ERROR exists, so `loom validate` works in CI as-is.

---

## 4. Declare metadata with `library.yaml`

Optional, and it buys three things the files cannot express: tags, collections, and supersession.

```yaml
artifacts:
  skill/delivery-lead:
    tags: [orchestration, process]
    collections: [delivery]
  skill/developers-orchestration:
    superseded_by: skill/delivery-lead

collections:
  delivery:
    title: The delivery chain
    description: Spec to shipped code.
    members:
      - skill/solution-designer
      - skill/delivery-lead
      - agent/backend-developer-specialist
```

**Supersession is not cosmetic.** A redirect stub's whole body is prose about its successor,
including that successor's reference paths — so without `superseded_by`, V3 reports every one of
those as a broken link. Declaring it clears them.

---

## 5. Serve the library over MCP

A read-only MCP server exposes the library to any client. **Nothing can write through it** — that
guarantee is enforced by an import contract that fails the build, not by convention.

The client spawns it; you never start it yourself. Add to `~/.claude/settings.json` (or a project
`.mcp.json`):

```json
{
  "mcpServers": {
    "loom": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/loom-machine", "loom", "mcp"],
      "env": { "LOOM_LIBRARY": "/absolute/path/to/your-library" }
    }
  }
}
```

Restart the client. Four tools appear:

| Tool | For |
|---|---|
| `list_artifacts` | Everything, filterable by type and tag |
| `search_artifacts` | Full text across entry documents and `.md` references |
| `get_artifact` | One artifact's entry text and file list |
| `get_reference` | **One reference file, without its parent** |

`get_reference` is the one that matters for context. A reference-heavy skill can be 700 lines
before its references; pulling one costs a fraction of pulling the skill.

> **`loom mcp` writes nothing but JSON-RPC to stdout.** A single stray byte kills the client
> connection with no diagnosable error, so all logging goes to stderr. If you extend the server,
> keep it that way — there is a test that proves it.

---

## 6. Install into a harness

This is the part that replaces copying directories by hand.

### Always look first

```bash
loom install --target ~/.claude --dry-run
```

Nothing is written. You get a plan, one row per path:

| Verdict | Meaning |
|---|---|
| `create` | Not in the target yet — will be written |
| `update` | The target holds what Loom last installed; the library moved on |
| `unchanged` | Already correct |
| `local_edit` | **You edited it.** Refused, not overwritten |
| `conflict` | Both moved. Refused |
| `skipped` | Will not install — a failing artifact, or a symlinked root |
| `foreign` | Not Loom's. **Never touched** |
| `prune` | Loom installed it; the library dropped it |
| `manifest_repair` | Content already matches; only the record was stale |

### Then install

```bash
loom install --target ~/.claude
```

Three guarantees, in this order:

1. **A backup is taken before anything is written.** If it cannot be taken, the run refuses.
2. **The record is written before the files.** A crash mid-install leaves the record *over*-claiming,
   which shows up as `local_edit` next time and asks you. The other order would leave your files
   claimed by nobody and unrecoverable.
3. **Foreign paths are never touched.** Your `settings.json`, Claude Code's own `synced/` bucket,
   an editor swap file — all left exactly alone.

If anything was refused, the run exits **6** and says so:

```
INCOMPLETE: the entries above were left alone. Nothing was destroyed —
decide each one with loom install --resolve library|target|edit <artifact>.
```

Safe paths are still written. Only the refused ones wait for you.

### Settle a refusal

```bash
loom install --target ~/.claude --resolve library skill/delivery-lead   # take the library's copy
loom install --target ~/.claude --resolve target  skill/delivery-lead   # keep yours
loom install --target ~/.claude --resolve edit    skill/delivery-lead   # open both in $EDITOR
```

> **`--resolve target` does not pin the file.** It settles *this* refusal by recording your copy as
> the installed version. The **next** plain `loom install` will then write the library's version
> over it, because that is what "installed" now means. If you want to keep an edit permanently,
> keep it in the library.

### Other write commands

```bash
loom diff      --target ~/.claude        # the plan, read-only, always exits 0
loom uninstall skill/foo --target ~/.claude
loom backups   --target ~/.claude        # ids you can pass to rollback
loom rollback  --target ~/.claude        # most recent, or name a backup id
loom clean --foreign --target ~/.claude  # LISTS only
loom clean --foreign --remove --target ~/.claude
loom export --collection delivery -o delivery.zip
```

`loom clean --foreign` is the only command that deletes files Loom never wrote. It **lists by
default** and removes only with `--remove`, and it takes a backup first.

---

## 7. Undo anything

```bash
loom backups --target ~/.claude
```

```
BACKUP ID               TAKEN                             PATHS  BYTES  LINKS
2026-09-21T20-55-14Z    2026-09-21T20:55:14.112445+00:00  1      0      0
2026-09-21T20-55-14Z-2  2026-09-21T20:55:14.938818+00:00  2      2      0
```

```bash
loom rollback --target ~/.claude                          # the most recent
loom rollback 2026-09-21T20-55-14Z --target ~/.claude     # a specific one
```

A rollback restores **content, permissions and symlinks**, and removes paths the target did not
hold before the install — so even a first install into an empty target is undoable.

Backups live in `~/.local/state/loom/backups/`, outside both trees, so neither a `git clean` nor a
target wipe destroys them. Nothing deletes them yet; that is still to come.

---

## 8. Exit codes

Scriptable, and stable.

| | |
|---|---|
| 0 | Done |
| 1 | `loom validate` found an ERROR |
| 2 | Usage error |
| 3 | Not found |
| 4 | Bad request |
| 5 | Not a usable library |
| **6** | **`INCOMPLETE` — something was left alone and needs your decision** |
| 7 | Target unwritable |
| 8–15 | Manifest, backup, lock, editor and state-directory failures |

**6 is the one to branch on.** It means *you must decide*, never *it broke*.

---

## 9. A first real run, safely

```bash
cp -r ~/.claude /tmp/claude-rehearsal          # rehearse on a copy
loom --library ~/code/my-library validate
loom --library ~/code/my-library install --target /tmp/claude-rehearsal --dry-run
loom --library ~/code/my-library install --target /tmp/claude-rehearsal
loom rollback --target /tmp/claude-rehearsal   # prove you can undo it
```

Then do it for real. `--target` defaults to `~/.claude`, and a missing target directory is an error
rather than something Loom creates — a typo cannot build a tree somewhere unexpected.
