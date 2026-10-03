from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.core.logging_utils import (
    JsonFormatter,
    RequestIdFilter,
    new_request_id,
    set_request_id,
)
from src.core.paths import BASE_DIR

# ============================================================
# Env & paths
# ============================================================

load_dotenv(BASE_DIR / ".env")

# ============================================================
# Logging
# ============================================================
#
# NOTE: this must run *before* we import src.api.state (below) — that
# module builds the executor / chat_memory / online-learning singletons
# at import time and logs during that setup. Importing it earlier would
# make those log lines bypass this configuration (default root logger,
# no handlers, WARNING level) same as it would have in the pre-split
# monolithic http.py, where these singletons were only ever constructed
# after setup_logging() had already run.


def setup_logging() -> None:
    """
    Logging controlled by env:
      LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
      LOG_FORMAT=text|json   (default text; set json once there's an
                              aggregator in front of these logs — Week 6)
      LOG_TO_FILE=1
    Every line — either format — carries the current request's id (see
    RequestIdFilter / the request-context middleware below), '-' outside
    a request.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "text").strip().lower()

    formatter: logging.Formatter = (
        JsonFormatter()
        if log_format == "json"
        else logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(request_id)s): %(message)s"
        )
    )
    request_id_filter = RequestIdFilter()

    handlers: list[logging.Handler] = []

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    console.addFilter(request_id_filter)
    handlers.append(console)

    if os.getenv("LOG_TO_FILE", "").strip() in ("1", "true", "yes", "on"):
        log_file = BASE_DIR / "data" / "logs" / "api.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_id_filter)
        handlers.append(file_handler)

    # force=True: setup_logging() can run more than once per process (e.g.
    # repeated test-suite imports) — without it, the second call is a
    # silent no-op because the root logger already has handlers.
    logging.basicConfig(level=level, handlers=handlers, force=True)


setup_logging()
logger = logging.getLogger(__name__)

# ============================================================
# Remaining imports — deferred until after setup_logging() (see note above)
# ============================================================

import sentry_sdk
from fastapi import Request
from fastapi.responses import JSONResponse

from src.api.auth_routes import router as auth_router
from src.api.routers.chat import router as chat_router
from src.api.routers.conversations import router as conversations_router
from src.api.routers.exploit import router as exploit_router
from src.api.routers.online_learning import router as online_learning_router
from src.api.routers.projects import router as projects_router
from src.api.state import EVENTS_LOG_DIR, online_learning_client
from src.db.migrate import run_migrations
from src.security.auth import ensure_jwt_secret_configured
from src.security.rate_limit import limiter

# ============================================================
# Error monitoring (optional — no-op with no SENTRY_DSN)
# ============================================================

SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.getenv(
            "SENTRY_ENVIRONMENT", os.getenv("APP_ENV", "development")
        ),
        # Fraction of requests to trace for performance monitoring, not just
        # errors. 0 (default) disables tracing entirely — errors still report.
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0")),
    )
    logger.info("Sentry error monitoring enabled")
else:
    logger.info("SENTRY_DSN not set - error monitoring disabled")

# ============================================================
# FastAPI app
# ============================================================

app = FastAPI(title="Security Assistant GPT (Lab)")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Every request gets an id (reused from X-Request-ID if the caller
    already set one, e.g. a frontend/proxy correlating its own logs).
    It's threaded onto every log line emitted while handling the request
    (see RequestIdFilter) and, if Sentry is configured, tagged onto
    whatever event a captured exception produces. On an unhandled
    exception we log it with a traceback, make sure Sentry sees it even
    though we're about to swallow it into a response, and return a
    structured 500 instead of letting FastAPI's bare default through.
    """
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    set_request_id(request_id)
    if SENTRY_DSN:
        sentry_sdk.set_tag("request_id", request_id)

    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - last resort before ServerErrorMiddleware
        logger.exception(
            "Unhandled exception handling %s %s", request.method, request.url.path
        )
        if SENTRY_DSN:
            sentry_sdk.capture_exception(exc)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    finally:
        set_request_id(None)

    response.headers["X-Request-ID"] = request_id
    return response


@app.on_event("startup")
def _startup() -> None:
    # Schema is managed by Alembic (see migrations/). Set DB_AUTO_MIGRATE=0 to
    # skip this and run `alembic upgrade head` as a separate deploy step.
    if os.getenv("DB_AUTO_MIGRATE", "1") != "0":
        run_migrations()
    ensure_jwt_secret_configured()


origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(projects_router)
app.include_router(online_learning_router)
app.include_router(exploit_router)

# ============================================================
# Healthcheck
# ============================================================


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "online_learning_enabled": online_learning_client is not None,
        "events_log_dir": str(EVENTS_LOG_DIR),
    }
