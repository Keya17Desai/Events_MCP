"""Structured logging configuration for the Events MCP server.

structlog writes key-value events instead of opaque strings. Every log call
emits a JSON object (or a colored line in a TTY) with a timestamp, level,
logger name, and whatever context was bound to the call.

Critical for stdio MCP servers: all output goes to stderr. stdout is
reserved for the JSON-RPC protocol; writing logs there would corrupt the
stream and silently break the connection to the client.

Usage:

    from events_mcp.logging import configure_logging, get_logger

    configure_logging()  # call once at server startup
    log = get_logger(__name__)
    log.info("search_completed", city="Mumbai", count=5, cache_hit=False)
"""
from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog. Idempotent — safe to call multiple times.

    Output goes to stderr. Format depends on whether stderr is a terminal:
    - TTY (running locally) → human-readable colored output
    - Non-TTY (Claude Desktop, file redirect) → one JSON object per line
    """
    global _configured
    if _configured:
        return

    is_tty = sys.stderr.isatty()

    renderer: structlog.types.Processor
    if is_tty:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. Pass `__name__` from the calling module."""
    return structlog.get_logger(name)
