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
| `library.yaml` | tags, collections, supersession, and two ids that resolve to nothing (V7) |

**Not here, on purpose.** V8 needs two directories differing only by case, which cannot be checked
out on a case-insensitive filesystem at all; V9 needs a duplicated key in the one `library.yaml`
whose tags and collections the rest of the suite reads as a golden literal; V10 needs a `SKILL.md`
whose frontmatter does not parse, which every other tool reading this repository — editors, linters,
GitHub's own preview — would report as broken, burying a deliberate fixture under noise. All three
are proven against real files built under `tmp_path` instead — same guarantee, and the repository
stays cloneable on macOS.

**Timestamps are never asserted against this tree.** It lives inside this repository, so it is dirty
while uncommitted and clean once committed; ruling R5 is proven in a purpose-built repository under
`tmp_path` where the test owns the commit dates.
