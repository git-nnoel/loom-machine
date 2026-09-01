"""Ruling R3 and charter §11 — structured logging, to stderr, and to stderr only.

**stdout is a payload channel and nothing else.** For `hl list --json | jq` that is a convenience;
for T-8's `hl mcp` it is survival, because stdout is the JSON-RPC transport and a single stray byte
kills the client connection with no diagnosable cause. T-8 inherits this configuration rather than
writing its own, so the guarantee is made once, here, and `tests/cli/test_logging.py` proves it
instead of asserting it in a comment.

**The stream is resolved at write time, not at configuration time.** `structlog`'s stock
`WriteLoggerFactory` binds whatever `sys.stderr` is when the factory is built. A test — and Click's
own runner — replaces `sys.stderr` after import, so a factory bound at import would write into a
stream nobody is capturing, and a stdout-purity test would pass by writing its log line into the
void. That would be the worst possible outcome: a green test proving nothing. Reading `sys.stderr`
inside the factory, with logger caching off, is what makes the test able to fail.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def _stderr_logger(*args: Any, **kwargs: Any) -> structlog.PrintLogger:
    """A logger writing to whatever `sys.stderr` is *now*. See the module docstring."""
    return structlog.PrintLogger(file=sys.stderr)


def configure_logging(*, verbose: bool = False) -> None:
    """Point every structlog logger at stderr. Idempotent; safe to call per invocation.

    Args:
        verbose: emit DEBUG records as well as INFO and above.

    `cache_logger_on_first_use` is **off** deliberately: with it on, the first logger built in a
    process would pin one `sys.stderr` for the life of that process, and every later test in the
    same session would log into the first test's captured stream.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if verbose else logging.INFO
        ),
        logger_factory=_stderr_logger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A bound logger. Named after the module asking, as every log line should be."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = ["configure_logging", "get_logger"]
