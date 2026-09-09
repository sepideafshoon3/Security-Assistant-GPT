from __future__ import annotations

import os
import logging
from typing import List, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
      LOG_TO_FILE=1
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: List[logging.Handler] = []

    console = logging.StreamHandler()
    console.setLevel(level)
    handlers.append(console)

    if os.getenv("LOG_TO_FILE", "").strip() in ("1", "true", "yes", "on"):
        log_file = BASE_DIR / "data" / "logs" / "api.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


setup_logging()
logger = logging.getLogger(__name__)

# ============================================================
# Remaining imports — deferred until after setup_logging() (see note above)
# ============================================================

from src.db.session import init_db
from src.api.auth_routes import router as auth_router
from src.api.routers.chat import router as chat_router
from src.api.routers.conversations import router as conversations_router
from src.api.routers.online_learning import router as online_learning_router
from src.api.routers.exploit import router as exploit_router
from src.api.state import online_learning_client, EVENTS_LOG_DIR
from src.security.auth import ensure_jwt_secret_configured

# ============================================================
# FastAPI app
# ============================================================

app = FastAPI(title="Security Assistant GPT (Lab)")

@app.on_event("startup")
def _create_tables_if_missing() -> None:
    init_db()
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
app.include_router(online_learning_router)
app.include_router(exploit_router)

# ============================================================
# Healthcheck
# ============================================================

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "online_learning_enabled": online_learning_client is not None,
        "events_log_dir": str(EVENTS_LOG_DIR),
    }