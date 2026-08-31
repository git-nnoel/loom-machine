---
name: uv-toolchain-bootstrap
description: uv is not installed in this environment and pip refuses --user (PEP 668); the gate's `uv run` needs a manual bootstrap
metadata:
  type: project
---

The charter §5 gate is expressed as `uv run …`, but `uv` is **not** on PATH in this container, and
`pip install --user uv` is refused by PEP 668 ("externally managed environment"). `~/.local/bin`
exists and is on PATH but is not populated with uv.

**Why:** the image ships a system Python 3.12.3 only. There is no project virtualenv until the first
`uv sync`.

**How to apply:** bootstrap once by downloading the uv wheel (`pip download --no-deps uv`), unzipping
it, and copying `uv-*.data/scripts/uv` into `~/.local/bin/uv`. Network to PyPI works. Then
`export PATH="$HOME/.local/bin:$PATH"` in **every** bash call — the agent shell does not persist env
between calls, and the gate silently becomes "command not found" without it. See [[the-gate-invocation]].
