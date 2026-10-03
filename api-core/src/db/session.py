# src/db/session.py
from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.paths import BASE_DIR

# ============================================================
# Connection
# ============================================================
# Default: local SQLite file under data/. Override with DATABASE_URL
# (e.g. postgresql+psycopg://user:pass@host/db) for a real deployment
# without touching any code that imports from this module.

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SQLITE_URL = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)
_is_sqlite = DATABASE_URL.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}

# pool_pre_ping: cheap no-op on SQLite, but required on Postgres so a
# connection that's been idle long enough for the server (or a proxy/LB
# in front of it) to drop isn't handed back out and blow up mid-request.
# Pool sizing only makes sense for a real server-based DB; SQLite ignores
# these kwargs via its own default pool class.
_engine_kwargs: dict = {
    "connect_args": _connect_args,
    "future": True,
    "pool_pre_ping": True,
}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
    _engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_engine(DATABASE_URL, **_engine_kwargs)

if _is_sqlite:
    # SQLite ignores ON DELETE CASCADE (and every other FK constraint)
    # unless foreign key enforcement is turned on per-connection — it's
    # off by default. Without this, deleting a Conversation would leave
    # its Message rows behind as permanent orphans instead of the
    # cascade the models declare.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped session, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
