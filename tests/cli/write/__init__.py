"""The CLI's write suite. A package of its own so its `conftest.py` is its own.

`sandbox_home` is autouse and points `$HOME` at `tmp_path`; every test that can reach a real
`~/.claude` or a real state root lives here and nowhere else. Defining it in `tests/cli/`'s
conftest would have applied it to initiative 01's read-path tests too, which is a change to
tests that are a contract — and importing it into each module instead makes every fixture
parameter an F811 redefinition. A package is the one shape that scopes it exactly.
"""
