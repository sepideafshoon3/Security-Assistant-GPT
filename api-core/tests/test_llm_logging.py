"""Behaviour tests for the daily-file logging extracted from openai_client."""

from __future__ import annotations

import datetime as real_datetime
import logging

import pytest

from src.llm import llm_logging
from src.llm.llm_logging import DailyFileHandler, setup_daily_llm_logger


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
    assert (tmp_path / f"llm-{today}.log").read_text() == '{"event": "x"}\n'


def test_old_import_sites_still_resolve():
    # The modules that used to import the handler from openai_client.
    import src.agents.dark_recon_agent  # noqa: F401
    import src.llm.xai_client  # noqa: F401
    import src.tools.registry  # noqa: F401
    import src.tools.utils  # noqa: F401
