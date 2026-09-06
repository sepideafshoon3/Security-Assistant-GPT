# src/db/session.py
from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
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

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

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


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped session, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
