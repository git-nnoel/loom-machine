# Fixture library

`library/` is a real harness library, committed as real files. It is prerequisite P-4 of the
`01-store-and-read-path` implementation plan and it is the regression suite for the reason this
product exists, so **charter §10 says it is never deleted**.

Every failure charter §8 names is reproduced here against real bytes rather than a literal:

| Path | Reproduces |
|---|---|
| `skills/delivery-lead/` | the clean control — every "this rule does not fire" assertion leans on it |
| `skills/no-entry/` | V1 — a skill directory with no `SKILL.md` |
| `skills/misnamed/` | V2 — frontmatter `name` disagreeing with the directory |
| `skills/broken-links/` | V3 — two missing citations, one of them written twice |
| `skills/legacy-orchestration/`, `skills/legacy-ctg-pattern/` | V3's exemption — two redirect stubs citing **seven** of their successor's paths as prose |
| `skills/incomplete/`, `agents/nameless.md` | V5 — a required key present-but-empty, and one absent |
| `skills/messy/` | V6 — an editor swap file, a `node_modules` tree, and a symlink escaping the artifact root; plus a binary PNG that is stored and hashed but never text |
| `skills/dangling-successor/` | V4 — `superseded_by` naming an artifact that is not here |
| `skills/linked-skill` → `../../outside/linked-skill` | V11 — an **artifact root that is a symlink**. Never followed, never scanned, and so absent from the library entirely: no `skill/linked-skill` appears in any listing, and before V11 nothing said so. The destination is a skill with no fault of any kind, which is what makes the omission the whole fault |
| `library.yaml` | tags, collections, supersession, and two ids that resolve to nothing (V7) |

**Not here, on purpose.** V8 needs two directories differing only by case, which cannot be checked
out on a case-insensitive filesystem at all; V9 needs a duplicated key in the one `library.yaml`
whose tags and collections the rest of the suite reads as a golden literal; V10 needs a `SKILL.md`
whose frontmatter does not parse, which every other tool reading this repository — editors, linters,
GitHub's own preview — would report as broken, burying a deliberate fixture under noise. All three
are proven against real files built under `tmp_path` instead — same guarantee, and the repository
stays cloneable on macOS.

**The symlinked root points at a real directory**, `outside/linked-skill/`, and must keep doing
so: `ruff` exits 2 on a broken symlink anywhere in the tree, before any rule runs and with no rule
code (L21). `outside/linked-skill/` belongs to the library fixture the way `outside/secret.md`
does.

**Timestamps are never asserted against this tree.** It lives inside this repository, so it is dirty
while uncommitted and clean once committed; ruling R5 is proven in a purpose-built repository under
`tmp_path` where the test owns the commit dates.

---

# Fixture install target

`target/` is a real install target, committed as real files. It is prerequisite **P-3** of the
`02-install-and-drift` implementation plan. It is **not** a library and must not be read as one: it
has no `library.yaml`, nothing here is validated, and nothing here is an artifact. It is a
directory of paths shaped like a user's `~/.claude/`, most of which this tool did not put there.

`outside/target-escape.md` belongs to it, the way `outside/secret.md` belongs to the library.

| Path | Stands for |
|---|---|
| `skills/delivery-lead/SKILL.md`, `.../references/cost-and-time.md`, `agents/scribe.md` | files this tool would have installed — the `UNCHANGED` / `UPDATE` / `LOCAL_EDIT` control |
| `skills/delivery-lead/references/diagram.png` | a binary that must round-trip through `read_bytes` byte-identically and is never decoded (charter §7) |
| `skills/delivery-lead/SKILL.md.swp` | an editor swap file. The **library** scanner skips this name and reports V6; the **target** scanner records it, because install has to see it to leave it alone. The sharpest single difference between the two |
| `skills/synced/` | Claude Code's own skill-sync bucket: a `.bucket-<id>` marker beside a `<id>_<id>/` directory holding a skill two levels down. No entry document at its root and no library artifact claims it. **Ruling R44 gives it no named exclusion** — it is `FOREIGN` like anything else, and an exclusion keyed on the name would hide whatever else lands there |
| `settings.json` | a foreign loose file at the target root, under no artifact root at all. The path ruling **R60** exists for: its plan entry carries `artifact_id=None`, because there is no `<type>/<name>` to give it |
| `skills/delivery-lead/references/elsewhere.md` | a symlink resolving **outside the target root**, which is how a copy writes where it should not (R6). Recorded with `is_symlink=True` and no content digest; never followed, never hashed, never written through |

**The link points at a real file**, `outside/target-escape.md`, and must keep doing so: `ruff` exits
2 on a broken symlink anywhere in the tree, before any rule runs and with no rule code (L21).

**Nothing writes into this tree.** Every test that writes copies it to `tmp_path` first
(`symlinks=True`, with `outside/` recreated alongside so the copy's link resolves as this one
does), and one test hashes this tree before and after to prove it.

**Timestamps are never asserted against it**, for the reason the library fixture gives: it is dirty
while uncommitted and clean once committed (L22).
