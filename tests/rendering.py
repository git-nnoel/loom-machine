"""Reading text back out of a **rendered** stream. Plumbing only — nothing here asserts (L29).

Ruling R117: a test matches on **text**, never on bytes a renderer is free to decorate. Rich
decorates far more readily than it looks like it will — `Console.is_terminal` answers on
`FORCE_COLOR` *before* it consults `isatty()`, so a `CliRunner` buffer and a subprocess pipe are
both colourised wherever that variable is exported, which is most CI. An assertion that matches a
literal against such a stream is asserting about styling it never meant to pin:

* Typer's option highlighter styles the leading hyphen of `--nope` as a span of its own, so the
  stream holds `ESC[1;36m-ESC[0mESC[1;36m-nopeESC[0m` and the literal `--nope` is simply not in it.
* A help panel's box rule is emitted as `ESC[2m│ESC[0m`, so dropping the `│` alone leaves the two
  escape runs sitting in the middle of any phrase that crossed the panel's edge.

Both are decoration. Strip it, then match.
"""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
"""Every ANSI escape a terminal renderer emits: CSI (colour, cursor), OSC (titles), and the
two-character sequences. Broader than the SGR codes seen today on purpose — a helper that only
knew about colour would hand back text still carrying whatever Rich reaches for next."""

_BOX_RULES = str.maketrans({"│": " ", "┃": " ", "║": " "})
"""The vertical rules Rich draws a panel's sides with, in the weights it chooses between."""


def without_ansi(rendered: str) -> str:
    """`rendered` with every ANSI escape removed and nothing else changed.

    Line structure, spacing and box drawing survive, so a caller that cares about layout still
    has it. Callers that do not want layout want `flattened`.
    """
    return _ANSI.sub("", rendered)


def flattened(rendered: str) -> str:
    """`rendered` as one line of plain text: escapes gone, box rules gone, whitespace collapsed.

    What is left is the wording and nothing else, which is the only part of a help screen or a
    table this project has ever promised. Neither a line break, a box rule nor a colour is a
    contract, and a test that matched one would fail on a cosmetic change while saying nothing
    about behaviour.
    """
    return re.sub(r"\s+", " ", without_ansi(rendered).translate(_BOX_RULES))
