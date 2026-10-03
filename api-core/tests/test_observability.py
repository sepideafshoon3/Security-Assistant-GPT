"""Structured logging (JsonFormatter) and the request-id middleware."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from src.api.http import app
from src.core.logging_utils import JsonFormatter, RequestIdFilter, set_request_id

# Same pattern as test_api.py: no DB override needed here since every
# endpoint we hit either doesn't touch the DB (/auth/me with no/garbage
# token short-circuits in get_current_user before any query) or we don't
# care about its body, only the middleware-added header.
client = TestClient(app)


def _make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_produces_valid_json_with_expected_fields():
    formatter = JsonFormatter()
    record = _make_record(request_id="abc123")

    parsed = json.loads(formatter.format(record))

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert parsed["message"] == "hello world"
    assert parsed["request_id"] == "abc123"
    assert "timestamp" in parsed


def test_json_formatter_includes_exception_info():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(request_id="-")
        record.exc_info = sys.exc_info()

    parsed = json.loads(formatter.format(record))

    assert "ValueError: boom" in parsed["exception"]


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter()
    record = _make_record(request_id="-", path="/auth/login", status_code=401)

    parsed = json.loads(formatter.format(record))

    assert parsed["path"] == "/auth/login"
    assert parsed["status_code"] == 401


def test_request_id_filter_defaults_to_dash_outside_a_request():
    set_request_id(None)
    record = _make_record()

    RequestIdFilter().filter(record)

    assert record.request_id == "-"


def test_response_carries_an_x_request_id_header():
    response = client.get("/auth/me")  # 401, but middleware still runs

    assert "X-Request-ID" in response.headers


def test_caller_supplied_request_id_is_echoed_back():
    response = client.get("/auth/me", headers={"X-Request-ID": "my-trace-id"})

    assert response.headers["X-Request-ID"] == "my-trace-id"
