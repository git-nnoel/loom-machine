---
name: linked-skill
description: a skill kept outside the library and reached through a symlinked root
---

A perfectly ordinary skill. It has a well-formed frontmatter block, a name that matches its
directory, and no broken citation anywhere — nothing in charter §8 has anything to say about it.

That is the point of this fixture. The artifact root that names it,
`tests/fixtures/library/skills/linked-skill`, is a **symlink**, so ruling R6 never follows it and
the scan never reads this file. Before charter §8 gained V11 the result was that this skill was
simply absent from the library, from every listing, from every search and from every install,
with nothing anywhere saying so.

It lives here rather than under `library/` because that is the shape the rule is about: a
developer keeps a skill in a working directory of their own and links it into their library, and
the tool must say so rather than quietly drop it.
