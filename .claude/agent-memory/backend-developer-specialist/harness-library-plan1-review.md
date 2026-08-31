---
name: harness-library-plan1-review
description: Plan 1 (store/validation/read path/MCP) was reviewed before any code; the 8 frozen contracts and the 9-task recut live in docs/instructions/backend-review-plan1.md
metadata:
  type: reference
---

`docs/instructions/backend-review-plan1.md` holds the pre-code review of
`docs/plans/2026-08-28-store-and-read-path.md`. It carries the eight contracts the orchestrator was asked
to freeze (Artifact, ArtifactFile, ValidationFinding, ArtifactRepository, the read use-case surface, the
error taxonomy, the MCP wire payloads, the composition root) and a 9-task recut of the original 8.

**Why:** the original plan contained ~1400 lines of concrete implementation, which is specialist territory;
it was re-scoped to intent. The review is the agreed technical baseline, not the plan.

**How to apply:** before implementing any Plan 1 task, read §3 (contracts) and §5 (gaps) of that file.
Two decisions there are load-bearing for Plans 2–4: `read_bytes -> bytes` (not `str`) and per-file hashes
on `ArtifactFile` — Plan 2's install verdict table (spec §8.1) is judged per path and cannot be built
without them. Related: [[v3-redirect-stub-false-positives]], [[pyyaml-carve-out]].
