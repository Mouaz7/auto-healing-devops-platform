"""Structured logging with correlation ID support using structlog."""
from __future__ import annotations

import logging
import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output.

    Call once at application startup (e.g. in server.py __main__).

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured structlog BoundLogger.
    """
    logger: structlog.BoundLogger = structlog.get_logger(name)  # type: ignore[assignment]
    return logger
