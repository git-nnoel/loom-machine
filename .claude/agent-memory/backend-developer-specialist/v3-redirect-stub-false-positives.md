---
name: v3-redirect-stub-false-positives
description: Validation rule V3 (cited references must exist) produces 7 false positives on the real ~/.claude library because the two redirect stubs cite their successor's reference paths
metadata:
  type: project
---

Spec §4's V3 rule flags 7 citations as dangling that are not defects. `developers-orchestration/SKILL.md`
cites `references/{collaboration,conflicts,cost-and-time,delegation,plan-formats,review-and-merge}.md` and
`frontend-ctg-system-pattern/SKILL.md` cites `references/brand-ctg.md`. All seven exist — in the successor
skill (`delivery-lead/`, `frontend-system-pattern/`). Both files are redirect stubs whose body is prose
describing *where content moved*, not citations into themselves.

**Why:** verified by direct read of `~/.claude/skills/` on 2026-08-31. V3 cannot distinguish a citation
from a forwarding address.

**How to apply:** V3 must be exempted for any artifact with `superseded_by` set. If you see 7 V3 findings
on the real library, that is this, not a regex bug — do not "fix" the regex. See
[[harness-library-plan1-review]].
