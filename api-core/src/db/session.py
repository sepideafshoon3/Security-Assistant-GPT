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

_connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

if DATABASE_URL.startswith("sqlite"):
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


def init_db() -> None:
    """
    Create all tables that don't exist yet.

    Safe to call on every app startup: existing tables are left untouched.
    For real schema changes later, switch to Alembic migrations instead of
    relying on create_all.
    """
    # Import models so they register on Base.metadata before create_all.
    from src.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _patch_conversations_project_id()


def _patch_conversations_project_id() -> None:
    """One-off stopgap for the Week 4 Project/Folder model: create_all()
    only creates missing tables, it doesn't ALTER existing ones, so a dev
    DB created before ``Conversation.project_id`` existed needs the column
    added by hand. Safe to call on every startup — it's a no-op once the
    column is there. Remove this once Alembic migrations (Week 5) land.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return
    existing_columns = {col["name"] for col in inspector.get_columns("conversations")}
    if "project_id" in existing_columns:
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE conversations ADD COLUMN project_id VARCHAR(36)")
        )
        if DATABASE_URL.startswith("sqlite"):
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_conversations_project_id "
                    "ON conversations (project_id)"
                )
            )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped session, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
