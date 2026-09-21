# Acceptance — Install, backup, drift (initiative 02, task T-23)

**Phase:** 1 · **Initiative:** 02-install-and-drift · **Task:** T-23 · **Date:** 2026-09-21
**Base:** `main` at `211edda`, working tree clean at the start. Gate green at 1038 tests.
**Run by:** `backend-developer-specialist`, against the committed fixtures and against a copy of
the user's real `~/.claude/`.

---

## 0. The headline verdict

> **Is installing inspectable before it runs, reversible after it runs, and incapable of
> destroying a file it did not put there?**

**Inspectable — yes.** `hl diff` and `hl install --dry-run` describe every path the tool can see,
and on the real tree the scan reported **1382 of 1382** paths with nothing omitted (§2.1). A dry
run writes nothing, asserted on content hashes (§1, F-8).

**Reversible — yes for content, no for permissions.** A `clean --foreign --remove` that deleted
**1345 paths / 144 MB** of the real harness was put back by `hl rollback` **byte-identical on all
1382 paths, including the one symlink** (§2.7). But every restored file comes back at mode `0644`:
`.credentials.json` goes `0600 → 0644`, an executable goes `0700 → 0644`. On the real tree that is
**149 private files made world-readable and 56 executables disarmed** by the recovery path.
**Defect D-2, §8.**

**Incapable of destroying a file it did not put there — yes.** In every run in this report, no
`install`, `uninstall`, `--prune` or `--resolve` changed a foreign path's content. The only
command that touches one is `clean --foreign --remove`, which lists every path first, refuses to
act without the flag, and backs everything up. The sharpest single measurement: an install over
real drift in the real harness changed **exactly two files**, both of them library files with a
safe verdict, and all 1380 other paths were byte-identical afterwards (§2.5).

Two defects and seven observations follow in §8. Neither defect destroys data; one of them is a
security regression on the recovery path, and both need a contract amendment rather than a patch,
which is why this task reports them instead of fixing them.

---

## 1. Deliverable 1 — F-8 … F-16 and V11, through the CLI

Every row was exercised through `hl`, which is the only human surface. `$HOME` was redirected on
every invocation (L64) and every claim about a file is a content hash, never a command's own
report (R31).

| # | Verdict | Evidence |
|---|---|---|
| **F-8** | **Proved in part** | Eight of C-9's nine verdicts were produced through the CLI and read back as values: `create`, `unchanged`, `manifest_repair`, `update`, `local_edit`, `conflict`, `prune`, `foreign`, `skipped` — that is all nine, §1.1. `MANIFEST_REPAIR` rewrote the record and left every file byte-identical, asserted on the tree hash. `hl diff` on an untouched target reported `unchanged` for every path and exited 0. **Not re-proved here:** that the rule never emits `SKIPPED` (a domain sweep) and that the three impossible hash combinations raise — both are unit-level and both are inside the green gate. |
| **F-9** | **Proved** | §1.2. Safe entries written, conflicted entries byte-identical, `INCOMPLETE = 6`, all three from one run. Modes `0644`/`0755` on the stat. `BACKUP_FAILED = 9` and a byte-identical target from a read-only backup directory. R63's ordering demonstrated through a *real* failure, not an injected one (§1.3). |
| **F-9 (R75)** | **Proved** | §1.4. Six invalid artifacts came out `skipped` with a reason naming the code, were not written, and the run exited 6; `--force` installed all six. A WARNING-only artifact (`skill/messy`, V6 ×3) installed normally — the control. |
| **F-10** | **Proved** | §1.5. Seven foreign paths byte-identical after apply. `clean --foreign` listed before removing, removed nothing the manifest knew, and removed nothing at all without `--remove`. |
| **F-11** | **Proved** | §1.6, and §2.7 at real scale. Asserted per file on the content-hash manifest of the whole tree. |
| **F-12** | **Proved** | §1.7. Uninstall removed exactly the manifest's six files out of 1381 paths; a foreign file *inside the artifact's own directory* survived byte-identical. `--prune` removed the one dropped path and only that. |
| **F-13** | **Proved** | §1.8. Two targets, two manifests keyed separately; installing into one left the other's manifest bytes and file set untouched. |
| **F-14** | **Proved** | §1.9. A held lock → `LOCK_HELD = 10` with the target's hash set unchanged. A sentinel naming a dead pid was broken and the apply proceeded. |
| **F-15** | **Proved** | §1.10. `--resolve library` wrote the library's version; `--resolve target` left the file byte-identical and repaired the record; both exit 0 on a clean library. Per artifact: resolving one of two conflicts left the other still refused. |
| **F-16** | **Proved** | §1.11. Entries are exactly the collection's artifacts' files as a path list; a PNG round-tripped byte-identical; two exports of one unchanged library are byte-identical. |
| **V11** | **Proved** | §1.12. WARNING in `hl validate`, named and `skipped` in the plan, run exits `6` on the integer, everything else applied, and neither the link nor its destination written. `--force` did not lift it (R99). **One gap: `hl diff` does not name it** — observation O-1. |
| **Cross-cutting** | **Proved** | `~/.claude/` byte-identical on the narrowed manifest, §6. |

### 1.1 All nine verdicts, as values

Against the committed fixture library and target:

```
$ hl --library …/fixtures/library diff --target …/fixtures/target
VERDICT   PATH                                                    ARTIFACT
create    agents/nameless.md                                      agent/nameless
conflict  agents/scribe.md                                        agent/scribe
foreign   settings.json                                           -
…
21 path(s) in …/target: conflict 2, create 12, foreign 7.
EXIT=0
```

Against a purpose-built clean library, with the target drifted four ways at once:

```
$ hl --library …/clean/lib diff --target …/clean/t1
VERDICT     PATH                              ARTIFACT
local_edit  agents/beta.md                    agent/beta
foreign     settings.json                     -
update      skills/alpha/SKILL.md             skill/alpha
prune       skills/alpha/references/notes.md  skill/alpha

4 path(s) in …/clean/t1: update 1, local_edit 1, prune 1, foreign 1.
EXIT=0
```

`unchanged` and `manifest_repair`:

```
$ hl … diff --target …/clean/t1          # immediately after a clean install
unchanged  agents/beta.md                    agent/beta
unchanged  skills/alpha/SKILL.md             skill/alpha
unchanged  skills/alpha/references/notes.md  skill/alpha
3 path(s) …: unchanged 3.
EXIT=0

$ rm …/manifests/*.json && hl … diff --target …/clean/t1
manifest_repair  agents/beta.md                    agent/beta
manifest_repair  skills/alpha/SKILL.md             skill/alpha
manifest_repair  skills/alpha/references/notes.md  skill/alpha
EXIT=0

$ hl … install --target …/clean/t1       # apply the repair
Complete: everything was applied.   EXIT=0
FILES BYTE-IDENTICAL after MANIFEST_REPAIR (asserted on content, not on the report)
```

`skipped` is §1.4 and §1.12.

### 1.2 F-9 — one run, three guarantees

```
$ hl --library …/clean/lib install --target …/clean/t1
4 path(s) …: update 1, local_edit 1, prune 1, foreign 1.
  written (1)
    skills/alpha/SKILL.md
  backup         2026-09-21T20-02-33Z
left alone (1)
  local_edit  agents/beta.md
INCOMPLETE: the entries above were left alone. Nothing was destroyed …
EXIT=6

safe UPDATE written?    YES
LOCAL_EDIT untouched?   YES
FOREIGN untouched?      YES
PRUNE path still there? YES
```

Modes, on the stat, for the five files a fixture install wrote and the four directories it made:

```
644 …/skills/delivery-lead/references/checklist.md      755 …/skills/legacy-ctg-pattern
644 …/skills/legacy-ctg-pattern/SKILL.md                755 …/skills/legacy-orchestration
644 …/skills/legacy-orchestration/SKILL.md              755 …/skills/messy
644 …/skills/messy/SKILL.md                             755 …/skills/messy/references
644 …/skills/messy/references/diagram.png
```

`BACKUP_FAILED`, with the backup directory made read-only:

```
error [BACKUP_FAILED]: the backup could not be taken, so nothing was written: [Errno 13]
Permission denied: …/backups/2026-09-21T20-04-41Z. Install refuses to write a target it cannot put back
EXIT=9
TARGET BYTE-IDENTICAL — nothing was written
```

### 1.3 R63's ordering, demonstrated by a real failure

The plan asserts the manifest-before-files ordering by injecting a failure into the first write.
The CLI reaches the same state without injection — a target directory that cannot be written:

```
$ chmod a-w target/ target/skills target/agents
$ hl --library …/clean/lib install --target …/r6/target
error [TARGET_UNWRITABLE]: agents/beta.md could not be written into the target: [Errno 13] …
EXIT=7

$ hl --library …/clean/lib diff --target …/r6/target
create   agents/beta.md                          agent/beta
create   skills/alpha/SKILL.md                   skill/alpha
```

`create` for a path the target does not hold means the **manifest already records it**. The record
was on disk before the first file write was attempted, and it over-claims — exactly the
self-correcting failure R63 chooses. The run after `chmod u+w` was `Complete: everything was
applied. EXIT=0`.

### 1.4 R75 and `--force`

```
$ hl --library …/fixtures/library install --force --target …/r3/target
  skills/no-entry/references/orphan.md          WRITTEN
  skills/misnamed/SKILL.md                      WRITTEN
  skills/incomplete/SKILL.md                    WRITTEN
  skills/broken-links/SKILL.md                  WRITTEN
  skills/dangling-successor/SKILL.md            WRITTEN
  agents/nameless.md                            WRITTEN
  skills/linked-skill: ABSENT from the target — V11 not lifted by --force (R99)
```

Without `--force`, each of the six was `skipped` with a reason naming its code:

```
  skipped  skills/misnamed/SKILL.md
    skill/misnamed does not validate: V2. Install refuses an artifact whose errors it cannot
    judge the consequences of; --force installs it anyway
```

`skill/messy` carries three V6 WARNINGs and installed in every run — the control that keeps the
refusal from being "refuses everything with a finding".

### 1.5 F-10

```
$ hl … clean --target …/clean/t1
foreign paths in …/clean/t1
  listed (1)
    settings.json
1 path(s) listed. Nothing was removed — pass --remove to delete them.
EXIT=0
settings.json still there? YES

$ hl … clean --foreign --remove --target …/clean/t1
  listed (1)  settings.json
  removed (1) settings.json
  backup      2026-09-21T20-03-08Z
EXIT=0

$ hl … rollback --target …/clean/t1
  restored (1)  settings.json
settings.json after rollback? RESTORED
acb68981366d9bccb83ec79de1d54959897faef3e8b921cf3a50996696eda2ea   (the original digest)
```

### 1.6 F-11

Fixture target, 9 paths, install then rollback, compared on a content-hash manifest of the tree:

```
$ hl … rollback --target …/r1/target
  removed again (5)  …
0 file(s) restored, 5 removed.   EXIT=0

BYTE-IDENTICAL to the pre-install tree (asserted on content hashes, not on the report)
```

Real scale is §2.6 and §2.7.

### 1.7 F-12

```
$ echo "mine, not yours" > …/r1/target/skills/messy/NOTES.md
$ hl … uninstall skill/messy --target …/r1/target
  removed (2)
    skills/messy/SKILL.md
    skills/messy/references/diagram.png
2 file(s) removed. Anything this tool did not install is untouched.   EXIT=0

what survived in skills/messy/:  skills/messy/NOTES.md, skills/messy/references
NOTES.md digest before = 22a881baf36bcbbb5f50fe130428a43decee258b3334859116d7cfa8dbc1d1cc
NOTES.md digest after  = 22a881baf36bcbbb5f50fe130428a43decee258b3334859116d7cfa8dbc1d1cc
```

`--prune` (§1.1's `prune` row applied):

```
$ hl … install --prune --target …/clean/t1
  written (1)            agents/beta.md
  removed (--prune) (1)  skills/alpha/references/notes.md
EXIT=0
```

`settings.json`, the foreign path, is in neither list and was byte-identical afterwards.

### 1.8 F-13

```
t1 manifest = e9fe27fb76467cc038e2bdec068484b3735acf60a1724069cebc47d7c95b69cc.json
t2 manifest = 6cd1bb82113b1582b7422890e3072d23f2341c56dd713976386fba0badc22116.json

(library changed, then installed into t2 only)
t1 manifest unchanged? YES
t1's files unchanged:  YES
```

### 1.9 F-14

```
$ sleep 120 &   # a real live pid, written into the sentinel by hand
$ hl … install --target …/clean/t1
error [LOCK_HELD]: …/manifests/e9fe27…lock is held by process 1376546: another install is
writing to this target, so this run wrote nothing. Wait for it to finish and run again
EXIT=10
TARGET HASH SET UNCHANGED — nothing was written

$ kill %1   # same sentinel, pid now gone
$ hl … install --target …/clean/t1
Complete: everything was applied.   EXIT=0
sentinel left behind? no — released
```

### 1.10 F-15

Per-artifact, on the fixture target's two conflicts:

```
$ hl … install agent/scribe --resolve target --target …/r2/target
resolve target: agent/scribe
  record repaired (1)   agents/scribe.md
  note           the refusal is settled, the file is NOT pinned: the next
                 hl install writes the library's version over the copy you kept.
left alone (9)
  conflict  skills/delivery-lead/SKILL.md        ← the other conflict, still refused

agents/scribe.md before = 4e1fcd0b0b4d7cc004c4996fe02cb2e454bf8c8e307eeecaef7b94f59cd1774b
agents/scribe.md after  = 4e1fcd0b0b4d7cc004c4996fe02cb2e454bf8c8e307eeecaef7b94f59cd1774b
BYTE-IDENTICAL — the user's copy was kept
```

Exit 0 is only reachable on a library with no other refusal, which the fixture library will never
be (§4, warning 1). Against the clean library:

```
$ hl … install agent/beta --resolve target --target …/clean/t1
resolve target: agent/beta
  record repaired (1)  agents/beta.md
Complete: everything was applied.   EXIT=0
beta.md byte-identical? YES
```

`--resolve library`:

```
$ hl … install skill/delivery-lead --resolve library --target …/r7/target
resolve library: skill/delivery-lead
  written (1)  skills/delivery-lead/SKILL.md
target == library? YES
```

`--resolve edit` and R102's `EDITOR_FAILED = 14`:

```
$ env -u EDITOR hl … install agent/scribe --resolve edit --target …
error [EDITOR_FAILED]: no editor is configured: $EDITOR is unset or blank … EXIT=14

$ EDITOR=/nonexistent/editor hl … --resolve edit …
error [EDITOR_FAILED]: the editor '/nonexistent/editor': [Errno 2] No such file or directory …

$ EDITOR="sh -c 'ls -1 \"\$@\"' --" hl … --resolve edit …
resolve edit: agent/scribe
  shown in $EDITOR (1)  agents/scribe.md
EXIT=6                                   ← nothing was decided, so the run stays incomplete
```

`--resolve edit --json` is refused at exit 2, as charter §11 requires.

### 1.11 F-16

```
$ hl … export delivery --output delivery.zip
delivery -> …/delivery.zip
  entries        3
  skills/delivery-lead/SKILL.md
  skills/delivery-lead/references/checklist.md
  agents/scribe.md
unresolved members (1)
  skill/also-never-existed  [MISSING]
EXIT=0
```

Those three are exactly the collection's two resolvable members' files (`hl collections delivery`
lists `skill/delivery-lead` and `agent/scribe`). Binary round-trip and determinism:

```
zip entry skills/messy/references/diagram.png  6b88e7862f089a…  }  identical
on disk   skills/messy/references/diagram.png  6b88e7862f089a…  }

hk.zip   927c47ec5858a34b63cb39df384cd395f266d087070a630bc7548e2731c0f32a
hk2.zip  927c47ec5858a34b63cb39df384cd395f266d087070a630bc7548e2731c0f32a
```

### 1.12 V11

`hl validate` reports the warning against the library:

```
library.yaml
  V11 WARNING: skills/linked-skill is a symlink (-> ../../outside/linked-skill), which is never
  followed or scanned (ruling R6), so skill/linked-skill is absent from this library. Install
  refuses this artifact and applies the rest (skills/linked-skill)
```

`hl install` names it, skips it, applies everything else and exits 6 on the integer:

```
skipped   skills/linked-skill    skill/linked-skill
  skipped  skills/linked-skill
    skill/linked-skill was not installed: its artifact root skills/linked-skill is a symlink
    (-> ../../outside/linked-skill), which is never followed or scanned (V11, ruling R6). …
    so --force does not override this
EXIT=6
```

Neither half was written: `skills/linked-skill` is absent from the target after both a plain and a
`--force` install, and `outside/linked-skill/SKILL.md` is unchanged at
`e77f27ac218cf51e5a28b9f66b6fbc5d32da4d1d869c1a5aac7dd49c2fc7a5c8`.

---

## 2. Deliverable 2 — the real thing, safely

**Method.** `~/.claude` (144 MB, 1382 files and symlinks) was copied with `cp -a` to
`<scratch>/home/.claude`, and `$HOME` was pointed at `<scratch>/home` for every invocation, so
`default_target_root()` and `default_state_root()` both resolve inside the scratch. The library is
a second copy holding only the nine artifacts plus the `library.yaml` of §3. Nothing under
`~/.claude/` was created, modified, deleted or moved; §6 proves it.

### 2.1 `hl diff`

```
1382 path(s) in <scratch>/home/.claude: foreign 1345, manifest_repair 37.
EXIT=0
```

**The scan omitted nothing.** Comparing the plan's path set against `find`:

```
files+symlinks in the target copy: 1382
paths in the plan:                 1382
total missing:                     0
```

The 37 `manifest_repair` rows are every file of all nine artifacts: the user's harness already
holds the library's bytes exactly.

### 2.2 `hl install --dry-run`, with **no** `--target`

Run deliberately without the flag, to prove `~/.claude` resolves inside the redirected home:

```
DRY RUN — nothing was written.
1382 path(s) in <scratch>/home/.claude: foreign 1345, manifest_repair 28, skipped 9.
left alone (9)
  skipped  skills/frontend-system-pattern/SKILL.md
    skill/frontend-system-pattern does not validate: V10. Install refuses an artifact whose
    errors it cannot judge the consequences of; --force installs it anyway
  … (the artifact's other 8 paths)
EXIT=6
```

**The first real install of the user's own library refuses nine of its thirty-seven paths**, and
the cause is a single unquoted colon in one `description:`. See O-3 and §3.

### 2.3 `hl install`

```
1382 path(s) in <scratch>/home/.claude: foreign 1345, manifest_repair 28, skipped 9.
  backup         -
INCOMPLETE …   EXIT=6

NO FILE CHANGED — a MANIFEST_REPAIR-only install writes the record and nothing else

artifacts recorded: 8      files recorded: 28
library_git_sha:   None    backup_id: None
```

### 2.4 Real drift, created by hand

`skills/delivery-lead/references/conflicts.md` deleted from the target (→ `create`);
`skills/backend-system-architecture/references/testing.md` changed in the library (→ `update`);
`skills/solution-designer/SKILL.md` edited in the target (→ `local_edit`).

```
update           skills/backend-system-architecture/references/testing.md
create           skills/delivery-lead/references/conflicts.md
local_edit       skills/solution-designer/SKILL.md
(everything else: unchanged, or foreign)
```

### 2.5 `hl install` over the drift — **the sharpest measurement in this report**

```
  written (2)
    skills/backend-system-architecture/references/testing.md
    skills/delivery-lead/references/conflicts.md
  backup         2026-09-21T20-09-17Z
left alone (10)
  local_edit  skills/solution-designer/SKILL.md
EXIT=6

my LOCAL_EDIT survived?   YES
CREATE restored?          YES
UPDATE written?           YES
skills/synced/ intact?    YES — FOREIGN and untouched (R44)
.credentials.json intact? YES
```

A content-hash diff of the whole 1382-path tree before and after shows **exactly two lines**: the
digest of `testing.md` changing and the line for `conflicts.md` appearing. Nothing else in the
user's harness moved.

`hl install --resolve target skill/solution-designer` then settled the refusal; the edited file
was byte-identical afterwards and no file in the tree changed.

### 2.6 `hl rollback`

```
backup 2026-09-21T20-09-17Z
  restored (1)      skills/backend-system-architecture/references/testing.md
  removed again (1) skills/delivery-lead/references/conflicts.md
1 file(s) restored, 1 removed.   EXIT=0

THE WHOLE 1382-PATH TREE IS BYTE-IDENTICAL to its state before the install
```

`hl uninstall skill/delivery-lead` then removed exactly the six files the record named, out of
1381 paths, and left `skills/delivery-lead/` behind as an empty directory (O-2). A second
`hl rollback` put all six back byte-identical.

### 2.7 `hl clean` — the listing, and then the whole harness

```
$ hl … clean --target <scratch>/home/.claude
foreign paths in <scratch>/home/.claude
  listed (1345)
    .credentials.json
    .last-cleanup
    …
1345 path(s) listed. Nothing was removed — pass --remove to delete them.
EXIT=0                                   (1381 paths still present)
```

On a second, pristine copy, with `--remove`:

```
$ hl … clean --foreign --remove --target <scratch2>/.claude
  backup         2026-09-21T20-11-18Z
1345 path(s) removed. Roll back with hl rollback.
EXIT=0
paths left: 37 (was 1382)      backup size: 144M
```

and then:

```
$ hl … rollback --target <scratch2>/.claude
1345 file(s) restored, 0 removed.   EXIT=0
paths restored: 1382 (was 1382)
BYTE-IDENTICAL: every one of the 1382 paths is back with its original content
```

The one symlink in the tree survived as a symlink with the same destination
(`AGENTS.md -> CLAUDE.md`), and the directory tree is identical to the real one. **Content is
perfectly recoverable. Permissions are not — D-2.**

---

## 3. Deliverable 3 — a real `library.yaml` (prerequisite P-2)

Authored in the scratch library copy. Nine artifacts, two of them redirect stubs, five
collections. Reproduced here in full so the user can adopt it; **it was not written into
`~/.claude/`.**

```yaml
# The harness library of pedro.lana@ctgbr.com.br — nine artifacts.
#
# Authored for prerequisite P-2 of initiative 02-install-and-drift. Two of the nine are
# redirect stubs kept only so an old name still resolves; declaring their supersession here
# is what clears the seven V3 findings their prose citations otherwise produce (L5), because
# charter §8 exempts a superseded artifact from V3.

artifacts:
  skill/backend-system-architecture:
    tags: [backend, python, architecture, reference]

  skill/frontend-system-pattern:
    tags: [frontend, react, typescript, design-system, reference]

  skill/delivery-lead:
    tags: [delivery, orchestration, planning, reference]

  skill/solution-designer:
    tags: [specification, design, discovery, reference]

  # --- the two redirect stubs ------------------------------------------------------------
  # Each cites its successor's `references/` paths as prose. They are not this artifact's
  # files and never were, so the citations are V3 false positives until the supersession is
  # declared. Six of the seven are here; the seventh is below.
  skill/developers-orchestration:
    tags: [deprecated, redirect]
    superseded_by: skill/delivery-lead

  skill/frontend-ctg-system-pattern:
    tags: [deprecated, redirect, ctg]
    superseded_by: skill/frontend-system-pattern

  agent/backend-developer-specialist:
    tags: [backend, specialist, subordinate]

  agent/frontend-developer-specialist:
    tags: [frontend, specialist, subordinate]

  agent/phase-reviewer:
    tags: [review, gate, read-only]

collections:
  backend:
    title: Backend
    description: The skill a backend specialist binds to, and the specialist itself.
    members:
      - skill/backend-system-architecture
      - agent/backend-developer-specialist

  frontend:
    title: Frontend
    description: The skill a frontend specialist binds to, and the specialist itself.
    members:
      - skill/frontend-system-pattern
      - agent/frontend-developer-specialist

  delivery:
    title: Delivery
    description: What the integration owner reaches for, and the reviewer it dispatches.
    members:
      - skill/delivery-lead
      - skill/solution-designer
      - agent/phase-reviewer

  specialists:
    title: The specialist team
    description: Every subordinate agent, addressable as one thing.
    members:
      - agent/backend-developer-specialist
      - agent/frontend-developer-specialist
      - agent/phase-reviewer

  deprecated:
    title: Redirect stubs
    description: Kept only so an older plan or record citing the old name still resolves.
    members:
      - skill/developers-orchestration
      - skill/frontend-ctg-system-pattern
```

### 3.1 Its effect on V3's seven findings

**Before** — L5 predicts seven V3 findings and they are exactly there. It does not predict the
eighth error, and the eighth is not a false positive:

```
$ hl --library <real skills+agents, no library.yaml> validate
skill/developers-orchestration  [INVALID]
  V3 ERROR: SKILL.md cites references/delegation.md,       which does not exist …
  V3 ERROR: SKILL.md cites references/review-and-merge.md, which does not exist …
  V3 ERROR: SKILL.md cites references/plan-formats.md,     which does not exist …
  V3 ERROR: SKILL.md cites references/conflicts.md,        which does not exist …
  V3 ERROR: SKILL.md cites references/cost-and-time.md,    which does not exist …
  V3 ERROR: SKILL.md cites references/collaboration.md,    which does not exist …
skill/frontend-ctg-system-pattern  [INVALID]
  V3 ERROR: SKILL.md cites references/brand-ctg.md,        which does not exist …
skill/frontend-system-pattern  [INVALID]
  V10 ERROR: the frontmatter of SKILL.md does not parse at line 3, column 255:
             mapping values are not allowed in this context (SKILL.md)

9 artifact(s) checked: INVALID. 8 error(s), 0 warning(s).
EXIT=1
```

**After** — all seven V3 findings gone, nothing else changed:

```
$ hl --library <same tree + the library.yaml above> validate
skill/frontend-system-pattern  [INVALID]
  V10 ERROR: the frontmatter of SKILL.md does not parse at line 3, column 255 …

9 artifact(s) checked: INVALID. 1 error(s), 0 warning(s).
EXIT=1
```

Seven for seven. L5 is confirmed exactly, and the mechanism is charter §8's V3 exemption for a
`superseded_by` artifact — not a regex change.

### 3.2 R39 — initiative 01's F-5 gets its real-content proof

F-5's criterion is *"`hl list --collection <key>` returns exactly the declared members"*. Five
collections over real artifacts, each returning exactly what it declares, with no unresolved
member (so no V7):

```
$ hl … collections
KEY          TITLE                MEMBERS  DESCRIPTION
backend      Backend              2        The skill a backend specialist binds to, …
frontend     Frontend             2        The skill a frontend specialist binds to, …
delivery     Delivery             3        What the integration owner reaches for, …
specialists  The specialist team  3        Every subordinate agent, addressable as one thing.
deprecated   Redirect stubs       2        Kept only so an older plan or record citing …
5 collection(s).   EXIT=0

$ hl … list --collection specialists
agent/backend-developer-specialist   file  ok  backend, specialist, subordinate
agent/frontend-developer-specialist  file  ok  frontend, specialist, subordinate
agent/phase-reviewer                 file  ok  review, gate, read-only
3 artifact(s), sorted by name.   EXIT=0

$ hl … list --collection deprecated
skill/developers-orchestration     directory  ok  deprecated, redirect       → skill/delivery-lead
skill/frontend-ctg-system-pattern  directory  ok  deprecated, redirect, ctg  → skill/frontend-system-pattern
2 artifact(s), sorted by name.   EXIT=0
```

**Yes — F-5 now has its real-content proof, and R39 is discharged.** Supersession, tags and
collections all resolve against content nobody designed for them.

---

## 4. Deliverable 4 — T-22's two warnings to T-23

### Warning 1 — "`hl install` over the committed fixture library is `INCOMPLETE = 6` by design, forever"

**CONFIRMED.** Six artifacts carry an ERROR finding and are refused under R75; a seventh root is a
symlink and is refused under R46, which `--force` does not lift. Two more paths are `CONFLICT`
against the committed target.

```
22 path(s) in …/r1/target: conflict 2, create 5, foreign 7, skipped 8.
left alone (10)
  skipped agent/nameless (V5) · skill/broken-links (V3, two paths) · skill/dangling-successor (V4)
  skipped skill/incomplete (V5) · skill/misnamed (V2) · skill/no-entry (V1)
  skipped skill/linked-skill (V11 — --force does not override this)
  conflict agents/scribe.md · conflict skills/delivery-lead/SKILL.md
EXIT=6
```

It is *by design* in the strong sense: charter §10 forbids deleting those fixtures — they are the
regression suite for the reason this product exists. Even `--force` leaves `INCOMPLETE = 6`,
because V11's refusal survives it. **Any future criterion that wants exit 0 through the CLI needs
a library other than the committed fixture one** (this report used a purpose-built clean library,
§1.1).

### Warning 2 — "`--resolve target` is surprising twice over: the *next* plain install overwrites the kept copy (R100)"

**CONFIRMED, with the overwrite observed.**

```
$ hl … install agent/scribe --resolve target --target …/r2/target
  note   the refusal is settled, the file is NOT pinned: the next
         hl install writes the library's version over the copy you kept.
kept (target) = 4e1fcd0b0b4d7cc004c4996fe02cb2e454bf8c8e307eeecaef7b94f59cd1774b

$ hl … diff --target …/r2/target
update     agents/scribe.md      agent/scribe        ← the refusal has become a write

$ hl … install --target …/r2/target
  written (1)   agents/scribe.md
agents/scribe.md now = 630f349e06f80e5bf74056917ea2a11fab5cd091973238bdae8d16dcbc1bbc2a
                     = the library's digest
R100 CONFIRMED: the next plain install OVERWROTE the copy the user kept.
```

Both halves of the surprise are real, and both are honestly signposted: the `note` on the resolve
says it in as many words, and `hl diff` shows `update` before the next install runs. The
observation worth recording is the *direction* of the change: **`--resolve target` converts a
verdict install refuses to touch (`local_edit`) into a verdict install writes without asking
(`update`)**. Resolving a refusal strictly reduces the protection on that file. That is the
documented consequence of "choose a side, no merge UI" (spec §8.5, R54) and is not a defect — but
it is the one place where the tool's safest state is the unresolved one, and the same wording will
have to appear in initiative 03's API. See O-4.

---

## 5. Deliverable 5 — the `library_git_sha` gap (R108). Reported, not fixed.

C-11's field answers *"which version of the library is on this machine"*. It is `null` on every
install this tool performs.

```
$ python3 -m json.tool <the real install's manifest>
{
    "schema_version": 1,
    "target_path": "<scratch>/home/.claude",
    "installed_at": "2026-09-21T…",
    "library_git_sha": null,          ← always
    "backup_id": null,
    "artifacts": [ … 8 artifacts, 28 files … ]
}
```

Every manifest written in this report — fixture installs, the clean-library installs, the real
install, the rollbacks, the resolves — carries `library_git_sha: null`. `apply_install` takes the
value as a keyword argument defaulting to `None` and no caller ever supplies one; nothing in the
project computes a library's HEAD (`infrastructure/timestamps.py` has `_run` and
`_last_commit_date`, both private and both per artifact).

Consequence, stated plainly so it is not discovered later: **two machines that installed two
different versions of one library have manifests that are indistinguishable on that field.** The
per-file digests still tell them apart; the question C-11 says this field answers has no answer.
Acceptance does not add features, so this is recorded and left.

---

## 6. `~/.claude/` is untouched

The narrowed manifest (L47) — `skills/`, `agents/`, `plugins/`, `commands/`, `settings*`, symlinks
recorded by destination and files by sha256 — taken before any work and again after everything
above:

```
before: 926 paths, sha256 4a23cfe98b6b0a45b79d662674346e4ecb79d29846b830a1511f57ccb5e2e205
after : 926 paths, sha256 4a23cfe98b6b0a45b79d662674346e4ecb79d29846b830a1511f57ccb5e2e205
IDENTICAL — nothing under ~/.claude/skills, /agents, /plugins or its settings changed
```

`~/.claude/commands` does not exist and was not created. No state root was created under the real
home (`~/.local/state/harness-library`: absent). The file-mode census of the real tree is
unchanged: 1364 of 1381 files are still not-`0644`, exactly as before.

---

## 7. Deliverable 6 — measurements

**Method.** `/project/harness-library/.venv/bin/hl` invoked directly (not through `uv run`, which
adds its own environment resolution), `$HOME` redirected, wall clock via `date +%s.%N` around each
invocation, **best of N** reported because the distribution is one-sided. The target is a 145 MB /
1382-path `cp -a` copy of the real `~/.claude`; the library is the nine real artifacts. The heavy
pair was re-copied from scratch before each repeat. Nothing else was running.

| Operation | Work done | Best of | Wall |
|---|---|---|---|
| `hl --help` | **the floor** — interpreter start + imports, no work | 5 | **833 ms** |
| `hl validate` | the 9-artifact library alone | 5 | 790 ms |
| `hl diff` | scan 1382 paths / 145 MB, join three sources | 5 | **1294 ms** |
| `hl install` | same, plus writing the record; **0 files written** | 5 | 1296 ms |
| `hl install` | same, plus back up and write **2 files** | 3 | **1752 ms** |
| `hl rollback` | restore 1 file, remove 1, rescan, rewrite record | 3 | **1682 ms** |
| `hl uninstall` | remove 6 files, back up, rescan, rewrite record | 1 | 1295 ms |
| `hl clean --foreign --remove` | back up **144 MB / 1345 paths**, then delete them | 2 | **9977 ms** |
| `hl rollback` (of that) | restore **144 MB / 1345 paths** | 2 | **6676 ms** |

**Is anything slow enough to matter? No — but the shape is not what you would guess.**

* **The floor dominates everything except `clean --remove`.** 833 ms of a 1294 ms `hl diff` is
  process start and imports; the actual scan-and-join of 145 MB is ~460 ms. Initiative 01 measured
  17 ms of scan against a 1.8 s import and deferred the MCP SDK; the floor is now 833 ms and it is
  still the largest single term in every routine command. Anyone optimising `hl diff` should
  measure against 833 ms, not against zero.
* **A write costs about 450 ms more than a read** (1752 vs 1294): that is one backup, one manifest
  write, two file writes and a second pass. It is not per-file — the 6-file uninstall was *faster*
  than the 2-file install, because it does not read the library.
* **`clean --foreign --remove` is the only command in a different class**, and the reason is the
  backup: it copies 144 MB before deleting anything. 10 s is the right price for that guarantee
  and the recovery is 6.7 s. Nothing here needs work.
* **Memory is flat at ~67 MB RSS** for every operation including the 144 MB one — the backup
  streams rather than buffering.

---

## 8. Findings

### D-1 — an unwritable state root is a traceback and exit 1, on every write command

`FilesystemWriteLock._acquire` is the **only** disk step in a write run whose `OSError` is not
translated into a taxonomy code. `infrastructure/lock.py` contains no `except OSError` at all; it
catches `FileExistsError` and nothing else.

```
$ chmod a-w <state_root>/manifests
$ hl … install --target …
  ❱ 183 descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, SENTINEL_MODE)
PermissionError: [Errno 13] Permission denied: '…/manifests/3bca0b62….lock'
EXIT=1

hl uninstall skill/alpha  -> exit 1 | PermissionError
hl rollback               -> exit 1 | PermissionError
hl clean --remove         -> exit 1 | PermissionError
hl diff                   -> exit 0    (reads take no lock, R85)
```

Every *other* failure of the same kind is typed and useful — the backup gives `BACKUP_FAILED = 9`,
the manifest gives `MANIFEST_UNWRITABLE = 11`, the target gives `TARGET_UNWRITABLE = 7`, and each
says what happened to the target. This one gives a 40-line traceback and a status outside C-14's
table, so a script cannot tell it from anything else.

Reachable in the ordinary world: a full disk (`ENOSPC` on the same `os.open`), a `~/.local/state`
left owned by root by one `sudo` run, a read-only or NFS-mounted state root.

**Nothing is lost when it happens** — the lock is taken before the backup, so the target is
byte-identical (verified). This is a diagnosis defect, not a data defect. Closing it needs a C-6
code and a C-14 row, because no existing code fits: `LOCK_HELD` would be false and
`MANIFEST_UNWRITABLE` promises something about the manifest specifically. **Out of T-23's scope;
raised for a ruling.**

### D-2 — a restored file comes back world-readable

Restoring a foreign path puts its **content** back exactly and its **mode** back never.

```
before: 600 …/private.json | 700 …/exec.sh
$ hl … clean --foreign --remove …      2 path(s) removed.
$ hl … rollback …                      2 file(s) restored, 0 removed.
after : 644 …/private.json | 644 …/exec.sh
content preserved? secret
```

On the real harness that is:

| Mode | Files | What they are |
|---|---|---|
| `664` | 1068 | most of the harness |
| `600` | **149** | `.credentials.json`, `history.jsonl`, `daemon/control.key`, `remote-settings.json`, `policy-limits.json`, every session transcript |
| `755` | **56** | scripts, including plugin `bin/` entries |
| `775` | 45 | |
| `766` | 45 | including the agent definitions |
| `764` | 1 | |
| `644` | **17** | the only ones a restore gets right |

1364 of 1381 files change mode on a restore; 149 of them become world-readable and 56 stop being
executable.

**Root cause, stated so it is not mis-diagnosed.** The obvious suspect is
`FilesystemTargetRepository.write`, which does `chmod(FILE_MODE)` — that is correct for an
installed artifact (R9, R56: mode is excluded from the content hash, and every file in the real
library is `-rwxrw-rw-` by accident of how it was copied) and wrong for a restore, which is
putting back a file this tool did not create. But fixing `write` alone cannot work: **the mode is
already gone before restore runs.** `FilesystemBackupStore.create` saves through the same
repository, so the copy under `backups/<id>/files/` is itself `644` —

```
$ stat -c '%a %n' <backup>/files/.credentials.json
644 …/files/.credentials.json
```

— and `BackupRecord` has no mode field at all (`schema_version`, `backup_id`, `created_at`,
`target_path`, `paths`, `kept`, `links`). The information does not exist anywhere by restore time.

**Severity.** This is the only place in the initiative where the *recovery* path makes a user
worse off than the operation it recovers from. A user who runs `clean --foreign --remove`, sees the
listing, thinks better of it and rolls back gets their files back — with their credentials
world-readable and their hook scripts no longer executable, and with no message saying so.

Closing it is a **C-13 amendment** (a per-path mode in the record) plus a restore write that does
not normalise. **Out of T-23's scope; raised for a ruling.**

### O-1 — `hl diff` does not name a V11-skipped artifact

`hl install --dry-run` lists `skipped skills/linked-skill`; `hl diff` over the same library and
target does not mention it at all (21 rows vs 22). This is by construction — `diff_against_target`
is the read-side use case and is not handed `symlinked_roots()`, which only `_plan` passes — and
`hl diff`'s own docstring says `--dry-run` is the command that names what install would refuse.
It is still the case that the command a user reaches for to ask *"what is the state of my
harness?"* is silent about the one artifact that is invisible, which is the failure V11 exists to
make visible. `hl validate` does report it.

### O-2 — an emptied directory is left behind, and it is V1-shaped

Uninstall documents this (`uninstall.py`: *"A directory is never removed (C-12)"*) and rollback
does not, but both do it. After rolling back a *first* install, the target keeps
`skills/legacy-orchestration/`, `skills/legacy-ctg-pattern/` and `skills/messy/references/` as
empty directories. An empty `skills/<name>/` in a real harness is precisely V1 — *"a skill
directory with no `SKILL.md` — observed twice; both loaded silently as nothing"*. The tool's own
recovery path creates the condition its first validation rule exists to report. Harmless and
visible; worth a sentence in `rollback.py`'s docstring at least.

### O-3 — one of the user's nine real artifacts does not validate, for a reason worth knowing

`skills/frontend-system-pattern/SKILL.md` is V10: its `description:` is an unquoted YAML scalar
containing `: ` — *"Covers every brand: the project's brand reference is the visual authority"* —
which ends the scalar and makes the frontmatter block a malformed mapping. **Claude Code's own
loader accepts the file and lists the skill; PyYAML does not.**

`hl` is not wrong: the file is not valid YAML, V10 is correctly raised with a line and column, and
it correctly suppresses the V2/V3/V5 cascade behind it (R33, R37). But R75 then refuses to install
the artifact, so **the user's first real `hl install` would leave nine of thirty-seven paths
unwritten for a skill that works today**, and the remedy is `--force` or quoting one string.

This is a product question for the lead, not a code change: *should an artifact the harness itself
loads be refused because a stricter parser rejects it?* Quoting the description fixes it in one
edit and is probably the right answer; the alternative is a narrower V10 that only fires when the
document is unusable rather than when it is non-standard.

### O-4 — `--resolve target` moves a file from "never touched" to "overwritten next time"

See §4, warning 2. Signposted by the `note` and by `hl diff`, and a direct consequence of R100 and
of spec §8.5's "no merge UI". Flagged because initiative 03 will render the same transition in a
UI, where a one-line note is easier to miss than in a terminal, and because there is no way at all
to express *keep mine permanently* — a user who wants that must stop installing that artifact.

### O-5 — the listing is the safety model, and at 1345 lines it stops being one

`clean --foreign` on the real harness lists 1345 paths, including `.credentials.json` and
`history.jsonl`, and the summary line is *"1345 path(s) listed. Nothing was removed — pass
`--remove` to delete them."* Nobody reads 1345 lines. R96's model — *"they are protected by being
shown to you first"* — was designed against a fixture with seven foreign paths and holds perfectly
there; against a real harness the listing is longer than the terminal scrollback and the one thing
a user most needs to notice (`.credentials.json`, line 2) scrolls past in the first screen.

Nothing is broken. But the honest reading is that on a real target the protection is the backup
and the rollback, not the listing — and the backup is 144 MB per run.

### O-6 — backups accumulate with no surface to see or remove them

`BackupStore` keeps every backup forever. There is no `hl backups` command, no retention, and no
way to delete one through the CLI. `hl rollback [BACKUP_ID]` takes an id **the user has no way to
discover except by listing the state directory by hand**, which makes "undo three installs instead
of one" — the stated reason the argument exists — unreachable in practice. Each
`clean --foreign --remove` on a real harness costs 144 MB of state.

### O-7 — a `MANIFEST_REPAIR`-only install writes no backup and no files

`backup_id: null` on the real install, because `_take_backup` returns `None` when the plan has
nothing to write or delete. Correct — there is nothing to protect — but it means the *first*
install into an already-populated harness is not rollback-able:

```
$ hl … install --target …     backup -    Complete: everything was applied.   EXIT=0
$ hl … rollback --target …
error [BACKUP_FAILED]: no backup '(most recent)' is available for this target, so there is
nothing to put back. …
EXIT=9
```

"The install that did nothing" is exactly the one a user might want to undo after discovering the
record now claims 28 of their files, and the answer they get is a status named `BACKUP_FAILED`.
Two unrelated situations — *the backup could not be taken, so nothing was written* and *there is
nothing here to put back* — share exit 9, which is the one thing C-14 says a status must not do.
Worth a sentence in `install`'s help and, arguably, a code of its own.

---

## 9. What I could not prove, and why

| Claim | Why not |
|---|---|
| F-8: the rule never emits `SKIPPED`; the three impossible hash combinations raise | Domain-level. Proved by `tests/domain/test_install_plan.py` inside the green gate; there is no CLI surface for an impossible digest triple, which is the point. |
| F-9: *the manifest exists before the first file write*, by injected failure | Not injectable through the CLI. **Corroborated** at CLI level by a real failure instead (§1.3): a read-only target left the manifest on disk over-claiming three unwritten paths. |
| F-9: apply never writes a path absent from the plan (write-recording fake) | Requires a fake; unit-level, in the gate. |
| F-15 exit 0 against the **committed fixture** library | Unreachable by construction — see §4 warning 1. Proved against a purpose-built clean library instead. |
| `MANIFEST_UNWRITABLE = 11` through the CLI | The lock sentinel lives in `manifests/`, so making that directory unwritable fails the lock first — which is how D-1 was found. The code is proved at unit level in the gate. |

---

## 10. Gate

Run whole, one command, exit code read without a pipe (L2, L44):

```
$ uv run ruff format --check . && uv run ruff check . && uv run mypy src tests \
    && uv run lint-imports && uv run pytest
157 files already formatted
All checks passed!
Success: no issues found in 134 source files
layered-architecture KEPT
mcp-is-read-only KEPT
domain-is-pure KEPT
Contracts: 3 kept, 0 broken.
======================= 1038 passed in 79.79s (0:01:19) ========================
GATE EXIT=0
```

No source file was changed by this task. No commit was authored.
