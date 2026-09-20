# T-9 — Acceptance against the real library

**Date:** 2026-09-01 · **Base:** `main` at `cd687cd` · **Author:** backend specialist
**Subject:** `~/.claude/` — six skills, two agents, 36 files, 668 406 bytes (652.7 KiB)

Every command below was run exactly as written and its output pasted verbatim. The `hl` console
script resolves only from `/project/harness-library/.venv/bin`; every session below prefixed
`export PATH="/project/harness-library/.venv/bin:$PATH"`.

---

## Headline verdict

| F | Claim | Verdict |
|---|---|---|
| **F-1** | Every artifact lists, invalid ones included; filters and sorts defined; superseded ranked below successors (R8) | **PASS** |
| **F-2** | `hl show` renders an invalid artifact with its findings rather than raising | **PASS** |
| **F-3** | ~~Phrase in a reference found with path/line/context~~; 184 KB HTML reported skipped as *not a markdown reference* | **PASS** |
| **F-4** | V1–V7 fire on purpose-built content; `hl validate` exits non-zero on ERROR | **PASS on mechanism, but see D-1** |
| **F-5** | `hl list --collection` returns exactly the declared members | **NOT PROVABLE HERE** — `~/.claude` declares no collections (L6) |
| **F-6** | Handshake enumerates four tools read from the server; each returns its payload; `get_reference` carries no parent entry text | **PASS** |

**The software does what F-1 through F-6 claim.** It also found three real faults in the real
library that nothing else had reported, which is the point. But the honest headline is narrower
than "green":

> Against real content, V3 fired 15 times. Seven are the redirect-stub findings we predicted and
> can exempt. **The other eight are false positives, and there were zero true positives.** V3's
> precision on this library, correctly configured, is 0/8.

That is D-1 below, and it is the most important thing in this document.

---

## What a run against `~/.claude` cannot tell you (L6)

`~/.claude` is a **target** layout, not a library layout. It has no `library.yaml`. Therefore:

- **tags** read empty for all eight artifacts — not "no tags declared", simply nothing to declare
  them in;
- **collections** read empty — `hl collections` prints *This library declares no collections*, and
  **F-5 is untestable against this tree**;
- **supersession** reads empty — the `SUPERSEDED BY` column is `-` for both redirect stubs, R8's
  ranking never engages, and V3's exemption cannot fire. This is the whole of deliverable 2.

Additionally, `~/.claude` is not a git work tree, so R5 takes its mtime fallback for every artifact
and **`is_dirty` is `true` for all eight** (L22). That is R5's documented first fallback, not a
defect and not a statement about the content.

A green line from this tree therefore proves less than it looks like it proves, and three of the
six features are only partly exercised by it.

---

## 1. The finished CLI against the real library, read-only

### `hl --library ~/.claude list`

```
ID                                   KIND       STATUS   TAGS  SUPERSEDED BY  FILES
agent/backend-developer-specialist   file       INVALID  -     -              1
skill/backend-system-architecture    directory  ok       -     -              8
skill/delivery-lead                  directory  ok       -     -              7
skill/developers-orchestration       directory  INVALID  -     -              1
skill/frontend-ctg-system-pattern    directory  INVALID  -     -              2
agent/frontend-developer-specialist  file       INVALID  -     -              1
skill/frontend-system-pattern        directory  INVALID  -     -              9
skill/solution-designer              directory  ok       -     -              7

8 artifact(s), sorted by name.
```

Exit code `0`. All eight artifacts appear, five of them invalid — **nothing is hidden because it is
broken**, which is F-1's core claim and the failure the product exists to close.

### `hl --library ~/.claude list --json`

Contract C-7 fields, one row per artifact (findings elided to their codes):

```
id                                   | is_dirty | updated_at           | tags | superseded_by | is_valid | findings
agent/backend-developer-specialist   | True     | 2026-08-25T18:03:58Z | []   | None          | False    | V3 ×7
skill/backend-system-architecture    | True     | 2026-08-25T18:03:34Z | []   | None          | True     | —
skill/delivery-lead                  | True     | 2026-08-25T18:03:28Z | []   | None          | True     | —
skill/developers-orchestration       | True     | 2026-08-25T18:03:26Z | []   | None          | False    | V3 ×6
skill/frontend-ctg-system-pattern    | True     | 2026-08-25T18:03:30Z | []   | None          | False    | V3 ×1
agent/frontend-developer-specialist  | True     | 2026-08-25T18:03:54Z | []   | None          | False    | V3 ×1
skill/frontend-system-pattern        | True     | 2026-08-25T18:03:32Z | []   | None          | False    | V5 ×2
skill/solution-designer              | True     | 2026-08-25T18:03:26Z | []   | None          | True     | —
```

`total=8`, `sort=name`. Every nullable field is present-and-null as C-7 promises; `superseded_by`
is `null` on both stubs, not absent.

### `hl --library ~/.claude validate`

```
skill/developers-orchestration  [INVALID]  skills/developers-orchestration
  V3 ERROR: SKILL.md cites references/delegation.md, which does not exist under skills/developers-orchestration (references/delegation.md)
  V3 ERROR: SKILL.md cites references/review-and-merge.md, which does not exist under skills/developers-orchestration (references/review-and-merge.md)
  V3 ERROR: SKILL.md cites references/plan-formats.md, which does not exist under skills/developers-orchestration (references/plan-formats.md)
  V3 ERROR: SKILL.md cites references/conflicts.md, which does not exist under skills/developers-orchestration (references/conflicts.md)
  V3 ERROR: SKILL.md cites references/cost-and-time.md, which does not exist under skills/developers-orchestration (references/cost-and-time.md)
  V3 ERROR: SKILL.md cites references/collaboration.md, which does not exist under skills/developers-orchestration (references/collaboration.md)

skill/frontend-ctg-system-pattern  [INVALID]  skills/frontend-ctg-system-pattern
  V3 ERROR: SKILL.md cites references/brand-ctg.md, which does not exist under skills/frontend-ctg-system-pattern (references/brand-ctg.md)

skill/frontend-system-pattern  [INVALID]  skills/frontend-system-pattern
  V5 ERROR: required frontmatter key 'name' is missing (SKILL.md)
  V5 ERROR: required frontmatter key 'description' is missing (SKILL.md)

agent/backend-developer-specialist  [INVALID]  agents/backend-developer-specialist.md
  V3 ERROR: backend-developer-specialist.md cites references/persistence.md, which does not exist under agents/backend-developer-specialist.md (references/persistence.md)
  V3 ERROR: backend-developer-specialist.md cites references/schema-evolution.md, which does not exist under agents/backend-developer-specialist.md (references/schema-evolution.md)
  V3 ERROR: backend-developer-specialist.md cites references/concurrency.md, which does not exist under agents/backend-developer-specialist.md (references/concurrency.md)
  V3 ERROR: backend-developer-specialist.md cites references/contracts.md, which does not exist under agents/backend-developer-specialist.md (references/contracts.md)
  V3 ERROR: backend-developer-specialist.md cites references/ai-integration.md, which does not exist under agents/backend-developer-specialist.md (references/ai-integration.md)
  V3 ERROR: backend-developer-specialist.md cites references/observability.md, which does not exist under agents/backend-developer-specialist.md (references/observability.md)
  V3 ERROR: backend-developer-specialist.md cites references/testing.md, which does not exist under agents/backend-developer-specialist.md (references/testing.md)

agent/frontend-developer-specialist  [INVALID]  agents/frontend-developer-specialist.md
  V3 ERROR: frontend-developer-specialist.md cites references/brand-ctg.md, which does not exist under agents/frontend-developer-specialist.md (references/brand-ctg.md)

8 artifact(s) checked: INVALID. 17 error(s), 0 warning(s).
```

Exit code `1`. Note **0 warnings**: no symlink, no swap file, no vendor tree anywhere in the real
library, so V6 never fires here and R22's "a WARNING never blocks" is not exercised by this tree.

### `hl --library ~/.claude collections` and `--json`

```
This library declares no collections.
```
```json
{"collections":[],"total":0}
```

Both exit `0`. Correct and unhelpful — see L6 above. **F-5 is unproven against real content.**

### `hl --library ~/.claude show skill/frontend-system-pattern`

F-2's exact case: an invalid artifact rendered rather than raised on.

```
skill/frontend-system-pattern
  name           frontend-system-pattern
  type           skill
  kind           directory
  path           skills/frontend-system-pattern
  description    -
  tags           -
  superseded by  -
  content hash   6312167a1332da45aa6445a2c710dfc4a447e18a981a1711e52e2686520a2dc2
  updated        2026-08-25T18:03:32+00:00
  dirty          yes
  valid          no

files (9, 280288 bytes)
  SKILL.md (32263 bytes)
  references/a11y-and-dialogs.md (4127 bytes)
  references/async-ui.md (3723 bytes)
  references/authority-rendering.md (3973 bytes)
  references/brand-ctg.md (39617 bytes)
  references/contract-honesty.md (4532 bytes)
  references/ctg_brasil_brand_reference.html (184002 bytes)
  references/testing.md (4247 bytes)
```

`description -` is itself the symptom of D-2 below.

---

## 2. The V3 redirect-stub exemption, and the gap around it

### 2a. Without `library.yaml` — seven findings, exactly as L5 predicted

Counted from `hl --library ~/.claude validate --json`:

```
  7  V3  agent/backend-developer-specialist
  1  V3  agent/frontend-developer-specialist
  6  V3  skill/developers-orchestration
  1  V3  skill/frontend-ctg-system-pattern
  2  V5  skill/frontend-system-pattern
TOTALS: {'V3': 15, 'V5': 2}
is_valid=False  errors=17  warnings=0  library_findings=[]
V3 on the two stubs = 7
```

**Seven on the two stubs.** Predicted, not a bug, regex untouched (L5).

### 2b. With `library.yaml` — the exemption fires

The real tree was copied to a scratch directory (`cp -a`; nothing under `~/.claude` was touched)
and this file added at its root — **this is what a user must author to get the stubs to stop
reporting**:

```yaml
artifacts:
  skill/developers-orchestration:
    superseded_by: skill/delivery-lead
  skill/frontend-ctg-system-pattern:
    superseded_by: skill/frontend-system-pattern
```

`hl --library <copy> validate` then reports:

```
skill/frontend-system-pattern  [INVALID]  skills/frontend-system-pattern
  V5 ERROR: required frontmatter key 'name' is missing (SKILL.md)
  V5 ERROR: required frontmatter key 'description' is missing (SKILL.md)

agent/backend-developer-specialist  [INVALID]  agents/backend-developer-specialist.md
  V3 ERROR: backend-developer-specialist.md cites references/persistence.md, ... (×7)

agent/frontend-developer-specialist  [INVALID]  agents/frontend-developer-specialist.md
  V3 ERROR: frontend-developer-specialist.md cites references/brand-ctg.md, ...

8 artifact(s) checked: INVALID. 10 error(s), 0 warning(s).
```

### Side by side

| | without `library.yaml` | with `library.yaml` |
|---|---|---|
| errors | **17** | **10** |
| V3 on `skill/developers-orchestration` | 6 | **0** |
| V3 on `skill/frontend-ctg-system-pattern` | 1 | **0** |
| V3 on the two agents | 8 | 8 (unchanged) |
| both stubs' `STATUS` in `hl list` | `INVALID` | `ok` |
| both stubs' rank in `hl list` | interleaved by name | **last two rows**, R8 applied |
| `SUPERSEDED BY` column | `-` | `skill/delivery-lead`, `skill/frontend-system-pattern` |

The exemption is exactly the seven-finding delta. **Charter §8's most important rule interaction
works on real content.**

`hl list` on the copy, showing R8:

```
ID                                   KIND       STATUS   TAGS  SUPERSEDED BY                  FILES
agent/backend-developer-specialist   file       INVALID  -     -                              1
skill/backend-system-architecture    directory  ok       -     -                              8
skill/delivery-lead                  directory  ok       -     -                              7
agent/frontend-developer-specialist  file       INVALID  -     -                              1
skill/frontend-system-pattern        directory  INVALID  -     -                              9
skill/solution-designer              directory  ok       -     -                              7
skill/developers-orchestration       directory  ok       -     skill/delivery-lead            1
skill/frontend-ctg-system-pattern    directory  ok       -     skill/frontend-system-pattern  2
```

Both stubs are still **present** and still **visible** — ranked below, never dropped. R8 holds.

### 2c. R15's fallback path also works, and costs less to author

A second copy was made with **no `library.yaml`** and one line added to each stub's own
frontmatter (`superseded_by: skill/delivery-lead` / `superseded_by: skill/frontend-system-pattern`).
The report is **byte-identical to 2b**: 10 errors, the same seven V3 gone.

So a user has two ways to close the gap, and they are not equivalent in cost:

- **`library.yaml`** — one new file, no edit to any artifact. Authoritative (R15). Also the only
  route to tags and collections.
- **frontmatter** — two one-line edits inside artifacts that other tooling reads. Cheaper, but it
  puts library-level metadata inside a document a skill loader will also parse.

**The gap, stated plainly:** the real library declares neither. Until someone authors one of the
two, the two redirect stubs report seven ERRORs that are all correct prose, and `hl validate`
exits non-zero on a library whose stubs are working exactly as designed.

---

## 3. Scan cost — measured, and the estimate does not survive contact

The estimate in play was *"imperceptible at roughly 750 KB across eight artifacts."* Measured
subject: 36 files, 668 406 bytes.

**Method.** Ten runs of `hl --library ~/.claude list > /dev/null` timed with `/usr/bin/time -f %e`,
each a fresh process. Then the same cost decomposed: bare interpreter, interpreter + import of the
CLI module with no work done, and the scan itself timed in-process with `time.perf_counter()`
around `FilesystemArtifactRepository(root).list_all()` (which forces the whole snapshot — walk,
hash, `library.yaml`, assemble). Page cache warm; unprivileged, so a true cold-cache run was not
available.

| Measurement | Result |
|---|---|
| `hl list`, end to end, 10 runs | 2.19 – 2.26 s (median **2.21 s**) |
| bare `python -c pass` | 0.03 s |
| `python -c "import harness_library.cli.main"` | **2.15 – 2.23 s** |
| the scan itself, in-process, 5 reps | **15.9 – 17.5 ms** |
| `hl mcp` cold start to `initialize` response, 5 runs | 1.85 – 1.92 s (median **1.88 s**) |

**Verdict: the estimate held for the thing it described and was measuring the wrong thing.**
The scan is ~16 ms — genuinely imperceptible, and about 0.7 % of what a user waits for. The other
99.3 % is Python import time, paid before a single byte of the library is read.

`python -X importtime` names the cost:

```
import time:      1837 |    1848645 | harness_library.cli.main
import time:       346 |    1305417 |   harness_library.mcp
import time:       429 |    1304623 |     harness_library.mcp.dispatch
import time:        42 |    1295873 |       mcp.types
import time:    302568 |     302568 |         mcp_types._v2026_07_28
import time:    275116 |     275765 |         mcp_types._v2025_11_25
import time:    229399 |     240562 |         mcp_types._types
import time:       452 |     214643 |   harness_library.application.read
```

`cli/main.py` imports `from harness_library.mcp import serve_stdio` at module scope for the sake of
one command. **`hl list` pays 1.31 s to import the MCP SDK it never touches** — 59 % of its total
runtime. See D-3.

**Consequence for the original question:** no caching is warranted. R5's git subprocess cost is also
a non-issue here — `~/.claude` is not a work tree, so `GitTimestamps` makes exactly one
`git rev-parse` call, discovers that, and takes the mtime path for every artifact with no further
subprocess. `timestamps.py`'s "fifty artifacts is fifty-two processes" warning is untested by this
library and remains a live risk for a library that *is* a work tree.

---

## 4. The MCP server against the real library, over real JSON-RPC

Driven by a raw client over pipes — `subprocess.Popen(["hl", "--library", ~/.claude, "mcp"])`,
newline-delimited JSON-RPC on stdin/stdout, all four expected response lines read **before** stdin
was closed, with a 20 s watchdog (L31).

### initialize

Request:
```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t9-acceptance","version":"1.0"}}}
```
Response:
```json
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "capabilities": {"experimental": {}, "tools": {"listChanged": false}},
    "instructions": "A read-only view of a Claude Code harness library: its skills, its agents, their references and their validation findings. Call `list_artifacts` first to see what exists, `search_artifacts` to find a phrase across entry documents and markdown references, and `get_artifact` for one artifact in full. Prefer `get_reference` when you need a single reference file: these skills are reference-heavy and the entry document alone can run to hundreds of lines.",
    "protocolVersion": "2025-06-18",
    "serverInfo": {"name": "harness-library", "title": "Harness library", "version": "0.1.0"}
  }
}
```

### tools/list — four tools, read from the server

```
list_artifacts   | title: List artifacts        | annotations: {'destructiveHint': False, 'readOnlyHint': True}
    inputSchema props: ['collection', 'include_superseded', 'invalid_only', 'sort', 'tag', 'type']
    outputSchema: PRESENT | title: ArtifactListPayload
search_artifacts | title: Search artifacts      | annotations: {'destructiveHint': False, 'readOnlyHint': True}
    inputSchema props: ['collection', 'query', 'tag', 'type']
    outputSchema: PRESENT | title: SearchResults
get_artifact     | title: Get one artifact      | annotations: {'destructiveHint': False, 'readOnlyHint': True}
    inputSchema props: ['artifact_id']
    outputSchema: PRESENT | title: ArtifactDetail
get_reference    | title: Get one reference file| annotations: {'destructiveHint': False, 'readOnlyHint': True}
    inputSchema props: ['artifact_id', 'path']
    outputSchema: PRESENT | title: FileContent
```

Exactly four. Every one declares `outputSchema` generated from its C-7 model, so the client
revalidates results against the contract rather than trusting a promise.

### tools/call `get_artifact` on a real skill

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_artifact","arguments":{"artifact_id":"skill/backend-system-architecture"}}}
```
Result — `isError: false`, structured content:
```
id: skill/backend-system-architecture | file_count: 8 | total_size: 66031 | is_valid: True
entry_path: SKILL.md | entry_text: 33987 chars
files: ['SKILL.md', 'references/ai-integration.md', 'references/concurrency.md',
        'references/contracts.md', 'references/observability.md', 'references/persistence.md',
        'references/schema-evolution.md', 'references/testing.md']
keys: content_hash, description, entry_path, entry_text, file_count, files, findings, frontmatter,
      id, is_dirty, is_valid, kind, name, path, superseded_by, tags, total_size, type, updated_at
```

### tools/call `get_reference` on one of its reference files

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_reference","arguments":{"artifact_id":"skill/backend-system-architecture","path":"references/persistence.md"}}}
```
Result — `isError: false`:
```
payload keys: artifact_id, is_text, path, sha256, size, text
artifact_id: skill/backend-system-architecture | path: references/persistence.md
size: 4464 | is_text: True
sha256: 7cbecca3c1060ac43fcf57250939b6abe7bdb1de4453aacdf78acd7ce38a1f32
text: 4448 chars
```

**No `entry_text` key exists on the payload at all** — `FileContent` has no field for it, and
`Payload` is `extra="forbid"`, so the declared `outputSchema` would reject one. F-6's "without its
parent's entry text" is structural, not a promise.

### The token argument for `get_reference` — real numbers

`skills/backend-system-architecture/SKILL.md` is **718 lines**, matching the figure the tool's own
description quotes.

| | bytes |
|---|---|
| whole artifact on disk (8 files) | **66 031** |
| `get_artifact` result text block (entry text + metadata + file list) | **38 933** |
| `references/persistence.md` on disk | **4 464** |
| `get_reference` result text block | **4 772** |

**A session needing one reference pays 4.8 KB instead of 38.9 KB — 8.2× less through the wire, and
14.8× less than the artifact's full content.** The argument holds and is not marginal.

### stdout purity and logging

The client parsed **every** stdout line as JSON-RPC; nothing else appeared on it. The server's
stderr carried exactly one line per tool call (R3):

```
2026-09-01T03:16:12.250770Z [info     ] mcp.tool_call                  ok=True tool=get_artifact
2026-09-01T03:16:12.256062Z [info     ] mcp.tool_call                  ok=True tool=get_reference
```

Server exited `0` on stdin close.

---

> **STRUCK 2026-09-20 — the context half of F-3 was never built.** This report's F-3 verdict reads PASS
> on "path/line/context", but the shipped `SearchMatch` carries four fields and no context lines; its
> docstring redefined the requirement rather than meeting it. The *skipped-asset* half of F-3, which
> §5 below examines, is correct and stands. Found by a `phase-reviewer` cold read; scheduled as T-11
> under ruling R36.

## 5. F-3 settled — the 184 KB HTML asset

`~/.claude/skills/frontend-system-pattern/references/ctg_brasil_brand_reference.html` is
**184 002 bytes** and **decodes cleanly as UTF-8** (verified directly). The criterion's premise is
correct: it is text, so "binary" would be a false diagnosis, which is why R25/R27 forbid the word.

`preserveAspectRatio` appears **only** inside that HTML, nowhere in any `.md` in the library.

```
$ hl --library ~/.claude search preserveAspectRatio
No matches for 'preserveAspectRatio'.

0 match(es).

2 file(s) not searched:
  skill/frontend-ctg-system-pattern:ctg_brasil_brand_reference.html — not_a_markdown_reference
  skill/frontend-system-pattern:references/ctg_brasil_brand_reference.html — not_a_markdown_reference
```

```json
{
    "query": "preserveAspectRatio",
    "matches": [],
    "truncated": false,
    "limit": 200,
    "skipped": [
        {
            "artifact_id": "skill/frontend-ctg-system-pattern",
            "path": "ctg_brasil_brand_reference.html",
            "reason": "not_a_markdown_reference",
            "message": "not a markdown reference: only the entry document and `.md` files under `references/` are searched (ruling R4)"
        },
        {
            "artifact_id": "skill/frontend-system-pattern",
            "path": "references/ctg_brasil_brand_reference.html",
            "reason": "not_a_markdown_reference",
            "message": "not a markdown reference: only the entry document and `.md` files under `references/` are searched (ruling R4)"
        }
    ]
}
```

**F-3 PASSES.** The reason is `not_a_markdown_reference`. The word *binary* appears nowhere. The
omission is reported rather than silent — a user searching for a term that lives only in that HTML
is told, by name, which two files were not looked at.

**Positive control**, so "0 matches" is not mistaken for a search that never ran — `CTG Sans`
occurs in both the HTML *and* a markdown reference:

```
$ hl --library ~/.claude search "CTG Sans"
skill/frontend-ctg-system-pattern:SKILL.md:3: description: Use when building or reviewing ... CTG Sans typography, ...
skill/frontend-system-pattern:references/brand-ctg.md:135:       sans:    ['CTG Sans', 'Bricolage Grotesque', ...
skill/frontend-system-pattern:references/brand-ctg.md:164: ## 3. Typography — CTG Sans is the brand typeface
... (13 matches total)

13 match(es).

2 file(s) not searched:
  skill/frontend-ctg-system-pattern:ctg_brasil_brand_reference.html — not_a_markdown_reference
  skill/frontend-system-pattern:references/ctg_brasil_brand_reference.html — not_a_markdown_reference
```

Correct artifact, correct path, correct 1-based line number, whole matching line as context — and
the same two HTML files still reported skipped even though the phrase is inside them. That is the
exact behaviour R4 and R25 specify, demonstrated on content nobody designed for it.

**Incidental:** the 184 KB asset exists **twice** in the real library — once under
`frontend-system-pattern/references/`, once at the root of the `frontend-ctg-system-pattern` stub,
which is otherwise a two-file redirect. 368 KB of the library's 653 KB is two copies of one HTML
file. Not a defect the tool is required to report; noted because an install initiative will copy
both.

---

## Defects found

### D-1 · V3 cannot be satisfied by a FILE-kind artifact — 8 false positives, 0 true positives

**Severity: high.** This is the headline.

Both agents cite `references/…` paths belonging to *another artifact*, in prose that names the
owning skill:

> `backend-developer-specialist.md`, under **"The skill carries topic references"**:
> `| ORM models, queries, constraints, indexes, locking reads | references/persistence.md |`
>
> `frontend-developer-specialist.md`: *"consult `frontend-system-pattern` … for a CTG Brasil product
> that is the bundled `references/brand-ctg.md`"*

**Every one of those eight paths exists** — under the skill the agent points at:

```
skills/backend-system-architecture/references/: ai-integration.md concurrency.md contracts.md
    observability.md persistence.md schema-evolution.md testing.md      (7 of 7 cited — all present)
skills/frontend-system-pattern/references/:     brand-ctg.md            (1 of 1 cited — present)
```

The cause is structural, not incidental. An agent is a `FILE`-kind artifact: per
`registry.py`/`scanner.py` it holds exactly one file whose path is its own basename. `raw.file_paths`
can therefore **never** contain a `references/…` path, so `_check_v3`'s `cited not in present` test
is unconditionally true. **V3 has no reachable passing case for any FILE-kind artifact.** Any agent
that so much as mentions a reference path is permanently invalid.

Netting it out on the real library, with the stub exemption correctly configured:

| V3 findings | count | correct? |
|---|---|---|
| the two redirect stubs | 7 | exempt once `superseded_by` is declared |
| the two agents | 8 | **all false — every cited path exists elsewhere** |
| genuinely broken citations anywhere in the library | **0** | — |

V3 is the rule charter §8 justifies with *"a skill documenting another skill's install path"*. On
real content it did not find that failure; it manufactured eight of its own.

**Pinned, not fixed** (behaviour deliberately unchanged, per the task's constraint):
`tests/domain/test_assembly.py::test_a_file_kind_artifact_cannot_satisfy_v3_for_any_citation`, with
`::test_a_file_kind_artifact_citing_nothing_is_clean` as its positive control and
`::test_a_directory_kind_artifact_citing_the_same_path_can_be_clean` as the contrast.

**For the delivery lead to rule on.** Three shapes, none implemented:
1. exempt FILE-kind artifacts from V3 entirely — cheapest, and gives up the rule for agents;
2. resolve a citation library-wide before calling it broken — turns V3 into a library-level rule
   beside V4/V7/V8, and would report a *genuinely* dangling cross-artifact citation, which is
   arguably what the rule was always for;
3. leave it and require `library.yaml` to suppress — not viable; no such mechanism exists for a
   non-superseded artifact.

Option 2 is the one that keeps the rule's value. It is a rule change, so it is plan-level.

### D-2 · One unquoted `:` silently discards an entire frontmatter block, and the diagnosis points elsewhere

**Severity: medium.** `skills/frontend-system-pattern/SKILL.md` line 3 is a plain YAML scalar
containing `": "`:

```
description: Use when writing, reviewing, or refactoring React/TypeScript frontend code — … Covers every brand: the project's brand reference is the visual authority, …
                                                                                                          ^^ here
```

PyYAML: `ScannerError: mapping values are not allowed in this context, line 3, column 255`.
`scanner._parse_entry` treats *any* parse failure as "this document declares nothing" and returns
an empty frontmatter mapping. Consequences:

- two V5 ERRORs saying `required frontmatter key 'name' is missing` — about a file whose **second
  line is `name: frontend-system-pattern`**. True finding, false diagnosis;
- `description` is `null` in every payload and `-` in `hl show`, so the artifact is unsearchable by
  its own description and unreadable in a listing;
- V2 cannot fire (it is silent when `name` is absent), so a *second* fault in the same file would
  be masked;
- **worst case, not hit here but one line away:** if a redirect stub's frontmatter failed to parse,
  R15's frontmatter fallback for `superseded_by` would silently return `None` and V3's exemption
  would not fire. A YAML typo would quietly flood the report with the exact findings charter §8
  carves out.

Note the asymmetry that makes this dangerous: **Claude Code's own loader parses this file fine** —
the skill's full description appears in a live session's skill listing. So `hl validate` calls
invalid a skill that the real runtime loads correctly. That is a false positive by the standard of
"does this artifact work", and a true positive by the standard of "is this well-formed YAML".
Which standard `hl` is supposed to hold is **an ambiguity I am not resolving** — see Open questions.

`scanner._read_entry`'s docstring already flagged this: *"Flagged to the delivery lead: a dedicated
code would say it better."* T-9 is the event that flag was waiting for — it happened on the first
real run, on real content.

**Pinned, not fixed:**
`tests/infrastructure/test_repository.py::test_a_colon_in_an_unquoted_description_loses_the_whole_frontmatter`
with `::test_quoting_the_same_description_makes_the_artifact_clean` as its positive control.

### D-3 · `hl list` pays 1.31 s to import an MCP stack it never uses

**Severity: medium (usability), zero (correctness).** Measured in §3. `cli/main.py` does
`from harness_library.mcp import serve_stdio` at module scope, so every `hl list`, `hl show`,
`hl search`, `hl validate` and `hl collections` imports `mcp.types`, `mcp.client` and two versioned
`mcp_types` schema modules costing 578 ms between them. A read-only listing of eight artifacts takes
2.2 s, of which 16 ms is the actual work.

Not fixed: out of scope, and the fix is a one-line deferral inside the `mcp` command that changes
import-time behaviour and would want its own mutation check. Flagged for initiative 02, which adds
more commands to the same module and will inherit the cost.

---

## The symlinked-artifact-root decision — input, not a resolution

The state today, from `scanner._artifact_name`: `is_symlink()` is tested before `is_dir()`/`is_file()`
(correctly, per R6), and a symlinked artifact root returns `None` — not followed, **and not
scanned, and not reported**. A symlinked skill that would load perfectly is absent from the library
with no diagnostic anywhere. The docstring says so and defers to you.

**How likely in practice.** More likely than the current library suggests, and the likelihood is
about to rise:

- `~/.claude` today contains **zero symlinks** (verified: 48 filesystem entries, none a link), so
  the exposure is currently nil;
- but the natural way to develop a skill against a live harness is
  `ln -s ~/work/my-skill ~/.claude/skills/my-skill`, and that is precisely the user this tool
  serves. The failure mode is silent and self-consistent: `hl list` shows seven artifacts, the user
  has eight, and nothing anywhere says which one is missing or why;
- initiative 02 **installs**. A symlink at the *target* is a different and more urgent question
  than one at the source — installing over a symlinked root either follows it (writing outside the
  target, the exact escape R6 exists to prevent) or replaces it (destroying the user's dev link).
  That question has to be answered by initiative 02 regardless of what is decided here.

**What the rule would cost.** Small, and smaller than it looks, because every part already exists:

- one register row in charter §8 — a **WARNING** ("an artifact root that is a symlink was not
  scanned"), so R22 keeps it from blocking anything;
- the finding has no artifact to hang itself on, so it belongs at the **library level** beside V7
  and V9 — a path `assembly.AssembledLibrary.findings` and `repository.library_findings()` already
  provide, and which `validate_library` already renders;
- the plumbing is the real cost: `scan_library` currently returns only `tuple[RawArtifact, ...]`,
  so a skipped root has no channel out of the scanner. That signature changes, and so does
  `FilesystemArtifactRepository._snapshot`. Contract C-4 itself is untouched.

Estimate: half a day including tests and one mutation check. Not free, not large.

**My recommendation: defer it to the install initiative, and record the reason now.**

Because: the exposure on today's real content is exactly zero; the rule as scoped here is a
*diagnostic* whose whole value is warning a user before they install, which is initiative 02's
question; and initiative 02 must open the symlink question at the target anyway, so deciding both
halves together will produce one coherent rule instead of a WARNING here and an unrelated policy
there. Deciding it now risks exactly the outcome you named — a register row added because the gap
was noticed, rather than because the failure was understood.

What I would **not** do is leave it undocumented. The gap is real and it is silent, which is the
one failure class this product exists to eliminate. A line in the decisions log naming it as
deferred-to-02 costs nothing and keeps it from being rediscovered by whoever hits it first.

---

## Verification

**The real library is byte-for-byte unchanged.** A manifest of all 48 entries under
`~/.claude/skills` and `~/.claude/agents` (SHA-256 per file, symlink targets, directory markers) was
taken before any command ran and again after everything above. `diff` is empty:

```
IDENTICAL: real library byte-for-byte unchanged (48 entries)
--- library.yaml still absent under ~/.claude?
ls: cannot access '/home/mininoel/.claude/library.yaml': No such file or directory
--- files with an mtime newer than 2026-08-31?
(none)
```

Both experiments in §2 ran against `cp -a` copies in a scratch directory. Nothing under `~/.claude`
was created, modified, deleted or moved.

**Mutation checks**, each with its assertion named before the run:

| Mutation | Named to fail | Result |
|---|---|---|
| `_check_v3` skips FILE-kind artifacts | `test_a_file_kind_artifact_cannot_satisfy_v3_for_any_citation` — `findings_for(...) == ["references/persistence.md"]` | **Failed as named**, `assert [] == ['references/persistence.md']`. 53 others passed, including every stub-exemption and DIRECTORY-kind V3 test — an independence check. Restored: 54 passed. |
| `_parse_entry` returns empty frontmatter on the success path | `test_quoting_the_same_description_makes_the_artifact_clean` — `assert artifact.findings == ()` | **Failed as named**, `assert (ValidationFinding V5 …) == ()`; the characterisation test beside it stayed green, proving the pair is not vacuous. Restored: 2 passed. |

Both mutations sit **above** the only fake in play (`FixedTimestamps`, which pins R5 only): the first
is pure-domain, the second is in `infrastructure/` and observed through real files on disk.

**The gate**, whole, from the repository root — result recorded in the report to the delivery lead.

---

## Files changed by this task

| File | Change |
|---|---|
| `docs/instructions/phases/phase-1/01-store-and-read-path/2026-09-01-acceptance.md` | this document |
| `docs/instructions/phases/phase-1/01-store-and-read-path/backend-task-plan.md` | T-9 section appended |
| `tests/domain/test_assembly.py` | +3 tests pinning D-1 (one characterisation, two controls) |
| `tests/infrastructure/test_repository.py` | +2 tests pinning D-2 (one characterisation, one control) |

**No `src/` file was changed.** Both mutations were reverted with `git checkout --`. No commit was
authored.

---

## Open questions for the delivery lead

1. **D-1 — what should V3 mean for a FILE-kind artifact?** Option 2 (resolve citations
   library-wide) is the one that preserves the rule's stated purpose, and it is a plan-level change
   to charter §8. Until it is ruled on, every agent in every library is permanently invalid.
2. **D-2 — what is `hl validate` measuring?** Claude Code's loader reads
   `frontend-system-pattern`'s frontmatter successfully; `hl` does not. If the standard is "would
   this load", the current behaviour is a false positive and the parser should be as lenient as the
   runtime. If the standard is "is this well-formed", the finding is right and only the *message* is
   wrong, and the fix is the dedicated code `scanner._read_entry` already asks for. **These are
   different products.** I did not choose.
3. **F-5 is unproven against real content.** It is proven against the fixture library. If that is
   acceptable, say so in the record rather than letting the acceptance table imply otherwise.
4. **The symlinked artifact root** — recommendation above: defer to initiative 02, log the reason
   now.
