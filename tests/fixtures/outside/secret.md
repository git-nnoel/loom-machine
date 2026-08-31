# Outside the library

This file sits outside the fixture library entirely. `skills/messy/references/elsewhere.md` is a
symlink pointing here, four levels up and back down.

It exists so the link is not broken — a broken link makes `ruff`'s file walk fail with `os error 2`
and tells you nothing about your code — and because a link that really does resolve **outside the
artifact root** is the danger ruling R6 names: that is how a copy writes outside its target, and
initiative 02 writes into `~/.claude/`.

Nothing may ever hash, read or install this file through an artifact. That is what the scanner's
`SYMLINK` skip and the repository's symlink refusal are for.
