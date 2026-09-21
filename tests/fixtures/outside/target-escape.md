# Outside the target

This file sits outside the fixture install target entirely.
`tests/fixtures/target/skills/delivery-lead/references/elsewhere.md` is a symlink pointing here,
four levels up and back down.

It exists so the link is not broken — a broken link makes `ruff`'s file walk fail with `os error 2`
before any rule runs, and tells you nothing about your code (L21) — and because a link that really
does resolve **outside the target root** is the danger ruling R6 names: that is how a copy writes
outside the directory it was told to write into, and this initiative writes into `~/.claude/`.

The target scanner **records** this link — `is_symlink=True`, no content digest — where the library
scanner **skips** it. Recording it is the point: install has to be able to see that the path it was
about to write is a link somewhere else. Nothing may ever hash, read or install this file through
the target repository.
