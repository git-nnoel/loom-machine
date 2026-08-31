---
name: ruff-format-rewrites-docs-markdown
description: `ruff format .` at repo root silently reformats Python code fences inside docs/*.md — docs/ is excluded in pyproject for this reason
metadata:
  type: project
---

Ruff 0.16's formatter formats embedded Python code fences in **Markdown**. Running `ruff format .`
from the repository root rewrote two delivery-lead documents under `docs/` (aligning inline `#`
comments, splitting `a: int; b: str` dataclass lines) with no mention of `.md` in its "N files
reformatted" output — it just says a count.

**Why it matters:** `docs/` is the delivery lead's territory, not the backend specialist's. A
specialist running the gate would ship an unrequested diff to planning documents and probably not
notice, because `git status` on a documentation-only repo looks noisy anyway.

**How to apply:** `[tool.ruff] extend-exclude = ["docs"]` is already set in `pyproject.toml` — do not
remove it. If you ever see `docs/**` modified after running the gate, that exclusion was lost.
Check `git status --porcelain docs/` is empty before reporting a task done.
