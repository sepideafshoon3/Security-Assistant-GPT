"""Behaviour tests for the daily-file logging extracted from openai_client."""

from __future__ import annotations

import datetime as real_datetime
import json
import logging

import pytest

from src.core.logging_utils import set_request_id
from src.llm import llm_logging
from src.llm.llm_logging import (
    DailyFileHandler,
    JsonlEventFormatter,
    get_daily_logger,
    setup_daily_llm_logger,
)


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def test_handler_creates_dated_file_and_appends(tmp_path):
    h = DailyFileHandler(log_dir=tmp_path / "logs", prefix="llm")
    h.emit(_record("one"))
    h.emit(_record("two"))
    today = real_datetime.date.today().isoformat()
    f = tmp_path / "logs" / f"llm-{today}.log"
    assert f.read_text().splitlines() == ["one", "two"]

    # a second handler (e.g. after a restart) appends instead of truncating
    DailyFileHandler(log_dir=tmp_path / "logs", prefix="llm").emit(_record("three"))
    assert f.read_text().splitlines() == ["one", "two", "three"]


def test_handler_switches_file_when_date_changes(tmp_path, monkeypatch):
    class FakeDate(real_datetime.date):
        current = real_datetime.date(2026, 10, 4)

        @classmethod
        def today(cls):
            return cls.current

    class FakeDatetimeModule:
        date = FakeDate

    monkeypatch.setattr(llm_logging, "datetime", FakeDatetimeModule)
    h = DailyFileHandler(log_dir=tmp_path, prefix="tools")
    h.emit(_record("day1"))
    FakeDate.current = real_datetime.date(2026, 10, 5)
    h.emit(_record("day2"))

    assert (tmp_path / "tools-2026-10-04.log").read_text() == "day1\n"
    assert (tmp_path / "tools-2026-10-05.log").read_text() == "day2\n"


def test_emit_never_raises_on_io_failure(tmp_path):
    h = DailyFileHandler(log_dir=tmp_path, prefix="llm")
    h.emit(_record("ok"))
    h._fp.close()  # simulate a broken file handle
    h.emit(_record("still fine"))  # must be swallowed, not raised


@pytest.fixture()
def clean_llm_logger():
    lg = logging.getLogger("mrrobot.llm")
    saved = (list(lg.handlers), lg.propagate, lg.level)
    lg.handlers.clear()
    yield lg
    for h in lg.handlers:
        h.close()
    lg.handlers[:] = saved[0]
    lg.propagate, lg.level = saved[1], saved[2]


def test_setup_uses_env_dir_and_does_not_duplicate_handlers(
    tmp_path, monkeypatch, clean_llm_logger
):
    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path))
    a = setup_daily_llm_logger()
    b = setup_daily_llm_logger()
    assert a is b is clean_llm_logger
    handlers = [h for h in a.handlers if isinstance(h, DailyFileHandler)]
    assert len(handlers) == 1
    assert a.propagate is False

    a.info('{"event": "x"}')
    today = real_datetime.date.today().isoformat()
    (line,) = (tmp_path / f"llm-{today}.log").read_text().splitlines()
    assert json.loads(line)["event"] == "x"


def test_old_import_sites_still_resolve():
    # The modules that used to import the handler from openai_client.
    import src.agents.dark_recon_agent  # noqa: F401
    import src.llm.xai_client  # noqa: F401
    import src.tools.registry  # noqa: F401
    import src.tools.utils  # noqa: F401


# ---------------------------------------------------------------------------
# One JSON shape for app, LLM and tool logs
# ---------------------------------------------------------------------------


def _daily(log: logging.Logger) -> list[DailyFileHandler]:
    # Only our handlers: pytest and the app's setup_logging() add others.
    return [h for h in log.handlers if isinstance(h, DailyFileHandler)]


def _fmt(msg: str, **extra) -> dict:
    rec = _record(msg)
    rec.request_id = "-"
    for k, v in extra.items():
        setattr(rec, k, v)
    return json.loads(JsonlEventFormatter().format(rec))


def test_event_keys_are_merged_at_top_level_next_to_the_envelope():
    event = {"ts": "2026-10-04T10:00:00", "event": "llm_request", "model": "m", "n": 3}
    out = _fmt(json.dumps(event))
    for key, value in event.items():  # every key call sites wrote survives
        assert out[key] == value
    assert out["level"] == "INFO" and out["logger"] == "t"
    assert out["request_id"] == "-" and out["timestamp"]
    assert "message" not in out  # not buried, escaped, inside "message"
    assert list(out)[:4] == ["timestamp", "level", "logger", "request_id"]


def test_event_keys_win_on_a_clash_with_the_envelope():
    out = _fmt(json.dumps({"level": "custom", "event": "e"}))
    assert out["level"] == "custom" and out["event"] == "e"


@pytest.mark.parametrize("msg", ["plain text", "{not json", "[1, 2]", '"str"', ""])
def test_non_event_messages_fall_back_to_the_app_log_shape(msg):
    out = _fmt(msg)
    assert out["message"] == msg
    assert {"timestamp", "level", "logger", "request_id"} <= set(out)


def test_unicode_stays_readable_in_the_file(tmp_path, monkeypatch, clean_llm_logger):
    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path))
    setup_daily_llm_logger().info(
        json.dumps({"event": "e", "text": "سلام"}, ensure_ascii=False)
    )
    today = real_datetime.date.today().isoformat()
    raw = (tmp_path / f"llm-{today}.log").read_text()
    assert "سلام" in raw and "\\u0633" not in raw


def test_request_id_is_attached_and_defaults_to_dash(
    tmp_path, monkeypatch, clean_llm_logger
):
    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path))
    log = setup_daily_llm_logger()
    set_request_id("abc123")
    try:
        log.info(json.dumps({"event": "inside"}))
    finally:
        set_request_id(None)
    log.info(json.dumps({"event": "outside"}))
    today = real_datetime.date.today().isoformat()
    rows = [
        json.loads(x) for x in (tmp_path / f"llm-{today}.log").read_text().splitlines()
    ]
    assert [(r["event"], r["request_id"]) for r in rows] == [
        ("inside", "abc123"),
        ("outside", "-"),
    ]


@pytest.fixture()
def clean_tools_logger():
    lg = logging.getLogger("mrrobot.tools")
    saved = (list(lg.handlers), lg.propagate, lg.level)
    lg.handlers.clear()
    yield lg
    for h in lg.handlers:
        h.close()
    lg.handlers[:] = saved[0]
    lg.propagate, lg.level = saved[1], saved[2]


def test_factory_is_idempotent_and_keeps_llm_and_tools_files_apart(
    tmp_path, monkeypatch, clean_llm_logger, clean_tools_logger
):
    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path))
    a = get_daily_logger("mrrobot.llm", "llm")
    assert get_daily_logger("mrrobot.llm", "llm") is a
    assert len(_daily(a)) == 1
    t = get_daily_logger("mrrobot.tools", "tools")
    assert len(_daily(t)) == 1 and t is not a

    a.info(json.dumps({"event": "from_llm"}))
    t.info(json.dumps({"event": "from_tools"}))
    today = real_datetime.date.today().isoformat()
    assert "from_llm" in (tmp_path / f"llm-{today}.log").read_text()
    assert "from_tools" in (tmp_path / f"tools-{today}.log").read_text()
    assert "from_tools" not in (tmp_path / f"llm-{today}.log").read_text()


def test_all_call_sites_share_one_logger_and_one_handler(
    tmp_path, monkeypatch, clean_llm_logger, clean_tools_logger
):
    from src.agents import dark_recon_agent
    from src.tools import registry, utils

    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path))
    first = setup_daily_llm_logger()
    assert utils._get_daily_llm_logger() is first
    assert dark_recon_agent._get_daily_llm_logger() is first
    assert len(_daily(first)) == 1  # previously: one handler per call site
    assert registry._get_tool_jsonl_logger().name == "mrrobot.tools"


def test_wrappers_fall_back_instead_of_raising_when_dir_is_unusable(
    tmp_path, monkeypatch, clean_llm_logger
):
    from src.tools import utils

    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("LLM_LOG_DIR", str(blocker / "sub"))  # cannot mkdir
    assert utils._get_daily_llm_logger().name == "mrrobot.llm"


def test_plain_json_formatter_output_is_unchanged_by_the_refactor():
    from src.core.logging_utils import JsonFormatter

    rec = _record("سلام")
    rec.request_id = "r1"
    line = JsonFormatter().format(rec)
    assert "\\u0633" in line  # default still ASCII-escapes, as before
    out = json.loads(line)
    assert out["message"] == "سلام" and out["request_id"] == "r1"
    assert list(out) == ["timestamp", "level", "logger", "message", "request_id"]
