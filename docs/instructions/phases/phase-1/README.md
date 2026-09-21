# Phase 1 — the library and its install path

The store, its read surface, and the safe install that replaces the manual `cp -a`.

| Initiative | Status | Closes |
|---|---|---|
| `01-store-and-read-path` | **CLOSED** 2026-09-21 — 11 tasks, 437 tests, two cold reads resolved | Reading, validating and serving the library |
| `02-install-and-drift` | **CLOSED** 2026-09-21 — 13 tasks, 1090 tests | Writing it back out, reversibly |

**Ids are project-wide** (R51). Across this phase: T-1…T-23, F-1…F-16, DEC-1…DEC-14, C-1…C-14,
R-1…R-54, V1…V11, L1…L39. Recompute rather than trusting that line —
`for s in R DEC C T F V L; do grep -rhoE "\b${s}-?[0-9]+\b" docs/instructions/ | grep -oE '[0-9]+' | sort -n | tail -1; done`
