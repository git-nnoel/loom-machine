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
