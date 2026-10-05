# Loom

**The canonical home for the skills and agents you write — browse them, check them, install them anywhere, reversibly.**

Loom exists because copying directories by hand destroys things quietly. A swap file here, an
edit there, and nothing tells you until you go looking.

You author your skills and agents once, in one versioned tree. Loom validates them, installs
them into `~/.claude` — or any other directory — as a plan you can read before a single byte
moves, and can put everything back afterwards. It also speaks MCP, so any LLM session can read
a skill without installing anything at all.

No server. No account. Git distributes it.

---

## What it does

```console
$ loom validate
skill/frontend-system-pattern  [INVALID]  skills/frontend-system-pattern
  V10 ERROR: the frontmatter of SKILL.md does not parse at line 3, column 255:
             mapping values are not allowed in this context

9 artifact(s) checked: INVALID. 1 error(s), 0 warning(s).
```

```console
$ loom install --dry-run --target ~/.claude
DRY RUN — nothing was written.

VERDICT   PATH                                      ARTIFACT
create    skills/delivery-lead/SKILL.md             skill/delivery-lead
update    agents/scribe.md                          agent/scribe
conflict  skills/notes/SKILL.md                     skill/notes
foreign   skills/synced/.bucket-7c1f9a2e            -

INCOMPLETE: the entries above were left alone. Nothing was destroyed —
decide each one with loom install --resolve library|target|edit <artifact>.
```

Three promises, and the tests hold them to each one:

- **Inspectable before it runs.** Every path gets a verdict from three hashes — what the library
  has, what was last installed, what is on disk now. `--dry-run` writes nothing.
- **Reversible after it runs.** Every write is backed up first, contents *and* permissions.
  `loom rollback` puts it back.
- **Incapable of destroying what it did not write.** A foreign path is reported and left alone.
  Removing one is a separate, deliberate act that lists before it acts.

---

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```console
$ git clone https://github.com/git-nnoel/loom-machine.git
$ cd loom-machine
$ uv sync
$ uv run hl --help
```

---

## Commands

### Reading

| | |
|---|---|
| `list` | Every artifact, with filters by type, tag, collection or validity |
| `show` | One artifact — its text, its files, its findings |
| `search` | Across entry documents and markdown references |
| `validate` | Eleven rules; exits non-zero on any error |
| `collections` | Named sets of artifacts, declared in `library.yaml` |
| `export` | A collection as a zip |

### Writing

| | |
|---|---|
| `diff` | What would change in a target, and why |
| `install` | Apply the plan. `--dry-run`, `--prune`, `--force`, `--resolve`, `--target` |
| `uninstall` | Remove one artifact's files, by the record |
| `rollback` | Put a target back from a backup |
| `backups` | What can be rolled back to |
| `clean` | Remove foreign paths — lists them all before removing any |

### Serving

| | |
|---|---|
| `mcp` | A read-only MCP server over stdio. Four tools; any client can use it |

Every read command takes `--json`, which is a stable contract. The human columnar output is not.

---

## How it works

**The library is canonical. An install is derived.** You edit here; `~/.claude` is somewhere the
library gets written to, and overwriting it is always safe because the library is the truth.

```
loom-machine/
  skills/<name>/SKILL.md, references/*.md
  agents/<name>.md
  library.yaml          ← tags, collections, supersession
```

**Install is plan → review → apply.** Each path is judged on three hashes, and presence is
resolved before equality:

| Verdict | Means |
|---|---|
| `unchanged` · `update` · `create` | Safe. Written. |
| `local_edit` · `conflict` | You changed it. **Refused**, named, left alone. |
| `foreign` | Not ours. Never touched. |
| `skipped` | Can't be installed — fails validation, or its root is a symlink |
| `prune` · `manifest_repair` | Gone from the library · only the record was stale |

A run that leaves anything undecided exits **6** and tells you how to decide it.

**A record outside both trees** remembers what was installed, with per-file hashes and the
library's commit. It is written *before* the files when they appear and *after* them when they
disappear — so a crash can leave the record over-claiming, which self-corrects, but never
disowning a file that is still on disk, which cannot be recovered.

---

## Validation

Eleven rules, each closing a failure observed in a real library:

| | |
|---|---|
| **V1** | A skill directory with no `SKILL.md` — it loads as nothing, and nothing says so |
| **V2** | Frontmatter `name` disagreeing with the directory |
| **V3** | A cited `references/…` path that does not exist (exempt for redirect stubs) |
| **V4** | `superseded_by` pointing at nothing |
| **V5** | A missing or empty required key |
| **V6** | *warning* — a swap file, a vendor tree, a symlink inside an artifact |
| **V7** | A `library.yaml` entry naming no artifact |
| **V8** | Two artifacts differing only by case — one filesystem away from silently merging |
| **V9** | A duplicate `library.yaml` key, silently discarding the first |
| **V10** | Frontmatter that does not parse — reported as that, not as missing keys |
| **V11** | *warning* — a symlinked artifact root, otherwise invisible. Refuses to install |

---

## Development

One gate, run whole:

```console
$ uv run ruff format --check . && uv run ruff check . && uv run mypy src tests \
    && uv run lint-imports && uv run pytest
```

Clean Architecture, enforced structurally rather than by convention — `import-linter` contracts
run as tests, so `domain/` importing a framework or the MCP server reaching a write path fails
the suite.

```
cli/  mcp/        adapters — no logic
   application/   read/ and write/
   domain/        entities, protocols, pure rules — imports nothing
   infrastructure/
```

`tests/fixtures/` holds trees that reproduce every failure the rules exist to catch, including a
real symlink and a real binary. **They are never deleted.**

> **Note for Windows:** the fixtures include symlinks. Clone with developer mode enabled, or
> `git config core.symlinks true`.

---

## Status

| | |
|---|---|
| Store, validation, read path, MCP | **Done** |
| Install, backup, drift, rollback | **Done** |
| HTTP API | Planned |
| Web UI | Planned |

1090 tests. Design and delivery records live in `docs/specs/` and `docs/instructions/`.
