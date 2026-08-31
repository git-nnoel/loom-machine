---
name: pyyaml-carve-out
description: This project uses pyyaml although backend-system-architecture §5 bans it; the ban targets YAML config, library.yaml is user-authored data
metadata:
  type: project
---

`pyyaml` appears on the skill's NOT-allowed list. Harness Library uses it anyway, for `library.yaml`
(spec §3.4). This needs an explicit orchestrator ruling recorded in the charter — as of 2026-08-31 it had
not been made; the plan simply listed pyyaml in its tech stack.

**Why:** the skill's ban is aimed at YAML *configuration* files (R3: env vars only). `library.yaml` is
user-authored *data* mandated by the spec, and `python-frontmatter` vendors PyYAML regardless, so the
dependency is present either way.

**How to apply:** do not treat pyyaml's presence as licence to add YAML config. Config still goes through
a single pydantic-settings reader (R1). If the charter still lacks the ruling, raise it rather than
assuming. See [[harness-library-plan1-review]].
