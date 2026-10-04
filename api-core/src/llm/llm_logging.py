"""Daily-rotating file logging for LLM / tool traces.

Extracted from ``openai_client.py`` so the logging pieces can be imported
without pulling in the OpenAI client (and so ``tools/`` and ``agents/`` no
longer need a function-local import of that 3,700-line module). This module
is a leaf: it must not import from ``src.llm.openai_client`` or ``src.tools``.

Named ``llm_logging`` rather than ``logging`` on purpose: a sibling file
called ``logging.py`` shadows the standard library whenever a script is run
from inside this directory.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from pathlib import Path

from src.core.logging_utils import JsonFormatter, RequestIdFilter
from src.core.paths import BASE_DIR


class DailyFileHandler(logging.Handler):
    """Daily log file handler that writes to:
    <log_dir>/llm-YYYY-MM-DD.log
    - If today's file exists, it appends.
    - If not, it creates it.
    - Switches file automatically when local date changes.
    """

    def __init__(
        self, log_dir: Path, prefix: str = "llm", encoding: str = "utf-8"
    ) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.encoding = encoding
        self._lock = threading.RLock()
        self._current_date: str | None = None
        self._fp = None

        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _today_path(self) -> Path:
        ds = datetime.date.today().isoformat()  # YYYY-MM-DD
        return self.log_dir / f"{self.prefix}-{ds}.log"

    def _ensure_file(self) -> None:
        ds = datetime.date.today().isoformat()
        if self._current_date == ds and self._fp:
            return

        if self._fp:
            try:
                self._fp.flush()
                self._fp.close()
            except Exception:
                pass
            self._fp = None

        path = self._today_path()
        self._fp = path.open("a", encoding=self.encoding)
        self._current_date = ds

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._ensure_file()
                assert self._fp is not None
                self._fp.write(msg + "\n")
                self._fp.flush()
        except Exception:
            # never crash the app because of logging
            pass


class JsonlEventFormatter(JsonFormatter):
    """One JSON object per line, in the same envelope as the app log.

    Call sites log a pre-serialised event (``logger.info(json.dumps({...}))``
    with its own ``ts`` / ``event`` / ``layer`` fields). Wrapping that string
    in ``JsonFormatter`` as-is would bury it, escaped, inside ``"message"``.
    Instead the event's keys are merged at the top level next to the shared
    ``timestamp`` / ``level`` / ``logger`` / ``request_id`` fields, so the
    LLM, tool and app logs can be queried with the same field names while
    every key the call sites already wrote is still there, unchanged (the
    event's own keys win on a clash). Anything that is not a JSON object
    falls back to the ordinary ``JsonFormatter`` shape with ``message``.
    """

    def __init__(self) -> None:
        # Events carry Persian/Unicode text; keep it readable in the files.
        super().__init__(ensure_ascii=False)

    def build_payload(self, record: logging.LogRecord) -> dict:
        payload = super().build_payload(record)
        event = self._as_event(payload["message"])
        if event is None:
            return payload
        del payload["message"]
        payload.update(event)
        return payload

    @staticmethod
    def _as_event(message: str) -> dict | None:
        text = message.lstrip()
        if not text.startswith("{"):
            return None
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None


def resolve_log_dir() -> Path:
    """``LLM_LOG_DIR`` if set, else ``<BASE_DIR>/logs/llm``."""
    log_dir_env = os.getenv("LLM_LOG_DIR")
    if log_dir_env:
        return Path(log_dir_env).expanduser()
    return BASE_DIR / "logs" / "llm"


def get_daily_logger(name: str, prefix: str) -> logging.Logger:
    """Logger *name* writing JSONL to ``<log dir>/<prefix>-YYYY-MM-DD.log``.

    Idempotent: calling it again returns the same logger without adding a
    second handler for the same directory and prefix. Raises ``OSError`` if
    the directory cannot be created; callers that must never fail wrap it.
    """
    log_dir = resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger(name)
    if any(
        isinstance(h, DailyFileHandler) and h.log_dir == log_dir and h.prefix == prefix
        for h in log.handlers
    ):
        return log

    handler = DailyFileHandler(log_dir=log_dir, prefix=prefix)
    handler.setFormatter(JsonlEventFormatter())
    handler.addFilter(RequestIdFilter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def setup_daily_llm_logger() -> logging.Logger:
    """Dedicated logger for LLM traces that writes one file per day.

    Location: see :func:`resolve_log_dir`; file prefix ``llm``.
    """
    return get_daily_logger("mrrobot.llm", "llm")
