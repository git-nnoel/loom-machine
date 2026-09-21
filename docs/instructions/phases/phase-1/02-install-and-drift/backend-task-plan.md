# Backend task plan — T-12, the verdict rule and the install plan entity

Initiative 02 · phase 1 · base commit `2b1b380` · owner `backend-developer-specialist`.
Realises contracts **C-9** (`Verdict`) and **C-10** (`PlanEntry`, `InstallPlan`). Pure domain, zero I/O.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/install_plan.py` | new. Holds `Verdict`, the equality table, the presence rule, `PlanEntry`, `InstallPlan`. One module, because the verdict vocabulary and the entity that carries it are one decision — splitting them would let a rename land on one side only |
| `tests/domain/test_install_plan.py` | new |
| `tests/domain/test_purity.py` | one line: `install_plan` joins `EXPECTED_MODULES` (L13, L18) |

Nothing else is touched. No `pathlib`, no `os`, no `io`, no `time`, no clock, no dependency change.

## 2. The rule, as two functions

Presence is resolved before equality (R55). The two halves are separate functions because only the
second one can be handed an impossible input:

* `decide_verdict(library_sha, manifest_sha, target_sha) -> Verdict | None` — the presence layer.
  `None` means "absent from all three sides", which is *not an entry at all* rather than an error:
  the caller (T-15) unions three path sets and skips what no side holds. It returns `None` rather
  than raising for the same reason `identity.parse_artifact_id` does — the caller is enumerating,
  not asserting.
* `verdict_for_equalities(library_equals_manifest, manifest_equals_target, library_equals_target)`
  — the all-three-present table, keyed on the three booleans. Five of the eight boolean triples are
  in `VERDICT_BY_EQUALITY`; the other three violate transitivity and raise a bare `ValueError`
  (no `ErrorCode`: they are unreachable states, not user-facing errors).

The three violations are **unreachable through `decide_verdict`**, because equality of three real
strings is transitive. That is precisely why the table function is public: a rule that can only be
proven by a test it cannot be given an input for is a rule nobody has seen fail.

`decide_verdict` calls `verdict_for_equalities`. One decision, one object.

## 3. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| Who fills `PlanEntry.reason` on `CONFLICT` | `plan_entry_for(...)` does, from the presence pattern that produced it. The four conflicts have four different causes; if T-15 wrote the sentences it would be re-deriving, at a distance, what the rule already knew |
| `counts` and `is_complete` as stored fields | realised as **properties** over `entries`. A stored count that can disagree with the entries it counts is the drift C-10 exists to prevent; every consumer still reads `plan.counts` / `plan.is_complete` |
| Is `counts` dense or sparse | **dense**: all nine verdicts, in declaration order, zeros included. `counts[Verdict.SKIPPED]` is `0`, never a `KeyError` — R52 wants a consumer able to *count* a verdict, and a renderer can filter zeros |
| `artifact_id` on a `FOREIGN` path | **not validated**. A foreign file outside every artifact root belongs to no artifact, so `""` must stay constructible. Flagged to the lead — T-14/T-15 decide what they put there |
| Is `reason` required on `SKIPPED`/`CONFLICT` | yes, enforced in `__post_init__`. The converse does **not** hold: another verdict may carry a reason |

## 4. Tests

Presence: six cases, nine rows (the three conditional cases carry both branches), asserted as
verdict values. Equality: the five reachable triples through `decide_verdict` with real shas; the
three transitivity violations through `verdict_for_equalities`, each with `pytest.raises`, plus a
positive control in the same test proving the function still reaches its table. A 4x4x4 sweep over
`{None, a, b, c}` asserts the produced set is exactly the eight producible verdicts, that `SKIPPED`
is never among them, and that no input raises. `is_complete` is false for each of `LOCAL_EDIT`,
`CONFLICT` and `SKIPPED`, each row carrying the same plan without the blocking entry as its control.

The `InstallPlan` tests build their entries by hand rather than through the rule, so the mutation
below reddens the rule's table and nothing else.

## 5. Mutation check (L35 — read this if the session was interrupted)

Mutation: in `VERDICT_BY_EQUALITY`, the row `(False, False, True)` — library differs from manifest,
manifest differs from target, library equals target — maps to `Verdict.UNCHANGED` instead of
`Verdict.MANIFEST_REPAIR`. Must fail: the manifest-stale row of the equality table, by verdict
value. Must stay green: every other row.

While the mutation was applied, `src/harness_library/domain/install_plan.py` was deliberately
wrong; the backup was taken at
`…/scratchpad/install_plan.py.orig` and the file restored from that copy rather than from memory of
the edit. A red gate here with an otherwise complete diff would be a mutation in flight, not
unfinished work.

**Result — the mutation is no longer applied; the module matches its backup by md5.** Under it,
`uv run pytest tests/domain -q` gave `1 failed, 197 passed`, the failure being
`test_the_equality_table_when_every_side_holds_the_path[only-the-manifest-is-stale]` with
`assert <Verdict.UNCHANGED: 'unchanged'> is <Verdict.MANIFEST_REPAIR: 'manifest_repair'>`. Every
other row of the table, both presence rows that reach `MANIFEST_REPAIR` and every `InstallPlan`
test stayed green. Restored: `198 passed`.

One structural note for the next mutation check here: the equality table is reachable through two
entry points, `decide_verdict` and `verdict_for_equalities`. Its five verdict values are asserted
**only** through `decide_verdict`, and `verdict_for_equalities` is asserted only on the three
raises plus one positive control. Asserting the same five rows at both entry points would have
reddened two tests under this one mutation and destroyed the independence control.

## 6. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time. Baseline 437 passed.

---

# Backend task plan — T-13, the manifest and the C-6 amendment

Initiative 02 · phase 1 · base commit `e2fc3c0` · owner `backend-developer-specialist`.
Realises contract **C-11** (`Manifest`), **C-14** (five install exit statuses) and the whole
**C-6 amendment** (five error codes). DEC-14 fixes where the file lives.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/manifest.py` | new. `Manifest` and `ManifestArtifact` — C-11's entity, pure, reusing C-1's `ArtifactFile`. A module of its own rather than a section of `install_plan.py`: the plan is a *judgement* and the manifest is a *record*, and T-18's rollback and T-19's prune read the record without ever building a plan |
| `src/harness_library/domain/errors.py` | five `ErrorCode` members, and **one** exception class — `ManifestError`, the only one this task emits |
| `src/harness_library/cli/exit_codes.py` | five statuses and their five `EXIT_STATUS` rows. Nothing else |
| `src/harness_library/infrastructure/manifest_store.py` | new. Where the manifest is, how it is written, and the loudly-failing reader |
| `tests/domain/test_manifest.py` · `tests/infrastructure/test_manifest_store.py` | new |
| `tests/domain/test_purity.py` | one line: `manifest` joins `EXPECTED_MODULES` (L13, L18) |
| `tests/cli/test_exit_codes.py` | **added to, never altered.** Two new tests over the five new rows; every existing test is untouched and must stay green |

No dependency change. The manifest is JSON — `json` is stdlib, so L17's PyYAML trap is not met.

## 2. The three behaviours, and why absent is `None`

`read_manifest(...) -> Manifest | None`.

* **Absent** — no file. `None`. "Nothing was installed into this target yet", and a first install
  must work.
* **Corrupt** — the file exists and cannot be used. `ManifestError`, carrying the location.
* **Wrong-shaped** — parses as JSON, but a field has the wrong type, a key is unknown, or a
  required key is missing. Also `ManifestError`, carrying the **field path** inside the document.

`None` rather than `Manifest.empty()` for the absent case, which is where this reader parts company
with `read_library_metadata`. An empty manifest is a **real value**: after `hl uninstall` the target
has a manifest recording zero artifacts, and that is not the same fact as "this target was never
installed into". Collapsing them would cost T-18 and T-19 the distinction, and would make the
mutation below unable to tell its two tests apart.

## 3. Where the fault is

Two kinds of location, because JSON gives two:

* a **parse** failure has `lineno`/`colno` from `json.JSONDecodeError` → `path:line:column: reason`,
  the same shape `LibraryYamlError` renders;
* a **shape** failure has no line — `json.loads` has already thrown the positions away — so it
  carries a `location`, the field path inside the document (`artifacts[0].files[1].sha256`), and
  renders as `path: artifacts[0].files[1].sha256: reason`.

`ManifestError` therefore carries `path`, `line`, `column`, `location` and `reason`. Tests assert on
`error.line` and on `error.location`, not merely that something was raised.

**L23 is met head-on:** `UnicodeDecodeError` and `json.JSONDecodeError` are both `ValueError`
subclasses. Decoding and parsing are two separate `try` blocks with two separate messages, so a
binary manifest is reported as "not UTF-8 text" and never as a syntax error at line 1.

## 4. Keying, and R43

`~/.local/state/harness-library/manifests/<sha256 of the target path>.json`, per DEC-14.

* the hashed string is `str(Path(target).resolve())`, so `~/.claude`, `~/.claude/` and a relative
  spelling of the same directory key the same manifest, and two different directories key two
  different ones — which is what makes R43's "multiple targets are near-free" true rather than
  hopeful. Asserted on the paths, both directions.
* the digest is `domain.hashing.hash_bytes`, not a second `hashlib` call. Charter §7 keeps one
  hashing implementation, and a second one here would drift exactly where it matters.
* the **state root is a parameter**, never read from the environment inside the store. Every test
  passes `tmp_path`. `default_state_root()` exists beside it, computes `~/.local/state/
  harness-library` and creates nothing; the composition root (T-22) is what calls it.
  Charter §13 keeps `os.environ` in `cli/settings.py`, so `$XDG_STATE_HOME` is **not** consulted —
  flagged as an open point rather than decided here.
* the writer is **atomic**: a sibling temp file plus `os.replace`. A crash mid-write is precisely
  how a corrupt manifest gets made, and this task exists to make the manifest trustworthy.

## 5. `schema_version`, and what it is not

The document carries `"schema_version": 1`. This is a **document** field and not a `Manifest`
field — C-11's entity is untouched. Without it, a manifest written by a later `hl` reads as
"unknown key", which is the diagnosis for corruption and the wrong thing to tell a user whose file
is fine. Flagged to the lead: the contract did not ask for it and did not forbid it.

## 6. All five codes, only one class

`ErrorCode` gains `TARGET_UNWRITABLE`, `MANIFEST_UNREADABLE`, `BACKUP_FAILED`, `INCOMPLETE` and
`LOCK_HELD`, and `EXIT_STATUS` gains their five rows — 7, 8, 9, 6 and 10, fixed by C-14 and R57/R59
and not chosen here. I-8 is then total again, so T-16 through T-22 add a raise site rather than a
red gate.

Only **one** exception class is added: `ManifestError`, for the one code this task emits.
`errors.py`'s docstring says a new code means a new class; that sentence is amended in the same
edit, because the four remaining classes would need constructor fields — what a backup failure
carries, what a held lock carries — that belong to T-16 and T-17 and would be guessed here. The
contract is the **code**, per charter §9; the class arrives with its raise site.

## 7. Mutation check (L35 — read this if the session was interrupted)

Mutation: in `infrastructure/manifest_store.py`, the corrupt path returns an empty manifest instead
of raising. Must fail: the corrupt-manifest test. Must stay green: the absent-manifest test.
Backup at `…/scratchpad/manifest_store.py.orig`; the file is restored from that copy, not from
memory of the edit.

**Result — the mutation is no longer applied; the module matches its backup by md5**
(`49af775fb3a21814f21fb1956d5e8480`). Under it, `uv run pytest tests/infrastructure/
test_manifest_store.py tests/domain/test_manifest.py -q` gave `3 failed, 45 passed`. Narrowed to
the two named tests: `1 failed, 1 passed` — `test_a_corrupt_manifest_fails_loudly_and_names_the_line`
failed with `Failed: DID NOT RAISE ManifestError`, and
`test_an_absent_manifest_is_nothing_installed_here_yet` **stayed green**, which is the control that
matters: the reader is not conflating "no file" with "bad file". The other two reddened tests are
the same corrupt path under two other documents (a zero-byte file, and `{oops}`), which is expected
— the mutation was applied to the `json.JSONDecodeError` branch and to nothing else, so every
wrong-shape test stayed green too. Restored: `48 passed`.

One note for the next mutation check here: the damaged path has **three** entry points into one
branch, so a mutation on it reddens three tests. Keeping the named subject narrow
(`-k "corrupt_manifest_fails_loudly or absent_manifest_is_nothing"`) is what makes the control
legible rather than buried in a list of failures.

## 8. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time. Baseline 484 passed.

---

# Backend task plan — T-14, the target scanner and the committed target fixture

Initiative 02 · phase 1 · base commit `771fa36` · owner `backend-developer-specialist`.
Realises contract **C-12** (`TargetFile`, `TargetRepository`) and prerequisite **P-3** (the committed
target fixture). Also closes ruling **R60** on `PlanEntry.artifact_id`.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/target.py` | new. `TargetFile` and the `TargetRepository` protocol. C-12 puts the protocol in `domain/`, so it lands beside C-4's `ArtifactRepository` and is satisfied structurally, never inherited |
| `src/harness_library/infrastructure/target.py` | new. `FilesystemTargetRepository` — the walk, the hashing, and the four path operations |
| `src/harness_library/domain/install_plan.py` | **one change only**: `PlanEntry.artifact_id` and `plan_entry_for`'s parameter become `str \| None` (R60), with the docstring that described the empty string corrected in the same edit |
| `tests/domain/test_target.py` · `tests/infrastructure/test_target.py` | new |
| `tests/domain/test_purity.py` | one line: `target` joins `EXPECTED_MODULES` (L13, L18) |
| `tests/domain/test_install_plan.py` | **one test changed**, named in §6 below |
| `tests/infrastructure/conftest.py` | `FIXTURE_TARGET` and a `fixture_target` fixture, mirroring `fixture_library`. Presence precondition only — no verdict in shared plumbing (L29) |
| `tests/fixtures/target/**`, `tests/fixtures/outside/target-escape.md` | the committed fixture (P-3) |
| `tests/fixtures/README.md` | the fixture's inventory, path by path |

No dependency change; everything used is stdlib or already imported elsewhere in `infrastructure/`.

## 2. A target is not a library

The library scanner walks *artifact roots* it knows the registry layout of, and it **filters**: a
vendor tree, a `.git`, an editor swap file and a symlink are each skipped and reported as a
`SkippedPath`. The target scanner filters **nothing**. It has no registry, no artifact roots and no
idea which of the paths it finds this tool put there. Everything on disk is an entry, including the
editor swap file the library scanner refuses — which is the single sharpest test of the difference,
and is in the suite as exactly that.

**R44 in particular:** Claude Code's `synced/` bucket gets no named exclusion. It is foreign like
anything else the library and the manifest both disown, and a named exclusion would silently hide
whatever else lands in that directory. Mutation (b) below is that rule, made falsifiable.

## 3. What C-12 left open, and what I decided

| Open point | Decision |
|---|---|
| `TargetFile.sha256` is `str`, but a symlink is never hashed (R6) | the digest is the **empty string** for a symlink and only for a symlink, enforced one way in `__post_init__`: `is_symlink` ⇒ no digest. The converse — a regular entry must carry one — is deliberately **not** enforced; see §7, it would turn the required mutation into a raise and destroy its control. `size` is the link's own `lstat` size, which is real |
| `TargetFile` has no `is_text` | C-12 gives it no field and no member of C-12 needs one: a target is written and hashed, never searched. The decision itself stays `infrastructure.scanner.is_text` over the bytes `read_bytes` returns — one implementation, asserted in the suite against the fixture's PNG and its markdown sibling. Flagged: if T-21's diff wants the flag stored, that is a C-12 amendment |
| A path the scan cannot read | the `OSError` **propagates**. An unreadable file reported as absent is judged `CREATE` by the verdict rule and overwritten on the next apply, which is the single worst thing this layer could do quietly |
| A fifo, socket or device node | skipped, because C-12 has no channel to report it and `read_bytes` on a fifo blocks forever. Flagged |
| A target root that does not exist | `FileNotFoundError`, mirroring `FilesystemArtifactRepository.__init__`. Creating a target is a policy decision for the composition root (T-22), not a repository behaviour |
| File mode on `write` | `0644` for the file, `0755` for each directory it creates (R56, F-9). `write` is the only thing that creates a file in the target, so leaving mode to the process umask is how a strict umask ships an unreadable harness |
| Atomicity of `write` | **not** atomic, unlike the manifest store. A temp file left behind by a crashed `os.replace` would sit in the user's target and read `FOREIGN` forever; T-16's backup is the recovery mechanism |
| Error type for a rejected path | plain `ValueError`, the posture `infrastructure/repository.py` already takes. C-6's `INVALID_FILE_PATH` carries an `artifact_id` a target path does not have |

## 4. Path safety, in one place

`_locate(path)` is the only way any of `read_bytes`, `write`, `delete` and `exists` reaches the disk.

1. **Shape**, before anything touches the filesystem: empty, `.`, absolute, or any `..` component is
   a `ValueError`. A property of the string, so it holds on a target that does not contain the
   escaped-to file.
2. **No intermediate symlink.** Every component but the last is checked with `is_symlink()` and
   refused, because a symlinked directory is how a relative path with no `..` in it still lands
   outside the target (R6).
3. **Containment, re-checked** on the resolved parent. Redundant given 1 and 2, kept for the reason
   `FilesystemArtifactRepository._resolve` keeps its third stage: it is the one that still holds if
   a future change loosens either of the others.

`read_bytes` and `write` additionally refuse a final component that is a symlink. `delete` does
not — `os.unlink` on a link removes **the link**, which is the opposite of following it.

## 5. The fixture (P-3)

`tests/fixtures/target/`, committed, distinct from `~/.claude/` and from `tests/fixtures/library/`.
Its symlink points at `tests/fixtures/outside/target-escape.md`, a **real** file, because a broken
one makes `ruff` exit 2 before any rule runs (L21); it resolves outside the target root, which is
the escape R6 names. Inventory is in `tests/fixtures/README.md`, path by path.

## 6. The one existing test that changes

`tests/domain/test_install_plan.py::test_a_foreign_path_may_belong_to_no_artifact` asserted
`PlanEntry(artifact_id="")` is constructible and that `entry.artifact_id == ""`. R60 retires that
answer. It now asserts `artifact_id is None` for the same `settings.json` foreign path, and its
docstring cites R60 instead of describing the empty string as honest. Every other test in that file
is untouched.

## 7. Mutation checks (L35 — read this if the session was interrupted)

Two, because the dispatch and the initiative plan's §9 row name different ones. Both are one-line
edits to `src/harness_library/infrastructure/target.py`, backed up first to
`…/scratchpad/target.py.orig` and restored from that copy rather than from memory of the edit.

**(a) the dispatch's.** `scan()` reports `is_symlink=False` for every entry.
Must fail: `test_the_scan_records_the_fixtures_real_symlink_as_one`.
Must stay green: `test_an_ordinary_file_in_the_same_scan_is_not_a_symlink`.
Run alone as `-k "records_the_fixtures_real_symlink or ordinary_file_in_the_same_scan"` (L42).

This is why `TargetFile.__post_init__` enforces `is_symlink ⇒ no digest` and **not** its converse: a
two-way invariant would make the mutated scan *raise* on the fixture's link, reddening every test
that scans it and burying the control the dispatch requires.

**(b) the plan §9 row's.** "Stop recording foreign paths", as the named exclusion R44 forbids:
`if child.name == "synced": continue` in the walk.
Must fail: `test_the_foreign_synced_tree_is_recorded_whole`.
Must stay green: `test_the_loose_foreign_settings_file_is_recorded` — also foreign, so the mutation
cannot take its subject away, and `test_the_installed_files_are_recorded`.

**Result — neither mutation is applied; the module matches its backup by md5**
(`8f8911478283841e49c9f59fff3cb3c3`).

Under (a), `-k "records_the_fixtures_real_symlink or ordinary_file_in_the_same_scan"` gave
`1 failed, 1 passed`: `test_the_scan_records_the_fixtures_real_symlink_as_one` failed with
`assert False is True` on
`TargetFile(path='skills/delivery-lead/references/elsewhere.md', sha256='', size=36, is_symlink=False)`,
and the ordinary-file control **stayed green** — which is the half that matters, because "always
`False`" and "correct for ordinary files" are otherwise the same result. Restored: `2 passed`.

Under (b), `-k "foreign_synced_tree_is_recorded_whole or loose_foreign_settings_file or
installed_files_are_recorded"` gave `1 failed, 2 passed`:
`test_the_foreign_synced_tree_is_recorded_whole` failed on
`assert 'skills/synced/.bucket-7c1f9a2e' in [...]`, and both controls stayed green — the loose
foreign file in particular, so the mutation could not take the subject away by making *nothing*
foreign appear. Restored: `3 passed`.

One note for the next mutation check here: `test_the_scan_records_every_path_in_the_fixture_in_a_deterministic_order`
holds the golden path list and therefore reddens under (b) as well. It is kept out of the `-k`
filter deliberately, and it asserts **paths only, never `is_symlink`**, so it does not redden under
(a) and is not a second copy of either named subject.

## 8. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time. Baseline 536 passed.

---

# Backend task plan — T-15, the three-source join and the two use cases

Initiative 02 · phase 1 · base commit `93e3549` · owner `backend-developer-specialist`.
Builds `PlanInstall` (`application/write/`) and `DiffAgainstTarget` (`application/read/`) over
contracts **C-4**, **C-9**, **C-10**, **C-11** and **C-12**. Also carries **R69** (`PlanEntry.
artifact_id` rejects `""`) and **R68** (`TargetFile.sha256` becomes `str | None`).

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/application/read/drift.py` | new. `diff_against_target`, and the join — `target_path_of`, `target_sha_of`, `UNHASHED_TARGET_SHA` |
| `src/harness_library/application/read/__init__.py` | re-exports the four new names, per this package's rule that a caller never has to know which module a name lives in |
| `src/harness_library/application/write/install.py` | new. `plan_install` — the first module in `application/write/` |
| `src/harness_library/application/write/__init__.py` | re-exports `plan_install` |
| `src/harness_library/domain/install_plan.py` | **one guard only**: `PlanEntry.__post_init__` rejects `artifact_id=""` (R69) |
| `src/harness_library/domain/target.py` | **R68**: `sha256: str \| None`, the one-way invariant restated against `None` |
| `src/harness_library/infrastructure/target.py` | **R68's third mirror.** `NO_DIGEST` becomes `None`. Outside the dispatch's constraint list and done anyway — see §3 |
| `tests/application/fakes.py` | `FakeTargetRepository` (C-12) and the builders the drift tests read from |
| `tests/application/test_drift.py` · `tests/application/test_install.py` | new |
| `tests/test_architecture.py` | the module-path guard — the **only** thing that catches mutation (a) |
| `tests/domain/test_install_plan.py` · `tests/domain/test_target.py` · `tests/infrastructure/test_target.py` | R69 and R68 |

No new `domain/` module, so `tests/domain/test_purity.py` is untouched (L13, L18). No dependency
change.

## 2. The join — one key, three vocabularies

The key is the **target-relative path**. Each source speaks a different one:

| Source | What it holds | How it reaches the key |
|---|---|---|
| library (C-4) | `Artifact.files[].path`, relative to the **artifact root** | `target_path_of(type, name, file.path)` |
| manifest (C-11) | `ManifestArtifact.files[].path`, also artifact-root-relative, with no root recorded anywhere in the document | `parse_artifact_id` → the same `target_path_of` |
| target (C-12) | `TargetFile.path`, already relative to the **target root** | itself |

`target_path_of` is `registry.TypeSpec`, never a literal:

* `DIRECTORY` kind → `f"{spec.root_path(name)}/{file_path}"` — `skills/delivery-lead/SKILL.md`;
* `FILE` kind → `f"{spec.directory}/{file_path}"` — the artifact root **is** the entry document, so
  joining onto it would give `agents/scribe.md/scribe.md`. The result is `root_path(name)` exactly.

Nothing stores the prefix. C-11 records no target-relative path on purpose: one copy per file would
repeat the same string N times and one per artifact would be a second source of truth for a layout
`TypeSpec` already owns, and the two would disagree the first time a type's directory moved.

**A path that cannot be joined.** Only the manifest can produce one — an `artifact_id` that is not
`<type>/<name>`, which `ManifestArtifact` accepts (it rejects only the empty string) and the store's
reader does not check. `plan_install` **raises `ValueError`** naming the id. Skipping it silently is
the worse failure: that artifact's installed files would then be held by neither the library nor the
manifest, read `FOREIGN`, and become unprunable and ununinstallable — orphaned by the very record
that exists to make them removable. Flagged: the guard belongs on `ManifestArtifact.__post_init__`,
where `manifest_store._build` would render it as a located `ManifestError`, and C-11 is frozen.

**Attribution of a target-only path.** R60 says `artifact_id` is `None` only for a path under **no**
artifact root. So a foreign path is attributed to the artifact whose root contains it, where that
root is one the library or the manifest actually holds — `skills/delivery-lead/SKILL.md.swp` carries
`skill/delivery-lead`. A root nobody holds attributes nothing: `skills/synced/...` is not an artifact
root just because it is shaped like one, so every path of that tree carries `None` (R44, no named
exclusion anywhere in this module), and so does `settings.json`.

**A target path with no digest is present, not absent.** `TargetFile.sha256` is absent for a symlink
(R6 never hashes one). Passing that through as `target_sha=None` would tell the verdict rule the
target does not hold the path — `CREATE`, and the next apply writes straight through the link. So
`target_sha_of` answers `UNHASHED_TARGET_SHA`, a sentinel no digest can equal, and the rule reaches
`LOCAL_EDIT` or `CONFLICT` by the ordinary table. It reads `file.sha256 or UNHASHED_TARGET_SHA` —
**truth, not `is not None`** — so it is correct under T-14's `""` and under R68's `None` alike.

## 3. The two decisions this task had to make outside its contracts

**Where the composition lives.** In `read/drift.py`; `write/install.py` calls it. Not the other way
round: `mcp/tools.py` imports the `application.read` package, `import-linter`'s forbidden contracts
see **indirect** imports, so a `read → write` edge would make `mcp-is-read-only` fail the moment the
name was re-exported. Composing a plan writes nothing, so the read side is where it belongs. What
`write/` owns is the decision to act on it, and it is the place T-20's V11 refusal and T-21's
`--resolve` narrowing land — which is why `plan_install` is a separate symbol rather than an alias.

**R68's third mirror.** The dispatch authorises `domain/target.py` and says the symlink digest
becomes `None`, "replacing T-14's enforced empty-string sentinel". `infrastructure/target.py` is the
only producer of that sentinel and is not on the constraint list. Left alone, the change is either
vacuous (the scanner still emits `""`) or red (the new invariant rejects `""` on a link and every
scan of the fixture raises). One line — `NO_DIGEST = ""` → `NO_DIGEST: str | None = None` — plus its
docstring. Reported prominently; revertible on its own.

`manifest` is a **required** keyword argument on both use cases, with no `None` default. A caller
that forgot it would judge every path `CREATE` and overwrite the whole target, which is the exact
catastrophe the manifest exists to prevent.

## 4. Tests

`tests/application/**`, fakes only, zero disk (charter §10). `FakeTargetRepository` records writes
and deletes and renders no verdict (L29).

* every one of the eight producible verdicts, from three sources, **asserted as a verdict value**;
* the sweep: `SKIPPED` is 0 in a plan that carries all eight, and each of the eight is ≥ 1 — the
  eight are the positive control for the absence of the ninth;
* the symlink over an installed path, parametrised over **both** spellings of "no digest", asserted
  `LOCAL_EDIT` (and `CONFLICT` when the library has also moved on), never `UNCHANGED`, with the
  regular-file sibling as the control and a test that its `target_sha` is not `None`;
* the `synced/` tree, every path `FOREIGN` with `artifact_id is None`;
* the `FILE`-kind join, which the `DIRECTORY` formula would have got wrong;
* `diff_against_target` writes nothing — with the positive control that the fake does record a write;
* the module-path guard in `tests/test_architecture.py`.

## 5. Mutation checks (L35 — read this if the session was interrupted)

Both are backed up to `…/scratchpad/<file>.orig` first and restored from that copy.
**Neither is applied; the result is recorded below.**

**(a) `PlanInstall` moved into `application/read/`.** `read/drift.py` grows the definition and
`write/install.py` imports it, so `plan_install.__module__` becomes a read module.
Must fail: `tests/test_architecture.py::test_every_write_use_case_is_defined_in_the_write_package`.
Must stay green: `lint-imports` — deliberately, because it is blind to this.
`-k "write_use_case_is_defined_in_the_write_package or import_contracts_are_kept"`.

**(b) the library's paths left artifact-root-relative** — `_library_files` yields `file.path`
instead of the joined path, dropping the `TypeSpec.root_path` join.
Must fail: `tests/application/test_drift.py::test_a_library_file_and_its_identical_installed_copy_are_unchanged`.
Must stay green: `tests/application/test_drift.py::test_the_foreign_synced_tree_is_foreign_whole`,
so the mutation cannot pass by making everything foreign.
`-k "identical_installed_copy_are_unchanged or foreign_synced_tree_is_foreign_whole"`.

**Result — neither mutation is applied.** `write/install.py` matches its backup by md5
(`03aaa6747e60f9fef09c441af3516a75`) and `read/drift.py` matches its own
(`cbada6d3eca8bf004bdc1c38c812462e`).

Under (a), the filter gave `1 failed, 4 passed`:
`test_every_write_use_case_is_defined_in_the_write_package[plan_install]` failed with
*"plan_install is exported from harness_library.application.write but defined in
harness_library.application.read.drift"*, and `lint-imports` **stayed green** — run on its own it
still reported `layered-architecture KEPT · mcp-is-read-only KEPT · domain-is-pure KEPT`, exit 0.
That is the finding, not an accident: the contract forbids a module path and cannot see which
functions are in it, so this one test is the whole guard. Restored: `5 passed`.

Under (b), the filter gave `1 failed, 1 passed`:
`test_a_library_file_and_its_identical_installed_copy_are_unchanged` failed with
`assert <Verdict.PRUNE: 'prune'> is <Verdict.UNCHANGED: 'unchanged'>` — the library's `SKILL.md`
stopped being the same path as its installed copy, so only the manifest and the target still held
it. `test_the_foreign_synced_tree_is_foreign_whole` **stayed green**, which is what stops the
mutation passing by making everything foreign. Restored: `2 passed`.

Fifteen tests in `tests/application/` redden under (b) — every test whose subject *is* the join.
They are kept out of the filter deliberately, the way T-14 kept its golden path list out of its
own: the control that matters is the foreign one, and it is unaffected either way.

## 6. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time (L2), exit code read without a pipe (L44). Baseline 584 passed.

---

# Backend task plan — T-16, the backup store and the apply

Initiative 02 · phase 1 · base commit `011762f` · owner `backend-developer-specialist`.
Realises contract **C-13** (`BackupStore`, `BackupRecord`) and `ApplyInstall`, and carries three
corrections: **R73** (`target_path_of` moves to `domain/registry.py`), **R74** (the `<type>/<name>`
guard onto `ManifestArtifact`) and **R75** (an ERROR finding makes an artifact `SKIPPED`).
**Ruling R63 — back up, write the manifest, write the files — is the task.**

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/backup.py` | new. C-13's `BackupRecord` and `BackupStore`. A module of its own rather than a section of `manifest.py`: a backup is a *copy of a target*, a manifest is a *record of an install*, and T-18 restores one without reading the other. Costs one line in `tests/domain/test_purity.py` (L13, L18) |
| `src/harness_library/domain/manifest.py` | **R74**'s guard on `ManifestArtifact.__post_init__`, and the **`ManifestStore` protocol** — see §3, it is the one seam no contract named |
| `src/harness_library/domain/registry.py` | **R73**. `target_path_of` lands beside `root_path` and `entry_path`, the third answer in the same family |
| `src/harness_library/domain/errors.py` | `MANIFEST_UNWRITABLE` (C-14, R64) and three classes for codes that have been in the contract since T-13: `BackupFailedError`, `TargetUnwritableError`, `ManifestWriteError` |
| `src/harness_library/cli/exit_codes.py` | `MANIFEST_UNWRITABLE = 11` and its row. I-8 keeps the table total |
| `src/harness_library/infrastructure/backup.py` | new. `FilesystemBackupStore` under the state root |
| `src/harness_library/infrastructure/manifest_store.py` | `FilesystemManifestStore` — the protocol over the module functions already here |
| `src/harness_library/application/write/install.py` | `apply_install`, `ApplyResult`, and R75's narrowing on `plan_install` |
| `src/harness_library/application/read/drift.py` · `read/__init__.py` | R73's mirrors. This **deletes** a function |
| `tests/domain/test_backup.py` · `tests/infrastructure/test_backup.py` | new |
| `tests/application/fakes.py` | `FakeBackupStore`, `FakeManifestStore`, and real bytes behind `FakeTargetRepository` so "byte-identical" is an assertion over content and not over a recording |
| `tests/domain/test_registry.py` · `test_manifest.py` · `test_purity.py` · `tests/infrastructure/test_manifest_store.py` · `tests/application/test_drift.py` · `test_install.py` · `tests/test_architecture.py` · `tests/cli/test_exit_codes.py` | the mirrors, each named in §7 |

No dependency change; everything used is stdlib or already imported in `infrastructure/`.

## 2. R63, as five steps and one rule

```
1  decide          which entries are written, which are deleted, which are left alone
2  back up         every path step 1 will write or delete
3  write manifest  composed from the library, the previous manifest and step 1
4  write files     then delete the pruned ones
5  report          ApplyResult, from which the caller exits INCOMPLETE
```

**The manifest is written before the first file and that is the whole ordering.** A crash between
the two can only make the manifest *over*-claim, and over-claiming is self-correcting: a path the
manifest names that was never written comes back `LOCAL_EDIT` or `CONFLICT` on the next `hl diff`,
which is a decision the user is asked to make. The other order loses files: a crash after the last
write and before the manifest leaves every installed path held by neither the library's record nor
the manifest, so it reads `FOREIGN` — install will not touch it and uninstall cannot remove it, and
nothing this initiative ships can recover it. Under this order `MANIFEST_UNWRITABLE` always means
*nothing happened*.

**No rollback.** A failure at file *k* leaves files 1…k−1 written and the manifest already on disk.
That is the over-claim the ordering is designed around, and undoing it is T-18's rollback from the
backup this task takes. The suite asserts the byte-identical case at the boundary the ordering
actually guarantees: a failure injected into the **first** write.

Per verdict: `CREATE` and `UPDATE` are written · `MANIFEST_REPAIR` changes the manifest and touches
**no file** · `UNCHANGED` and `FOREIGN` are untouched · `LOCAL_EDIT`, `CONFLICT` and `SKIPPED` are
left alone and named in `ApplyResult.left_alone` · `PRUNE` is deleted only when `prune=True`.

## 3. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| **Apply must write the manifest and `application/` may not import `infrastructure/`** | a **`ManifestStore` protocol** on `domain/manifest.py`, one member, `write(manifest)`. The one seam no contract named — C-13 gave apply a backup store and C-12 a target, and left the manifest as module functions in `infrastructure/`. It is additive: C-11's entity is untouched. Beside `Manifest` rather than in a module of its own, mirroring `domain/target.py`'s `TargetFile` + `TargetRepository` |
| Which paths are backed up | **every path the run will write or delete**, not only those the target already holds. A path the target does not hold is recorded in the backup and holds no bytes, so a restore *removes* it — which is what makes a first install undoable. `backup_id` is `None` only for a run that writes and deletes nothing. C-11's prose ("`None` when none was needed — a first install into an empty target overwrites nothing") reads the other way and is the narrower rule; flagged |
| What `BackupStore.create` is given | **target-relative paths** (R21, C-12's vocabulary). The store knows its own target root |
| How a restore tells "saved" from "was absent" | the presence of `files/<path>` inside the backup. Not a second list in `backup.json`, which would be a second source of truth for the same fact |
| A damaged or half-written backup directory | skipped by `list()`. The opposite posture to `read_manifest`'s, deliberately: a half-written backup is exactly what a crashed `create` leaves, and restoring half a target is worse than not offering it. A damaged *manifest* read as empty destroys files; a backup omitted from a listing costs a rollback point |
| Where R75's refusal belongs | **`plan_install`, not `diff_against_target`.** `write/install.py`'s own docstring already fixed it: "every narrowing that belongs to acting rather than to describing lands here and must not reach the report". A drift report describes what is there; refusing to install an invalid artifact is a decision to act. `force=True` is simply the narrowing not applied, so nothing is lost under it — including a `CONFLICT`'s reason |
| Which of an invalid artifact's entries become `SKIPPED` | every entry the **library** holds for it. Not its `FOREIGN` neighbours: install never writes or removes a foreign path, and calling one `SKIPPED` would claim a decision is owed where none is. `PRUNE` is unreachable — an artifact the library no longer holds carries no findings |
| What the new manifest records for a path that was **not** written | the digest the **previous** manifest recorded. Recording the library's digest for a conflicted path would turn a `CONFLICT` into a `LOCAL_EDIT` on the next run and lose the fact that three versions exist. A path with no previous record and no write is recorded nowhere |
| `ManifestArtifact.content_hash` of a partly-applied artifact | `content_hash_of_files` over the files actually recorded, always — so the whole-artifact digest describes the file list beside it rather than an artifact state that is not installed anywhere |
| Where the bytes to write come from | `library.read_bytes(artifact_id, file_path)`, keyed by re-deriving **the same forward join** `plan_install` used. There is no inverse join and there should not be one: `target_path_of` is one-way for `FILE` kind, and a second implementation of the layout is what R73 exists to prevent |
| Whether apply re-scans the target | **no.** It acts on the plan it was given. A re-scan would be a second snapshot, and two snapshots disagreeing is how a path gets written on the strength of a verdict decided about a different file |

## 4. R73, R74, R75 — the three corrections

**R73** moves `target_path_of(artifact_type, name, file_path)` verbatim into `domain/registry.py`.
Kept a module-level function rather than promoted to a `TypeSpec` method: the ruling says *move*,
and a method would rename every call site's shape as well as its import. `application/read/` stops
re-exporting it — R77 accepted that re-export when the function lived in `read/drift.py`, and a
`domain/` function is reachable from every layer without one.

**R74** puts `parse_artifact_id` on `ManifestArtifact.__post_init__`. `manifest_store._build`
already turns a domain `ValueError` into a located `ManifestError` carrying `MANIFEST_UNREADABLE`,
so the guard earns the right code, the right exit status and the field path for free.
`drift._identity_of`'s raise stays: it is now unreachable through a constructed `Manifest`, which is
the point, and `parse_artifact_id` still returns `str | None` so the narrowing is not dead code.

**R75** is a plan-time narrowing with an apply-time consequence. `plan_install(..., force=False)`
replaces the verdict of every library-held entry of an artifact carrying an ERROR finding with
`SKIPPED`, whose `reason` names the codes that fired. A WARNING never refuses anything (R22).

## 5. Tests

`tests/application/` against fakes, zero disk. `tests/infrastructure/` against `tmp_path`.
**Nothing anywhere writes to `~/.claude/`**; the real tree is hashed before and after this task and
compared by content, never by mtime (L37).

The fakes gain real bytes: `FakeTargetRepository` now holds a content map, so every "byte-identical"
assertion in this task is made **on the file's content** and never on the write recorder. The
recorder is still there and is what proves the negative — *apply never writes a path absent from the
plan* — with the positive control in the same test.

## 6. Mutation checks (L35 — read this if the session was interrupted)

Three, each named in the dispatch and in the plan's §9. All three are one-line edits to
`src/harness_library/application/write/install.py`, backed up first to
`…/scratchpad/install.py.orig` and restored from that copy rather than from memory of the edit.

**(a)** the manifest is written **after** the files instead of before.
Must fail: `test_the_manifest_is_on_disk_before_the_first_file_is_written`.
Must stay green: `test_a_complete_plan_writes_every_file_and_records_them_all`.

**(b)** the backup is skipped when the plan has **more than one** entry.
Must fail: `test_a_backup_of_every_path_the_run_touches_is_taken_before_any_write` (two entries).
Must stay green: `test_apply_refuses_when_the_backup_cannot_be_taken` (one entry), so the mutation
cannot take its own subject away.

**(c)** the conflicted artifact is written along with the safe ones —
`Verdict.CONFLICT` joins `WRITTEN_VERDICTS`.
Must fail: `test_a_mixed_plan_writes_the_safe_entries_and_leaves_the_conflict_byte_identical`,
asserted on the conflicted file's **bytes**.
Must stay green: `test_a_complete_plan_writes_every_file_and_records_them_all`, the all-safe run.

**Result — none of the three is applied; the module matches its backup by md5**
(`7d2021712f7fe459f6fc758641df68b5`).

Under **(a)**, `-k "manifest_is_on_disk_before_the_first_file or
complete_plan_writes_every_file_and_records_them_all"` gave `1 failed, 1 passed`:
`test_the_manifest_is_on_disk_before_the_first_file_is_written` failed on its own message —
*"the manifest must already be on disk when the first file write happens (R63) … assert None is
not None"* — and the happy-path apply **stayed green**, which is the half that matters: a run
that does not fail cannot tell the two orders apart, so that control is the whole reason the
failing test has to inject a failure at all. Restored: `2 passed`.

Under **(b)**, `-k "backup_of_every_path_the_run_touches or refuses_when_the_backup_cannot_be_taken"`
gave `1 failed, 1 passed`:
`test_a_backup_of_every_path_the_run_touches_is_taken_before_any_write` failed with
`assert [] == [('skills/delivery-lead/SKILL.md', 'skills/phase-reviewer/SKILL.md')]`, and
`test_apply_refuses_when_the_backup_cannot_be_taken` **stayed green** — its plan has exactly one
entry, so the mutation could not take its own subject away by skipping the backup there too.
Restored: `2 passed`.

Under **(c)**, `-k "mixed_plan_writes_the_safe_entries or
complete_plan_writes_every_file_and_records_them_all"` gave `1 failed, 1 passed`:
`test_a_mixed_plan_writes_the_safe_entries_and_leaves_the_conflict_byte_identical` failed on the
conflicted file's **bytes** — `assert b'# the library has moved on\n' == b'# and then the user
edited it\n'` — and the all-safe run **stayed green**. The failure is on content and not on the
report, which is the point: a report saying "I left it alone" is exactly what the wrong
implementation also says.

One note for the next mutation check here: `test_a_complete_plan_writes_every_file_and_records_them_all`
is the named control for **two** of the three mutations, and it can be, because neither (a) nor
(c) changes what a complete, all-safe run does. Nothing else in `tests/application/test_install.py`
asserts the manifest's position relative to the file writes — the ordering has exactly one
witness, and it is the only test in the suite that injects a failure into the first write.

## 7. Existing tests changed, and what each asserts now

* `tests/application/test_drift.py::test_a_manifest_artifact_whose_id_is_not_an_identity_is_refused`
  — same subject, one layer lower. Under R74 the refusal now fires in `ManifestArtifact`'s
  constructor, before a plan can be built at all; the test says so and keeps its `match`.
* `tests/application/test_drift.py` imports `target_path_of` from `domain.registry` (R73), and the
  three tests that exercise the join move to `tests/domain/test_registry.py` with the function.
* `tests/test_architecture.py` — `WRITE_USE_CASES` gains `apply_install`, and the
  exports-exactly test gains a `WRITE_TYPES` tuple so `ApplyResult` is covered rather than
  excepted. The guard is unchanged in kind: nothing leaves `application/write/` unchecked.
* `tests/cli/test_exit_codes.py` — **added to, never altered**, as in T-13.

## 8. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time (L2), exit code read without a pipe (L44). Baseline 635 passed.

---

# Backend task plan — T-17, the single-writer advisory lock

Initiative 02 · phase 1 · base commit `3f980dc` · owner `backend-developer-specialist`.
Realises charter §12 / ruling **R50** — an `O_EXCL` sentinel beside the manifest, held for the
duration of an apply, released on exit, stale-broken by a pid check — and adds
**`TARGET_UNREADABLE`**'s `ErrorCode` member and exit row (**R81**, C-14).

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/lock.py` | new. The `WriteLock` protocol, one member. A module of its own rather than a section of `manifest.py`: the lock is *not* the record, and T-18's rollback will take it without reading a manifest. Costs one line in `tests/domain/test_purity.py` (L13, L18) |
| `src/harness_library/domain/errors.py` | `TARGET_UNREADABLE` (R81) and the `LockHeldError` class over the `LOCK_HELD` code T-13 put in the contract |
| `src/harness_library/cli/exit_codes.py` | `TARGET_UNREADABLE = 12` and its row. I-8 keeps the table total |
| `src/harness_library/infrastructure/lock.py` | new. `FilesystemWriteLock` — the sentinel, the pid check, the release |
| `src/harness_library/application/write/install.py` | `apply_install` gains a required keyword-only `lock` and wraps its whole body in it |
| `tests/domain/test_lock.py` · `tests/infrastructure/test_lock.py` · `tests/test_single_writer.py` | new |
| `tests/application/fakes.py` · `tests/application/test_install.py` · `tests/domain/test_purity.py` · `tests/cli/test_exit_codes.py` | the mirrors, each named in §7 |

No dependency change: `os`, `json`, `socket` and `contextlib` are stdlib.

## 2. The mechanism, exactly as R50 fixes it

```
acquire   os.open(<state_root>/manifests/<key>.lock, O_CREAT|O_EXCL|O_WRONLY)
          → writes {schema_version, pid, hostname, created_at}; keeps the inode
held      the whole of apply — the backup, the manifest and every file
release   finally: unlink, but only if the inode is still the one we created
refused   a sentinel whose pid is alive → LockHeldError (LOCK_HELD = 10), nothing written
broken    a sentinel whose pid is gone, or whose document names no pid at all → unlinked, one
          retry; if that retry also collides, someone won the race and this run is refused
```

**Keyed per target (R43), by the manifest's own key** — `manifest_path_for(...).with_suffix(".lock")`.
Not a second derivation of the key: two spellings of "which target is this" is exactly what
`canonical_target_path` exists to prevent, and `.with_suffix` is what makes "beside the manifest"
a fact rather than a comment. Two targets therefore have two sentinels and never block each other.

**Where the error is raised, and why this one is not a builtin.** `manifest_store.write_manifest`
and `FilesystemBackupStore.create` let an `OSError` out and `application/` gives it a code
(ruling R24), because the *application* is what interprets an I/O fault. A held lock is not an
I/O fault: only the lock can tell "held by a live process" from "stale, break it" from "the state
directory is broken", and a `FileExistsError` arriving at `apply_install` could not be
re-interpreted into any of the three. So `FilesystemWriteLock` raises `LockHeldError` itself —
`read_manifest`'s posture, which raises `ManifestError` for the same reason: it is a judgement
about content, not a failed syscall passed along. There is no translation for a fake to
pre-supply.

## 3. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| **Who takes the lock** | `apply_install`, as a required **keyword-only** parameter with no default, wrapping its entire body. Not the composition root: T-22 has not been written, T-18 adds two more write use cases, and a lock a caller may forget is a lock that is not there. A default would make running unlocked a typo rather than a decision — the same argument `manifest` already carries, asserted the same way |
| Where the protocol lives | `domain/lock.py`, satisfied structurally like C-4, C-12, C-13 and C-15 (R14) |
| What `hold()` returns | an `AbstractContextManager[None]`. A context manager and not `acquire`/`release`: the release has to happen on **every** exit, and a pair of methods is a pair a caller can half-use |
| A sentinel that does not parse, or names no pid | **stale, break it.** An empty sentinel is exactly what a crash between `O_EXCL` and the first `write` leaves, and a document that cannot name a holder cannot claim one is alive |
| A sentinel naming *this* process | **held, refused.** The lock is per target, not per process; two threads in one process interleaving two applies is the failure it exists to prevent |
| Whether release may remove someone else's sentinel | no. The inode captured at acquire is compared before the unlink, so a run whose sentinel was broken as stale cannot delete the sentinel of the run that broke it |
| pid reuse | fails **safe**: a reused pid reads as alive, so the lock is refused rather than broken. The remedy is the one `LOCK_HELD` already documents — wait and run again |
| `hostname` | recorded, and deliberately **not** part of the decision. R50 says pid check, and a pid compared across two hosts is meaningless either way; the field is there so a human reading a wedged sentinel can see it came from another machine. Flagged to the delivery lead |
| `TARGET_UNREADABLE`'s class | **none.** Nothing emits it: T-14's scanner propagates a bare `OSError` and translating that is not this task. The code and its row exist so I-8 has something to hold, which is the direction charter §9 fixes — a code may arrive before its class, never the reverse |

## 4. Tests

`tests/domain/` — the protocol is satisfied structurally, with its positive control.
`tests/infrastructure/test_lock.py` — real sentinels under `tmp_path`: the path is beside the
manifest, the file appears and disappears, a live holder is refused, a dead one is broken, an
empty one is broken, a release does not take a sentinel it did not create, two targets are held
at once.
`tests/application/test_install.py` — apply's control flow against a fake lock: the lock is taken
**before the backup**, released on success, and released on each of T-16's three failure paths.
`tests/test_single_writer.py` — **the one cross-layer module in the suite**, and it has to be:
the exclusion is infrastructure and the thing it protects is an application use case, so neither
layer alone can witness it. A real `FilesystemWriteLock`, a real `FilesystemTargetRepository` and
a real `apply_install`, with the second apply fired from inside the first apply's first write.

Nothing writes to `~/.claude/`; `default_state_root()` stays uncalled outside the composition
root, and every state root in this task is `tmp_path`.

## 5. Mutation checks (L35 — read this if the session was interrupted)

Two. Each is a one-line edit backed up first to `…/scratchpad/<name>.orig` and restored from that
copy. **No file is mutated as this plan is written**, and both modules match their backup by md5: `install.py` `9c16d304baf905f385f526d5e9a5c532`, `lock.py` `7349edd749eebb0c3e7f4b86e9f15678`.

**(a)** the plan's named row — the lock is released **before** the write instead of after
(`src/harness_library/application/write/install.py`: `with lock.hold(): pass` and the body after
it). Must fail: `test_a_second_apply_against_a_held_lock_writes_nothing`, on the target's hash
set *and* on the status. Must stay green: `test_a_single_apply_writes_every_file_and_leaves_no_sentinel` —
without it, "the lock is never taken" and "the lock is released too early" look the same.

**(b)** mine — the pid check never breaks a sentinel
(`src/harness_library/infrastructure/lock.py`: `_is_running` returns `True` unconditionally).
Must fail: `test_a_stale_sentinel_whose_process_is_gone_is_broken_and_the_apply_proceeds`. Named
precisely, because the shape matters: under this mutation the dead holder reads as alive, so the
apply is **refused** with `LockHeldError` where it should have proceeded — the failure is at the
`run_apply` call and the installed file's bytes are never written, which is the claim. Must stay green: `test_a_second_apply_against_a_held_lock_writes_nothing` —
a mutation that merely deleted the lock would redden it, so the pair separates "never breaks" from
"never locks".

**Result — neither is applied; both modules match their backup by md5.**

Under **(a)**, `-k "a_second_apply_against_a_held_lock_writes_nothing or
a_single_apply_writes_every_file_and_leaves_no_sentinel"` gave `1 failed, 1 passed`:
`test_a_second_apply_against_a_held_lock_writes_nothing` failed on its own message — *"the second
apply was not refused: while one apply holds this target's lock, another must exit LOCK_HELD
rather than interleaving its writes with the first's (R50)"*, `assert False … isinstance(None,
LockHeldError)` — and the `SecondRun` in that failure shows the other half of the criterion too:
`before` holds one path and `after` holds three, so the second apply had written both files. The
single-apply control **stayed green**, which is the half that matters: without it, "the lock is
never taken" and "the lock is released too early" produce the same one failing test.
Restored: `2 passed`.

Under **(b)**, `-k "a_stale_sentinel_whose_process_is_gone_is_broken_and_the_apply_proceeds or
a_second_apply_against_a_held_lock_writes_nothing"` gave `1 failed, 1 passed`: the stale-sentinel
test failed with `LockHeldError: …<key>.lock is held by process 571841` raised out of
`_acquire` — a pid that had already exited, read as alive, so the apply was refused where it
should have proceeded and the target was never written. The second-apply test **stayed green**,
which separates "never breaks a sentinel" from "never locks at all": a mutation that simply
removed the lock would have reddened it instead. Restored: `2 passed`.

One note for the next mutation check here: `test_a_second_apply_against_a_held_lock_writes_nothing`
is the must-fail of (a) and the must-stay-green of (b), which it can be because the two mutations
move in opposite directions — one releases the lock too early, the other never releases a stale
one. It is also the only test in the suite that runs two applies at once, so if it is ever
deleted the lock has no witness at all.

## 6. Existing tests changed, and what each asserts now

* `tests/application/test_install.py` — the module's `apply()` helper passes a `FakeWriteLock`.
  Every existing test keeps its subject and its assertions; what changes is that each now runs
  under a lock, which is the point.
* `tests/domain/test_purity.py` — `EXPECTED_MODULES` gains `"lock"`. L13's two-edit cost, paid.
* `tests/cli/test_exit_codes.py` — **added to, never altered**, as in T-13 and T-16.

## 7. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time (L2), exit code read without a pipe (L44). Baseline 707 passed.

---

# Backend task plan — T-18, rollback and uninstall

Initiative 02 · phase 1 · base commit `abdcdb8` · owner `backend-developer-specialist`.
Realises **F-11** (rollback) and **F-12** (uninstall, without `--prune`, which is T-19's), over
contracts **C-11**, **C-12**, **C-13**, **C-15** and **C-16**. Rulings **R79**, **R80**, **R82**,
**R83**, **R56**, **R44** and **R63** bind.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/application/write/rollback.py` | new. `rollback_install`, `RollbackResult`. A module of its own rather than a section of `install.py`: rollback never reads the library and never builds a plan, and the one thing it shares with apply is the lock |
| `src/harness_library/application/write/uninstall.py` | new. `uninstall_artifact`, `UninstallResult`. Separate from rollback for the same reason those two are separate from apply: uninstall never reads a backup record and rollback never reads an artifact id |
| `src/harness_library/application/write/__init__.py` | re-exports the four new names |
| `src/harness_library/domain/errors.py` | **two classes, no new code.** `BackupNotFoundError` over `BACKUP_FAILED` and `RestoreFailedError` over `TARGET_UNWRITABLE`. Charter §9 fixes the direction — a code may arrive before its class, never the reverse — and both codes have been in the contract since T-13. `cli/exit_codes.py` is **untouched**: no `ErrorCode` member is added, so I-8 stays total on its own |
| `tests/application/test_rollback.py` · `tests/application/test_uninstall.py` | new. Fakes only, zero disk |
| `tests/application/fakes.py` | `FakeBackupStore` gains a real restore over a `FakeTargetRepository`, and `FakeManifestStore` is unchanged. See §5 |
| `tests/test_rollback.py` | new, and **cross-layer by necessity** — see §5. The one place the restore is real |
| `tests/test_single_writer.py` | **added to, never altered.** Rollback's and uninstall's lock witnesses, in T-17's working shape |
| `tests/test_architecture.py` | `WRITE_USE_CASES` and `WRITE_TYPES` gain the four names |

No new `domain/` module, so `tests/domain/test_purity.py` is untouched (L13, L18). No dependency
change; nothing here is outside `{domain,infrastructure,application}` but the two test modules and
this plan.

## 2. Rollback — what it does, and in which order

```
1  lock        R82: required, keyword-only, wrapping every step below
2  restore     backups.restore(backup_id) — C-13's mechanism, run as a unit
3  scan        the target, once, after the restore
4  manifest    composed from the manifest it was given and that scan
```

**The order is restore-then-record, and it is the mirror of R63 rather than a copy of it.** R63
writes apply's manifest *first* because apply makes files appear, and a manifest written after them
can disown a file that is on disk — which reads `FOREIGN`, and nothing in this initiative can touch
a foreign path. Rollback makes files *disappear* (and reappear at older bytes), so the same rule —
**the manifest must never disown a file that is still on disk** — points the other way: record
last. A crash between the restore and the manifest leaves the manifest still claiming the
post-apply digests, so the restored paths come back `LOCAL_EDIT` or `CONFLICT` and a path the
restore removed comes back `CREATE`. Every one of those is a decision the user is *asked* about.
The opposite order is not merely unsafe here, it is impossible: the restored state is the only
source for the digests the new manifest records, and it does not exist until the restore has run.

**The manifest after a rollback is composed from the target, not from the record.** The manifest
that described the pre-apply state is gone — apply overwrote it, and `ManifestStore` has one
member. So for every artifact the current manifest records, every file it records is joined onto
the target with `registry.target_path_of` and kept **only if the target still holds it**, carrying
the digest and size the target now holds and the `is_text` the record already had (C-12 has no
`is_text`; charter §7 keeps one implementation of that decision and this is not a second one). An
artifact with no file left is dropped. `library_git_sha` becomes `None` — the restored bytes came
from a library state this run cannot name, and C-11 makes `None` an honest answer rather than a
missing one. `backup_id` becomes `None`: rollback takes no backup, and the way forward from a
rolled-back target is an install, which takes its own.

**Why this is the right digest.** A path the backup restored held, before the apply, exactly what
the *previous* install put there — `UPDATE` means the target held what the manifest recorded, and
`CREATE` means it held nothing. So reading the digest back off the restored disk reproduces the
previous manifest's digest for every path it can, without a second record to keep in step. A path
whose pre-apply content was a user's edit is never in the backup at all: `LOCAL_EDIT` and
`CONFLICT` are left alone by apply, so apply never backs them up and rollback never restores them.

## 3. Uninstall — what it does, and in which order

```
1  lock        R82
2  back up     every path this run will delete — see §4, the one decision outside the dispatch
3  delete      every path the manifest records for this artifact that the target holds
4  manifest    the same manifest with that artifact's record dropped
```

Driven off `manifest.artifacts[...].files`, joined with `target_path_of`, and off **nothing else**.
It never scans for what is under the artifact's root, which is the whole of F-12: a foreign file
beside an installed one is not in the manifest, so it is not in the list, so it survives. A path
the manifest records and the target no longer holds is passed over rather than raised on — the
file is already not there, which is the outcome uninstall is for. R44 gets no mention anywhere in
this module, because a named exclusion is exactly what would be needed if the list came from a
directory walk instead of from the record.

**Delete-then-record, for the reason rollback records last.** A manifest written first would drop
the artifact and then crash mid-delete, leaving its remaining files on disk claimed by nobody —
`FOREIGN`, untouchable by install and unremovable by uninstall. Deleting first can only leave the
manifest over-claiming files that are already gone, which comes back `CREATE` on the next diff and
is repaired by running uninstall again or by reinstalling.

A directory is never removed (C-12 says so, and `delete` refuses one), so an emptied artifact root
stays behind as an empty directory. An `artifact_id` the manifest does not record raises
`ArtifactNotFoundError` — charter §13's posture, fail loudly rather than silently do nothing.

## 4. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| **What the manifest says after a rollback** | composed from a scan of the restored target (§2). C-11 keeps one manifest per target and `ManifestStore` has no `read`, so the pre-apply record is genuinely gone; the restored disk is the only source there is |
| Which backup a rollback restores | an explicit `backup_id`, required and keyword-only. `Manifest.backup_id` is the obvious default and is **not** taken as one: `backups.list()` offers older backups too, and the caller choosing is the difference between "undo the last install" and "undo the last *three*" |
| **Does uninstall take a backup** | **yes** — the one decision outside the dispatch's letter, and separable in one parameter. Uninstall is the most destructive operation this tool has, and F-9's argument ("a write with no way back is the failure mode this initiative exists to remove") applies to a delete without modification. It is also what makes `hl rollback` able to undo an `hl uninstall`, which is the only thing that makes the pair coherent. Flagged to the lead |
| A path the manifest records whose target copy was **edited** | removed like any other. The dispatch fixes the criterion — "exactly what the manifest records for that artifact and nothing else" — and the backup above is what makes it recoverable. Flagged: refusing an edited path would need `INCOMPLETE`'s vocabulary and T-21's `--force`, and it is a ruling, not a task-level choice |
| A backup id that names nothing | `BackupNotFoundError`, code `BACKUP_FAILED`, exit 9 — the status whose remedy is already "go and look at where backups live". A new class over an existing code, which is the shape T-16 and T-17 both used |
| `OSError` out of `restore` | `RestoreFailedError`, code `TARGET_UNWRITABLE`, exit 7 — C-13 documents that `OSError` there means the target could not be written. It carries the **backup id** and not a path, because C-13 restores as a unit and the failing path is not something the seam reports. R83: a plain OS fact, coded in `application/` |
| **A partially unreadable backup** | rollback **restores what the store can and refuses to guess at the rest**; it does not pre-flight and it does not undo. The remedy is that `restore` is idempotent — the same backup restored twice produces the same target — so a rollback that failed half way is completed by running it again, which is a property apply does not have and is the reason apply needed this feature and this feature needs nothing beyond itself. Crucially the manifest is **not** written on that path, so nothing is disowned. **And the sharper half:** a backup whose `files/<path>` was *removed* rather than made unreadable raises nothing at all — C-13 infers "was absent when the backup was taken" from the tree, so the path is **deleted** from the target. Flagged; it is a C-13 question, not a T-18 one |
| A symlink sitting at a manifest-recorded path after a restore | not recorded in the new manifest. `TargetFile.sha256` is `None` for a link (R6, R68) and `<unhashed>` is a plan-time sentinel, never a digest (`application/read/drift`); putting either into `ArtifactFile.sha256` would make the manifest claim a digest nothing has |
| `installed_at` on both | a required parameter, never a clock — the same rule `apply_install` keeps (R66, and every assertion about the record would otherwise depend on how fast the suite ran) |

## 5. Tests, and why one module is cross-layer

`tests/application/test_rollback.py` and `tests/application/test_uninstall.py` are fakes only and
zero disk (charter §10). What they cannot see: that a real restore puts real bytes back, that a
delete lands on the right file, that a directory survives. `FakeBackupStore` gains a real restore
**over a `FakeTargetRepository`** so that the application layer can assert on content rather than
on a recording — the same upgrade T-16 made to `FakeTargetRepository`, and for the same reason: a
recorder can be empty because nothing happened or because nothing recorded it.

`tests/test_rollback.py` is **cross-layer by necessity**, the second module in this suite that has
to be, and for the same shape of reason `tests/test_single_writer.py` gives: the thing F-11 claims
is a fact about a real directory — "the target is empty again, per path" — and the code that makes
it true is split across `infrastructure/backup.py` (the restore) and `application/write/rollback.py`
(the decision to run it and the record afterwards). Neither layer alone can witness it, and the
required mutation (a) lives in the infrastructure half while the criterion is stated of the
application half.

`tests/test_single_writer.py` gains rollback's and uninstall's lock witnesses **in T-17's working
shape** (L50): a second run fired from inside the first's, through a one-shot wrapper, never "hold
the lock by hand and then call the use case". For uninstall the hook is on the first `delete`; for
rollback it is on the entry to `restore`, which is the moment the first run is between taking the
lock and touching a byte — the window an early release opens.

## 6. Mutation checks (L35 — read this if the session was interrupted)

Two, both named in the dispatch and each run alone with `-k` (L42). Each file is backed up to
`…/scratchpad/<name>.t18.orig` before it is mutated and restored from that copy rather than from
memory of the edit.

**(a)** rollback restores only the paths the target currently holds —
`src/harness_library/infrastructure/backup.py`, `restore`, the `elif self._target.exists(path)`
branch removed, so a path the backup holds no bytes for is skipped instead of deleted.
Must fail: `tests/test_rollback.py::test_rolling_back_a_first_install_empties_the_target_again`,
asserted **per path**.
Must stay green: `tests/test_rollback.py::test_rolling_back_an_overwrite_restores_the_previous_bytes`,
which the mutation does not touch — so "restores nothing" and "restores only overwrites" stay
distinguishable.

**(b)** uninstall removes the whole artifact directory —
`src/harness_library/application/write/uninstall.py`, the removal list taken from a target scan
under the artifact's root instead of from the manifest's file list.
Must fail: `tests/application/test_uninstall.py::test_a_foreign_file_under_the_artifacts_root_survives`,
asserted on the foreign file's **bytes**.
Must stay green: `tests/application/test_uninstall.py::test_uninstall_removes_every_file_the_manifest_records`,
so the mutation cannot pass by removing nothing.

**Result — neither is applied; both modules match their backup by md5.**
`infrastructure/backup.py` `598939915739af72a797c433f1dd1322`,
`application/write/uninstall.py` `8827576c2a55e77cbde20e46bf222f9f`.

Under **(a)**, `-k "rolling_back_a_first_install_empties_the_target_again or
rolling_back_an_overwrite_restores_the_previous_bytes"` gave `1 failed, 1 passed`. The first
install's rollback failed on its own message — *"skills/delivery-lead/SKILL.md was created by the
install this rollback undid, so putting the target back means taking it away again (R79)"*,
`assert not True … where True = exists()` — and the overwrite control **stayed green**, which is
the half that matters: every path *its* backup describes is one the target already held, so the
branch the mutation removes is never reached there, and "restores nothing" stays distinguishable
from "restores only overwrites". Restored: `2 passed`.

Three other tests redden under (a) and are kept out of the filter deliberately, the way T-14 kept
its golden path list out of its own: `test_a_foreign_file_is_byte_identical_after_a_rollback` and
`test_the_manifest_records_nothing_after_a_first_install_is_rolled_back` (both first-install
rollbacks, so the same subject), and T-16's own
`tests/infrastructure/test_backup.py::test_restoring_removes_a_path_the_target_did_not_hold`,
which is the store's half of the same rule one layer down.

Under **(b)**, `-k "a_foreign_file_under_the_artifacts_root_survives or
uninstall_removes_every_file_the_manifest_records"` gave `1 failed, 1 passed`:
`test_a_foreign_file_under_the_artifacts_root_survives` failed on the foreign file's **bytes** —
`KeyError: 'skills/delivery-lead/NOTES.md'`, the file simply no longer there — and the removal
test **stayed green**, so the mutation could not pass by removing nothing. Restored: `2 passed`.

**The control had to be weakened to be a control.** It first asserted
`result.removed == (INSTALLED_ENTRY, INSTALLED_REFERENCE)`, which reddens under (b) as well: a
directory-shaped uninstall removes the record's files *and* the foreign one, so a control that
pins the exact list fails for the same reason the subject does, and the pair stops telling
"removes too much" from "removes nothing". It now asserts that the record's files went and not
that only they went; the exact list is asserted in the must-fail next door, where reddening is
the point.

**A third, unrequired check, because DONE WHEN asks for T-17's shape and not L50's.** Both new
lock witnesses were run against an early release — `with lock.hold(): pass` and the body after it,
in `rollback.py` **and** `uninstall.py`. `-k "a_second_uninstall_against_a_held_lock_removes_nothing
or a_second_rollback_against_a_held_lock_restores_nothing or
a_single_apply_writes_every_file_and_leaves_no_sentinel or
rolling_back_an_overwrite_restores_the_previous_bytes"` gave `2 failed, 2 passed`: both second
runs went through unrefused (*"the second rollback was not refused … assert False … isinstance(
None, LockHeldError)"*), and both controls stayed green. That is the whole reason the callback
hangs off the first `delete` and off the entry to `restore` rather than being a lock taken by
hand: the shape L50 warns about passes this mutation. Restored: `4 passed`.

## 7. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time (L2), exit code read without a pipe (L44). Baseline 745 passed.

---

# Backend task plan — T-19, prune and `clean --foreign`

Initiative 02 · phase 1 · base commit `0a322bb` · owner `backend-developer-specialist`.
Realises **F-10**'s second half (`clean --foreign`) and **F-12**'s `--prune`, over contracts
**C-9**, **C-10**, **C-11**, **C-12**, **C-13** (amended here), **C-15** and **C-16**. Rulings
**R44**, **R82**, **R83**, **R86**, **R88**, **R90**, **R91** and **R92** bind.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/application/write/prune.py` | new. `prune_target`, `PruneResult`, `pruned_entries`. §2 argues why it is a use case and not a mode |
| `src/harness_library/application/write/clean.py` | new. `clean_foreign`, `CleanResult`, `foreign_entries` |
| `src/harness_library/application/write/install.py` | **one line.** `apply --prune` selects its entries through `pruned_entries`, so "which entries are pruned" has one spelling and not two. No behaviour change |
| `src/harness_library/application/write/rollback.py` · `uninstall.py` | the manifest write after the work raises `RecordStaleError` instead of a bare `OSError` — R90 is the plan-level decision both modules' docstrings said they were waiting for |
| `src/harness_library/application/write/__init__.py` | re-exports the four new names |
| `src/harness_library/domain/errors.py` | `ErrorCode.RECORD_STALE` and `RecordStaleError` (R90) |
| `src/harness_library/cli/exit_codes.py` | `RECORD_STALE = 13` and its `EXIT_STATUS` row. I-8 makes the table total, so the row lands in the same edit as the code |
| `src/harness_library/domain/backup.py` | **C-13 amended (R92).** `BackupRecord.kept` — the paths the backup holds bytes for |
| `src/harness_library/infrastructure/backup.py` | writes and reads `kept`; `SCHEMA_VERSION` 1 → 2; `restore` pre-flights the kept set |
| `tests/application/test_prune.py` · `tests/application/test_clean.py` | new. Fakes only, zero disk |
| `tests/test_clean.py` | new, cross-layer by necessity — §5 |
| `tests/application/fakes.py` | `FakeBackupStore` records its kept set; nothing else changes |
| `tests/test_single_writer.py` · `tests/test_architecture.py` · `tests/cli/test_exit_codes.py` · `tests/domain/test_backup.py` · `tests/infrastructure/test_backup.py` | added to, never altered |

No new `domain/` module, so `tests/domain/test_purity.py` is untouched (L13, L18). No dependency
change.

## 2. Prune is a use case, not a mode

`apply --prune` and `hl prune` remove the same paths and cannot be the same function, for one
reason that is not a matter of taste: **they record at opposite ends of the run.** Apply makes
files appear and writes its manifest first (R63); prune only makes files disappear and writes its
manifest last (charter §13b, R86). A `prune`-shaped mode of apply would need apply to hold two
orderings and choose between them at runtime, which is the one thing R63's position in the
function exists to make impossible.

It is not a mode of `uninstall_artifact` either: uninstall is given an `artifact_id` and removes
everything recorded for it, while prune is given no id and removes the recorded paths the
*library* no longer holds — which can be some of an artifact's files, or all of them, across every
artifact at once.

**What the two share is the definition of "pruned", and that is now one spelling.**
`pruned_entries(plan)` lives in `prune.py` and `install.py` imports it. The verdict itself is
C-9's and is decided in `domain/install_plan.py`; neither module re-derives it.

## 3. `clean --foreign` — the listing *is* the safety model

```
1  lock        R82: required, keyword-only, wrapping every step below
2  list        the plan's FOREIGN paths the target still holds — `exists` per path, nothing removed
3  (stop)      unless `remove=True`. The default lists and removes nothing
4  back up     every listed path. R88: no backup, no removal
5  remove      in listing order
6  record      last, charter §13b
```

**Two guarantees, not one.** The parameter is the structural half: `remove` defaults to `False`,
so the default call is a listing and T-22's CLI shows it before asking. C-9's `FOREIGN` docstring
already fixes this — *"only `clean --foreign` acts on one, and only when asked"*. The ordering is
the second half: inside a `remove=True` run the listing pass is **complete** before the first
delete, which the interleaving fake in §6(a) is what proves.

**Why the listing pass calls `exists` per path rather than trusting the plan.** Uninstall does the
same and for the same reason: a recorded path the target no longer holds is reported rather than
raised on, because aborting half way through a destructive run over a file somebody already
deleted is worse than finishing. Clean needs it harder — it is about to destroy files this tool
never wrote, and the list it reports has to be a statement about what is *there*, not about what a
scan saw some time ago.

**R44 is honoured by having nothing to honour.** Clean's list is the plan's `FOREIGN` verdicts, and
every path of Claude Code's `synced/` bucket is one. There is no name in this module, no prefix and
no exclusion; the bucket is protected by the listing and the backup, exactly as the dispatch
requires, and by the fact that the default removes nothing.

**A foreign *directory* is never listed and never removed.** C-12's scan reports files and not
directories, so `synced/` is four leaf paths and not one tree, and `delete` refuses a directory
outright. A cleaned `synced/` therefore leaves its empty directories behind — visible, harmless,
removable by hand — which is the same decision uninstall makes about an emptied artifact root, and
for the same reason: removing a directory is deciding that nothing else in it matters.

**`manifest` is required and not optional**, exactly as uninstall's is. A target with no manifest
is not one this tool manages, and `clean --foreign` against it would mean "every path here is
foreign, delete them all" — `rm -rf` reached through a plan. The composition root answers that.

## 4. C-13's amendment (R92) and the pre-amendment backup

`BackupRecord` gains `kept: tuple[str, ...]` — the subset of `paths` the backup holds bytes for —
and `backup.json` records it. `restore` then tells the two states apart before it moves a byte:

* a path in `paths` and not in `kept` was **absent when the backup was taken**, so it is removed —
  R79, unchanged, and what makes a first install undoable;
* a path in `kept` whose `files/<path>` is **gone** is a damaged backup, and the whole restore is
  refused with `KeyError` *before* anything is written.

Today those two are one state by construction, and the second silently **deletes** a live target
path. Narrow trigger, no error, no report, no code.

`KeyError` and no new code: the store already answers "this directory is not a complete backup"
that way, and `rollback_install` already turns it into `BackupNotFoundError` — `BACKUP_FAILED`,
exit 9, whose remedy is *go and look at where backups live*, which is exactly the remedy here. A
code whose remedy already matches takes a class, not a second code.

**A pre-amendment backup is not offered.** `SCHEMA_VERSION` goes 1 → 2, and the reader's existing
rule — a version this build does not read is passed over — does the rest: `list()` skips it and
`restore` refuses it. Reading one and inferring `kept` from the `files/` tree would reproduce the
exact indistinguishability this amendment closes, so the only honest readings are "refuse it" and
"carry the defect forward". A backup is regenerated by the next install; the cost is one rollback
point on a tool that has not shipped.

## 5. Tests, and why one module is cross-layer

`tests/application/test_prune.py` and `tests/application/test_clean.py` are fakes only and zero
disk (charter §10). What they cannot see: that a real `delete` unlinks a foreign symlink as itself
rather than following it, that a real directory survives its emptying, and that a real scan
reports every leaf of the `synced/` tree without filtering.

`tests/test_clean.py` is **cross-layer by necessity**, the third module in this suite that is. The
dispatch's criterion — *every path of the fixture's `synced/` tree is in the listing* — is a claim
about a **real committed tree** and a real scan (`infrastructure/target.py`, where R44's absence of
an exclusion actually lives) joined to a decision in `application/write/clean.py`. Neither layer
alone can witness it: the fake target is given its entries by the test, so a fake agreeing that
`synced/` is foreign proves only that the test author said so.

## 6. Mutation checks (L35 — read this if the session was interrupted)

Three, each run alone with `-k` (L42). Each file is copied to
`…/scratchpad/<name>.t19.orig` before it is mutated and restored from that copy.

**Result — none is applied; both modules match their backup by md5.**
`application/write/clean.py` `20dcc11a640d8ce566d80eb2ed1049b7`,
`application/write/prune.py` `234cd2d7068edab2f2c715016b09d81e`.

Under **(a)**, `-k "every_foreign_path_is_listed_before_any_is_removed or
no_path_the_manifest_records_is_ever_listed"` gave `1 failed, 1 passed`. The interleaving test
failed on the log itself — *"At index 5 diff: 'removed' != 'listed'"*, with the log printed in the
message showing `('listed', …swp), ('removed', …swp), ('listed', …bucket), ('removed', …bucket)`
— and the manifest-known control **stayed green**, which is the half that matters: the mutation
changes *when* a path goes, never *which*, so it cannot reach an assertion about the set. Both
back to `2 passed` on restore.

Worth knowing for the next reader: in the unmutated run the log holds each path **twice** under
`listed`, because `FakeBackupStore.create` calls `exists` per path and the recorder cannot tell
the store's question from the use case's. That does not weaken the assertion — the shape is still
"every listing, then every removal" — and it is why the assertion is written over the *kinds* in
order rather than over an expected list of pairs.

Under **(b)**, `-k "a_still_present_artifacts_files_survive_a_prune or
prune_removes_the_files_of_an_artifact_that_left_the_library"` gave `1 failed, 1 passed`:
`test_a_still_present_artifacts_files_survive_a_prune` failed on the surviving file's **bytes** —
`KeyError: 'skills/delivery-lead/SKILL.md'`, the file simply no longer there — and the removal
test **stayed green**, so the mutation could not pass by pruning nothing. Restored: `2 passed`.
The control asserts `set(result.removed) >= {…}` and not the exact tuple, which is L51 applied
before the run rather than after a wasted cycle.

Under **(c)**, `-k "the_manifest_is_written_only_after_the_pruned_files_are_gone or
the_manifest_drops_only_the_pruned_files"` gave `1 failed, 1 passed`: the ordering witness failed
on `manifests.written == []` — *"Left contains one more item: Manifest(target_path=…)"* — while
the successful run's record test **stayed green**, because a run that does not fail produces the
identical record under both orders (L52, exactly). Restored: `2 passed`.

**(a)** `clean --foreign` acts before listing — `application/write/clean.py`, the listing pass and
the delete loop fused so each path is deleted as it is found.
Must fail: `tests/application/test_clean.py::test_every_foreign_path_is_listed_before_any_is_removed`,
driven by a target that records `exists` and `delete` in one interleaving log.
Must stay green: `tests/application/test_clean.py::test_no_path_the_manifest_records_is_ever_listed`.
Heeding **L51**: that control asserts a membership and a non-membership of `listed`, and says
**nothing** about ordering or about the exact list — the mutation cannot reach it.

**(b)** prune deletes a path the manifest records for an artifact still in the library —
`application/write/prune.py`, the entry filter widened from `Verdict.PRUNE` to every entry the
manifest records.
Must fail: `tests/application/test_prune.py::test_a_still_present_artifacts_files_survive_a_prune`,
on the surviving file's **bytes**, with the exact removal tuple asserted in the same test.
Must stay green: `tests/application/test_prune.py::test_prune_removes_the_files_of_an_artifact_that_left_the_library`,
which asserts `set(result.removed) >= {…}` and not the exact list — **L51**, the lesson T-18 paid
for and addressed to this task by name.

**(c)** my own, for **R86** — prune records first instead of last —
`application/write/prune.py`, `manifests.write(record)` moved above the delete loop.
Must fail: `tests/application/test_prune.py::test_the_manifest_is_written_only_after_the_pruned_files_are_gone`,
which injects an `OSError` into the **second** delete and asserts `manifests.written == []` (L52 —
a run that does not fail cannot tell the two orders apart).
Must stay green: `tests/application/test_prune.py::test_the_manifest_drops_only_the_pruned_files`,
a successful run, whose record is identical under both orders.

## 7. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time (L2), exit code read without a pipe (L44). Baseline 787 passed; **849 passed,
exit 0** after this task, read with `… > gate.log 2>&1; echo $?`.

## 8. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| **Is prune a use case or a mode** | its own use case. The two record at opposite ends of the run (§2), which a mode cannot express without apply holding both orderings |
| **What gates `clean --foreign`'s removal** | a `remove: bool = False` parameter. C-9's `FOREIGN` docstring already says *only when asked*; T-22 owns the flag |
| `clean`'s `manifest` when a target has none | **not expressible.** `manifest: Manifest`, required and non-optional, exactly as uninstall's is. Against a target with no record every path is foreign, and this function must not make "delete everything in a directory this tool has never touched" a thing a caller can ask for |
| Whether `clean` writes a record at all | yes, and only when it removed something. It disowns nothing, so §13b is vacuous for it; the record's `backup_id` is the pointer to the only way back, and a listing-only run leaves no trace |
| `absent` on both | reported, not raised on and not listed. For clean the listing is what a user authorises, and nobody should be asked to authorise destroying a path that is not there |
| **A foreign *symlink* cannot be backed up** | found by the fixture. `BackupStore.create` read through `FilesystemTargetRepository`, which refuses a link (R6), so `clean --foreign` over the committed target raised a bare `ValueError` part-way through a copy. A link is now described in `paths`, left out of `kept` and stored nowhere — so it is removed and **not put back**. No content is lost (the file it names is outside every tree the backup describes) but the removal of a link is that far un-undoable. Asserted in `tests/test_clean.py`; **flagged, it wants a ruling** |
| `RecordStaleError` on rollback and uninstall too | yes. Both already reached that state and both said in their docstrings that a code was a plan-level decision; R90 is that decision, and leaving two spellings of one condition is the drift the taxonomy exists to prevent |

---

# Backend task plan — T-20, V11 and two corrections

Initiative 02 · phase 1 · base commit `ed3888d` · owner `backend-developer-specialist`.
Realises **V11** (F-9's last acceptance row) over contracts **C-3** (amended here) and **C-13**
(amended here), and carries two corrections from T-19's §8: **R93** (`apply --prune` violates
charter §13b) and **R94** (a backup cannot capture a symlink). Rulings **R6**, **R13**, **R22**,
**R46**, **R53**, **R63**, **R64**, **R82**, **R86**, **R90**, **R93**, **R94** bind.

## 1. Where the code goes

| File | Why |
|---|---|
| `src/harness_library/domain/raw.py` | `SymlinkedRoot` and `LibraryScan`. **No new domain module**, so `tests/domain/test_purity.py` is untouched (L13, L18) |
| `src/harness_library/domain/validation.py` | **C-3 amended.** `ValidationCode.V11`, its `SEVERITY_BY_CODE` row (WARNING), and the `path` attribute docstring, which V11 widens |
| `src/harness_library/domain/assembly.py` | `_check_v11`, `assemble_library(..., symlinked_roots=())`, and the `AssembledLibrary.findings` docstring, **which enumerates its members** |
| `src/harness_library/infrastructure/scanner.py` | detection in `_scan_type`; `scan_library` now returns `LibraryScan` |
| `src/harness_library/infrastructure/repository.py` | hands the symlinked roots to the assembler; additive `symlinked_roots()`, **not** a C-4 member |
| `src/harness_library/application/write/install.py` | `plan_install` takes `unscannable`, required and keyword-only; `_skip_unscannable_roots`; **R93's double record write** on the prune path |
| `src/harness_library/application/read/dtos.py` | `FindingPayload`'s docstring enumerates the code range — inside frozen C-7, so the text and nothing else |
| `src/harness_library/domain/backup.py` | **C-13 amended (R94).** `BackupRecord.links` — a described path's symlink destination |
| `src/harness_library/infrastructure/backup.py` | `create` records a link's destination, `restore` recreates it as a link; `SCHEMA_VERSION` 2 → 3 |
| `src/harness_library/infrastructure/target.py` | `read_link` / `write_link` on the **concrete class only**. C-12's protocol keeps its five members |
| `tests/fixtures/library/skills/linked-skill` → `../../outside/linked-skill` | the committed symlinked root. **Points at a real directory** (L21) |
| `tests/fixtures/outside/linked-skill/SKILL.md` | its destination: a skill that would load perfectly, which is what makes the omission a fault |
| `tests/test_symlinked_root.py` | new, cross-layer by necessity — §4 |
| `tests/domain/test_validation.py` · `test_assembly.py` · `test_backup.py` | I-7's register case, the rule, C-13's new invariants |
| `tests/infrastructure/test_scanner.py` · `test_repository.py` · `test_backup.py` · `test_target.py` | real files: the detection, the golden findings, the link round-trip |
| `tests/application/test_install.py` · `test_drift.py` · `tests/test_rollback.py` · `tests/test_clean.py` | `unscannable=()` at every call, plus R93's witness and R94's changed assertion |

No dependency change. No new `ErrorCode` and no `cli/exit_codes.py` edit: `RECORD_STALE = 13`
already exists (R90) and R93's second write raises it.

## 2. Two halves, and why they must not share a mechanism

R46 asks for a warning on scan and a refusal on install. The mutation table asks for something
sharper: dropping the finding must leave the refusal green, and following the link must leave the
warning green. That is only true if **neither reads the other**, so:

* **detection** lives in `scanner._scan_type`, which records a `SymlinkedRoot` for every symlinked
  child of an artifact type directory. `assemble_library` turns it into V11, exactly as a
  `SkippedPath` becomes V6 — the scanner still judges nothing;
* **the refusal** is `_artifact_name`'s existing `is_symlink` guard (R6, the reason the root is
  never scanned) plus `plan_install`'s `SKIPPED` entry, fed from the same `SymlinkedRoot` values
  and never from a finding.

The two `is_symlink()` calls are deliberate and are not a second source of truth: one answers
*should this be reported*, the other answers *may this be walked*. Fusing them would make mutation
(b) redden its own control.

**`plan_install`'s `unscannable` is required and keyword-only**, for the reason C-16's lock is
(R82): a plan that simply does not take the symlinked roots keeps every gate green while silently
omitting an artifact — which is the failure V11 exists to close. `assemble_library`'s equivalent
parameter **does** default to `()`, and the difference is the caller: the assembler has one
production call site, written and tested here, while `plan_install`'s is T-22's composition root.

**`force` does not override V11.** R75's refusal is a judgement about an artifact whose bytes the
library holds, so `--force` can install it anyway; here there are no bytes — the root was never
scanned — and the only way to "force" it would be to follow the link, which R6 forbids. The skip
is applied before the `force` branch and cannot be switched off.

**Where the `SKIPPED` entry lands.** Its path is `TypeSpec.root_path(name)`, which is also the
target-relative path (install mirrors the library's layout), reached through the registry and never
concatenated. If the plan already holds an entry at that exact path — the target holding a file or
the user's own development link at `skills/<name>` — the entry is **replaced**, keeping its
digests, rather than doubled: one path, one entry. That also stops `clean --foreign` offering to
delete the user's development link, which is the second half of R22's justification for V11 being
the one warning that refuses.

## 3. R93 — the union, then the drop

`_apply` writes the record once today, already carrying the pruned paths *dropped*, and then
deletes. A crash between them leaves those files on disk claimed by nobody.

The fix is two records on the prune path and one everywhere else:

```
1 back up
2 record  the union — everything this run will write AND everything it will delete
3 files   writes, then deletes
4 record  again, without the pruned paths      (only when there are pruned paths)
```

Step 2 is `_manifest_after(..., removed=frozenset())`, which already keeps a `PRUNE` path at the
previous manifest's digest, so the union is what it composes with nothing removed. Step 4 is the
same call with the pruned set. When nothing is pruned the two are identical and step 4 is not made,
so **R64's promise is untouched**: `MANIFEST_UNWRITABLE` still means nothing happened, because
step 2 is still the only record a non-pruning run writes. Step 4 raises `RecordStaleError`
(R90, exit 13) — the files are already gone, and 11's guarantee would be exactly false there.

## 4. R94 — a link's content is its destination

`BackupRecord` gains `links: Mapping[str, str]`, the destination of every described path that was
a symlink when the backup was taken. It is disjoint from `kept` (a path is bytes or a link, never
both) and a subset of `paths`, which is the same one-way invariant `kept` already carries.

`create` asks the scan which described paths are links — through `FilesystemTargetRepository`,
never a second `Path.is_symlink` — and records `read_link` for each instead of copying bytes.
`restore` recreates them with `write_link` before it considers removing anything, so a restored
link is a link with the same raw destination and not a copy of what it pointed at.

`read_link` and `write_link` are added to the **concrete** `FilesystemTargetRepository` and not to
C-12's protocol, which is out of this task's contract scope and says "five members, and no sixth".
The backup store already holds the concrete class, and the precedent is `library_findings()`, which
lived on the concrete repository before R23 put it in C-4. **Flagged: C-12 wants these two.**

`SCHEMA_VERSION` 2 → 3, and a version-2 backup is not offered — R92's decision, kept for R92's
reason: the reader has one version and reading an old record would mean guessing at the field it
lacks. The cost is a rollback point on a tool that has not shipped.

## 5. Tests, and why one module is cross-layer

`tests/test_symlinked_root.py` is the fourth cross-layer module in this suite and has to be. The
criterion is *a committed symlinked root produces a warning through the repository and is refused
by a real apply*, and neither layer alone can witness it: the domain suite is handed its findings
by the test, and the application suite is handed its library by a fake. Only a real
`FilesystemArtifactRepository` over the committed tree can show that the scanner really produced
the value the rule fired on — which is the half the mutation table says went unwired last time.

What the fakes still cannot see, stated once: that a real `readlink` survives a round trip through
`backup.json`, and that a restored link is a link. `tests/infrastructure/test_backup.py` and
`tests/infrastructure/test_target.py` prove those against real files.

## 6. Mutation checks (L35 — read this if the session was interrupted)

Three, each run alone with `-k` (L42). Each file is copied to `…/scratchpad/<name>.t20.orig`
before it is mutated and restored from that copy.

**Result — none is applied; all three modules match their backup by md5.**
`domain/assembly.py` `9246dfb1b8e9a8d8c25c051b21e1d091`,
`infrastructure/scanner.py` `5e1a8c809595fa14972bdd55cbfa17d1`,
`application/write/install.py` `ad421396db237ab03c60444e40bfb178`. If this session was
interrupted, those three are the files that were under mutation; compare each against its
`.t20.orig` copy in the scratchpad.

Under **(a)**, `-k "the_committed_symlinked_root_is_a_v11_warning_at_repository_level or
the_symlinked_root_is_skipped_in_the_plan_and_the_run_is_incomplete"` gave `1 failed, 1 passed`.
The warning test failed on the finding simply not being there — `assert 0 == 1, where 0 =
len([])` — and the refusal test **stayed green**, which is the half that matters: it reads
`symlinked_roots()` and never a finding, so the report can vanish without the refusal noticing.
Both back to `2 passed` on restore.

Under **(b)**, `-k "neither_the_symlinked_root_nor_its_destination_is_written or
the_committed_symlinked_root_is_a_v11_warning_at_repository_level"` gave `1 failed, 1 passed`:
the destination test failed on its **first** assertion, the destination's bytes found in the
target — *"assert b'---\nname: linked-skill\n…' not in dict_values([…])"* — and the warning
test **stayed green**, because detection sits in `_scan_type` and the mutation removes a guard
in `_artifact_name`. Restored: `2 passed`.

**Worth knowing for the next reader, and it cost a cycle.** The warning test originally also
asserted that `skill/linked-skill` is in no listing. That assertion is true, load-bearing — it
is the omission V11 exists to report — and it **reddens under (b)**, which makes the artifact
appear, so the control took its own control away. It is now its own test,
`test_the_symlinked_root_is_in_no_listing_the_library_can_produce`. L51's lesson in a second
shape: a control must assert the fact it is a control *for* and nothing else, and "nothing else"
includes true statements the other mutation happens to reach.

Under **(c)**, `-k "a_pruning_apply_claims_the_pruned_path_until_it_is_gone or
pruning_removes_the_path_and_drops_it_from_the_manifest"` gave `1 failed, 1 passed`: the R93
witness failed on the record's content — *"assert set() == {'references/notes.md'}"*, the one
record on disk having already disowned a file the run had not managed to delete — while the
successful pruning run **stayed green**, because a run that does not fail produces the identical
*final* record under both orders (L52, exactly). Restored: `2 passed`. The control asserts the
record's content and says nothing about how many records were written, which is L51 applied
before the run: it is the count that the mutation changes on a successful run.

**(a)** the V11 finding dropped from `AssembledLibrary.findings` — `domain/assembly.py`,
`_check_v11`'s result left out of `assemble_library`.
Must fail: `tests/test_symlinked_root.py::test_the_committed_symlinked_root_is_a_v11_warning_at_repository_level`,
**at repository level**, driven off the committed link.
Must stay green: `tests/test_symlinked_root.py::test_the_symlinked_root_is_skipped_in_the_plan_and_the_run_is_incomplete`,
which reads the scanner's own values and never a finding.

**(b)** the symlinked root followed instead of refused — `infrastructure/scanner.py`,
`_artifact_name`'s `is_symlink` guard removed.
Must fail: `tests/test_symlinked_root.py::test_neither_the_symlinked_root_nor_its_destination_is_written`,
whose **first** assertion is that the destination's bytes reach nowhere in the target.
Must stay green: the warning test above — detection sits in `_scan_type` and does not depend on
the guard, which is the whole reason the two are separate statements.

**(c)** my own, for **R93** — the record written once, already dropping the pruned paths, as it is
today — `application/write/install.py`, step 4 folded back into step 2.
Must fail: `tests/application/test_install.py::test_a_pruning_apply_claims_the_pruned_path_until_it_is_gone`,
which injects an `OSError` into the pruning delete and asserts that the one record already on disk
**still names the pruned path** (L52 — a run that does not fail cannot tell the two orders apart).
Must stay green: `tests/application/test_install.py::test_pruning_removes_the_path_and_drops_it_from_the_manifest`,
a successful pruning run, whose **final** record is identical under both orders. Heeding **L51**,
that control asserts the record's content and says nothing about how many records were written.

## 7. Existing tests changed, and what each asserts now

Nine, and every one of them is a golden that V11 or R94 moved by construction.

| Test | What it asserts now |
|---|---|
| `tests/domain/test_validation.py` — `CHARTER_SECTION_8` | gains `"V11": WARNING`. The closed-set and declaration-order assertions follow from it |
| …`test_v6_is_the_only_warning` → **`test_v6_and_v11_are_the_only_warnings`** | the warning set is `[V6, V11]`. Renamed rather than widened, so the name still says what the list is |
| `tests/domain/test_assembly.py::test_every_finding_takes_its_severity_from_the_register` | takes a `symlinked_roots=` argument, so *"every rule is reachable from this layer"* stays total over `ValidationCode` |
| `tests/infrastructure/test_repository.py::test_v7_fires_…` | the library-level codes are `[V7, V7, V11]`, the first two ERROR and the third WARNING. Still a golden list, so a lost V11 fails here too |
| `tests/cli/test_validate.py::test_the_report_reaches_the_library_level_findings` | `["V7", "V7", "V11"]` through the real CLI — the only place the user is told the linked skill exists at all |
| `tests/infrastructure/test_scanner.py::test_a_symlinked_artifact_root_is_never_followed` → **`…_and_is_reported`** | the artifact set still holds only the real skill **and** the scan reports the root, its id and its destination. The open question its docstring carried is answered and the paragraph is gone |
| …`test_two_scans_of_one_library_produce_the_same_order`, `test_a_library_with_no_type_directories_scans_to_nothing`, and the `scan()` helpers in `test_scanner.py` / `test_timestamps.py` / `test_repository.py` | mechanical: `scan_library` returns a `LibraryScan`, so they read `.artifacts` |
| `tests/test_clean.py::test_a_cleaned_target_is_put_back_by_restoring_the_backup` | **the file set comes back whole**, the symlink included, asserted on `is_symlink` and on `readlink`. It previously asserted `before - {SYMLINK}` and said in its docstring that the gap wanted a ruling; R94 is that ruling |
| every `plan_install(...)` call in `test_install.py`, `test_drift.py`, `test_rollback.py`, `test_clean.py` | mechanical: `unscannable=()` |

**T-16's ordering witness did not move.** `test_the_manifest_is_on_disk_before_the_first_file_is_written`
injects a failure into the first file write on a **non-pruning** plan, and R93 changes nothing
there: the union record is still composed and written before the first file. What changed is the
docstring of `apply_install` and of `ApplyResult.manifest`, which now say that a pruning run's
result carries the *second* record.

## 8. Gate

```
export PATH="$HOME/.local/bin:$PATH"
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run lint-imports && uv run pytest
```

Whole, every time (L2), exit code read without a pipe (L44). Baseline 849 passed; **899 passed,
exit 0** after this task, read with `… > gate.log 2>&1; echo $?`.

## 9. What the contracts left open, and what I decided

| Open point | Decision |
|---|---|
| **How the symlinked roots reach `plan_install`** | an explicit required keyword-only parameter. C-4 is frozen and the natural home — a seventh repository member — would amend it, so `FilesystemArtifactRepository.symlinked_roots()` is additive and not in the protocol, exactly as `library_findings()` was before R23. **Flagged: C-4 wants the member.** |
| **Why not read the finding instead** | because the mutation table forbids it, and rightly: a refusal wired through `library_findings()` would vanish the moment the report did, and the two would be one fact with two names |
| **What `ValidationFinding.path` means for V11** | the path **relative to the library root**, the only spelling that exists for a root that was never scanned. The field's docstring now says so; `None` would hide the one fact the finding delivers |
| **What happens when the plan already holds an entry at the root path** | it is **replaced**, keeping its digests. One path, one entry; and the case is the user's development link mirrored into their target, where keeping `FOREIGN` would have `clean --foreign` offer to delete the very link R22's exception protects |
| **Whether `--force` lifts V11** | **no**, and this is the one place `force` stops. R75 refuses bytes a user may accept; here there are none, and forcing could only mean following the link or destroying it |
| Whether a symlinked child that is not artifact-shaped warns | under a `FILE`-kind type, only a `.md` child does. Under a `DIRECTORY`-kind type **every** link does, because deciding otherwise means `is_dir()`, which follows it |
| **A symlinked root whose destination is another skill in the same library** | both answers stand and neither disturbs the other: the real skill is scanned once under its own name, the alias is reported and skipped. Different target paths, different names, so nothing is written twice and V8 has nothing to say. Pinned in `test_a_skill_symlinked_to_another_skill_in_the_same_library_is_reported_once` |
| **Where `read_link` / `write_link` live** | on the concrete `FilesystemTargetRepository` and **not** in C-12, whose protocol says five members and no sixth. Nothing that plans or applies needs them; the backup store already holds the concrete class. **Flagged: C-12 wants them** |
| A version-2 backup after R94 | not offered, as R92 decided for version 1. Reading one with `links = {}` would be true and would be a second code path through the document whose job is to be trustworthy |
