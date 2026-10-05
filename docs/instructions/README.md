# Instructions — phase map

Delivery tree for the harness library. Authored and owned by the delivery lead.
Specialists read only the sections a dispatch names, plus their own charter and task plan.

**Convention:** `docs/specs/` holds the spec suite (what the thing is). This tree holds delivery
(how it gets built, by whom, in what order). Specs are never edited from here; a spec defect is
raised to the user and amended at the source, with a row in the spec's §14 amendment log.

| Phase | Initiative | Status | Independently deployable |
|---|---|---|---|
| 1 | `01-store-and-read-path` | **CLOSED** 2026-09-21 — 11 tasks, 437 tests, two cold reads resolved | Yes — a working read-only CLI and MCP server |
| 1 | `02-install-and-drift` | **CLOSED** 2026-09-21 — 13 tasks, 1090 tests | Yes — `loom install` replaces the manual `cp -a` |
| 2 | `03-http-api` | **Next** — not opened | No — needs 01 and 02 |
| 2 | `04-web-ui` | Not opened | No — needs 03 |

**Gate before any dispatch:** the initiative's `implementation-plan.md` has been reviewed by the user.
A plan is authored in one turn and dispatched in another, never both.
