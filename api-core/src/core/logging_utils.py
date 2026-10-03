# src/core/logging_utils.py
"""Structured (JSON) logging and request correlation.

Plain-text logs are fine to tail in a terminal but can't be queried once
they're sitting in whatever log aggregator Week 6 ends up shipping to.
JsonFormatter gives every line a stable shape; the request-id machinery
ties every log line from one HTTP request — and its matching Sentry
event, if one fires — together.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every stdlib LogRecord already carries, plus the ones we add
# ourselves — used to find the extra={...} kwargs a caller passed in.
_RESERVED_RECORD_KEYS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "request_id"}


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(request_id: str | None) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Attaches the current request's id to every log record that passes
    through a handler with this filter installed, '-' outside a request
    (startup, background jobs, CLI usage)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message,
    request_id, exception info when present, plus whatever extra fields
    the call site passed via ``logger.info(..., extra={...})`` — callers
    don't need to know this formatter exists."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS:
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = repr(value)
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)
