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
