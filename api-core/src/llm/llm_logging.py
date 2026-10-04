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
import logging
import os
import threading
from pathlib import Path

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


def setup_daily_llm_logger() -> logging.Logger:
    """Dedicated logger for LLM traces that writes one file per day.

    Location:
      - env LLM_LOG_DIR if set
      - else <BASE_DIR>/logs/llm
    """
    log_dir_env = os.getenv("LLM_LOG_DIR")
    if log_dir_env:
        log_dir = Path(log_dir_env).expanduser()
    else:
        log_dir = BASE_DIR / "logs" / "llm"

    llm_logger = logging.getLogger("mrrobot.llm")
    llm_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on reloads
    if any(isinstance(h, DailyFileHandler) for h in llm_logger.handlers):
        return llm_logger

    h = DailyFileHandler(log_dir=log_dir, prefix="llm")
    h.setFormatter(logging.Formatter("%(message)s"))  # JSONL line per entry
    llm_logger.addHandler(h)
    llm_logger.propagate = False
    return llm_logger
