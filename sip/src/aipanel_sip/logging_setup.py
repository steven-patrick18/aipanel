"""Structured JSON logging for the SIP service.

systemd's ``StandardOutput=append:/var/log/aipanel/sip.log`` captures stdout
verbatim, so we just emit one JSON object per line to stdout. structlog
handles serialization; ``contextvars.merge_contextvars`` lets call handlers
bind ``call_id`` once and have it land on every subsequent log line for
that call.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "INFO") -> structlog.stdlib.BoundLogger:
    """Configure stdlib logging + structlog. Returns a logger bound to service=sip."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Bare stdlib config — single line-buffered stdout handler.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    # Replace any pre-existing handlers (pytest, etc).
    root.handlers = [handler]
    root.setLevel(log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger().bind(service="sip")
