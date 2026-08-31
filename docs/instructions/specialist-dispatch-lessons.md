# Specialist dispatch lessons

Recurring difficulties and their countermeasures, across phases. `PROMPT`-tagged entries are pasted
**verbatim** into every dispatch they bind on — a paraphrased gate command becomes a narrower gate.

Source: backend review of Plan 1, 2026-08-28.

| # | Lesson | Tag | Binding on |
|---|---|---|---|
| L1 | `tests` is not importable under `pythonpath = ["src"]`. Create `tests/__init__.py` and one per subpackage in the scaffold; set `pythonpath = ["src", "."]`. The failure names a module that visibly exists on disk, which sends you looking in the wrong place. | PROMPT | T-1 |
| L2 | **The gate is one command, run whole.** A path-scoped `pytest tests/<dir>` passes where the gate fails. Never report a narrower run as green, and a run that stops at type-check is not green. | PROMPT | every task |
| L3 | `import-linter`'s `layers` order is a trap that reads as correct: listing `infrastructure` above `application` *permits* the inward violation it appears to forbid. Prove the contract by adding a violating import and watching `lint-imports` fail before trusting it. | PROMPT | T-1 |
| L4 | Use the `lint-imports` script, not `python -m importlinter.cli`, and keep the config in `pyproject.toml`, not `setup.cfg`. The module entry point is cwd-dependent and fails differently under pytest's rootdir. | PROMPT | T-1 |
| L5 | The two redirect stubs produce **seven V3 findings that are not bugs** — they cite their successor's reference paths as prose. Spec §4 exempts artifacts with `superseded_by` set. Expect this; do not debug the regex. | PROMPT | T-3, T-9 |
| L6 | `~/.claude/` is a *target* layout, not a library layout — it has no `library.yaml`, so tags, collections and supersession all read empty. A smoke test against it tells you far less than it appears to. Acceptance uses a fixture library committed to the repo. | PROMPT | T-5, T-9 |
| L7 | `hl mcp` dies silently on any stdout write, including Typer's own error output on a bad flag. The failure surfaces as a malformed JSON-RPC stream with no clue why. Write the stdout-purity test before the server. | PROMPT | T-8 |
