"""
Structured Logging Setup for the Automated Trading System.

Uses structlog for structured, JSON-formatted logging that integrates
well with the Prometheus/Grafana observability stack.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

import structlog


def setup_logging(
    service_name: str,
    log_level: str = "INFO",
    json_format: bool = False,
) -> structlog.BoundLogger:
    """
    Configure structured logging for a microservice.

    Args:
        service_name: Name of the microservice (e.g., "market-data")
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: If True, output JSON logs (for production).
                     If False, output colored console logs (for development).

    Returns:
        Configured structlog logger instance.
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Shared processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        # Production: JSON output for log aggregation
        renderer = structlog.processors.JSONRenderer()
    else:
        # Development: Colored console output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger(service_name)
    logger = logger.bind(service=service_name)

    return logger


def get_logger(service_name: str) -> structlog.BoundLogger:
    """Get a logger for a specific service or module."""
    return structlog.get_logger(service_name).bind(service=service_name)
