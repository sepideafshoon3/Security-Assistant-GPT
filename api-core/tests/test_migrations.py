"""Alembic migrations: fresh DBs, pre-Alembic dev DBs, and data safety."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from src.db import models  # noqa: F401  (registers tables on Base.metadata)
from src.db.migrate import run_migrations
from src.db.session import Base


@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


def _schema_diff(url: str) -> list:
    """Differences between the migrated DB and the ORM models (want: none)."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            return compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()


def _version(url: str) -> str:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()


def test_fresh_database_matches_models(db_url):
    run_migrations(db_url)

    assert _version(db_url) == "0002"
    assert _schema_diff(db_url) == []


def test_upgrade_is_idempotent(db_url):
    run_migrations(db_url)
    run_migrations(db_url)

    assert _version(db_url) == "0002"


def test_downgrade_to_base_removes_everything(db_url):
    from alembic import command

    from src.db.migrate import _alembic_config

    run_migrations(db_url)
    command.downgrade(_alembic_config(db_url), "base")

    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_pre_alembic_database_is_adopted_without_data_loss(db_url):
    """A dev DB built by the old create_all() has no alembic_version table."""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, created_at) "
                "VALUES ('u1', 'a@b.c', 'x', '2026-01-01')"
            )
        )
    engine.dispose()

    run_migrations(db_url)

    assert _version(db_url) == "0002"
    assert _schema_diff(db_url) == []
    engine = create_engine(db_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1
    engine.dispose()


# The schema as it was before Projects (and before generation_jobs /
# email_verifications existed), to prove 0001+0002 upgrade an old DB in place.
_OLD_SCHEMA = [
    """CREATE TABLE users (
        id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) NOT NULL,
        password_hash VARCHAR(255) NOT NULL, created_at DATETIME)""",
    """CREATE TABLE conversations (
        id VARCHAR(36) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(255), title_is_generated BOOLEAN, created_at DATETIME,
        updated_at DATETIME, pinned BOOLEAN)""",
    """CREATE TABLE messages (
        id VARCHAR(36) PRIMARY KEY,
        conversation_id VARCHAR(36) NOT NULL
            REFERENCES conversations(id) ON DELETE CASCADE,
        role VARCHAR(32) NOT NULL, content TEXT NOT NULL, created_at DATETIME)""",
    "INSERT INTO users VALUES ('u1', 'a@b.c', 'x', '2026-01-01')",
    "INSERT INTO conversations VALUES ('c1', 'u1', 'Hi', 1, '2026-01-01', "
    "'2026-01-01', 0)",
    "INSERT INTO messages VALUES ('m1', 'c1', 'user', 'hello', '2026-01-01')",
    "INSERT INTO messages VALUES ('m2', 'c1', 'assistant', 'hi', '2026-01-01')",
]


def test_old_database_is_upgraded_and_messages_survive(db_url):
    engine = create_engine(db_url)
    with engine.begin() as conn:
        for stmt in _OLD_SCHEMA:
            conn.execute(text(stmt))
    engine.dispose()

    run_migrations(db_url)

    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert {"projects", "generation_jobs", "email_verifications"} <= set(
        inspector.get_table_names()
    )
    assert "project_id" in {c["name"] for c in inspector.get_columns("conversations")}
    with engine.connect() as conn:
        # Rebuilding `conversations` must not cascade-delete its messages.
        assert conn.execute(text("SELECT COUNT(*) FROM messages")).scalar() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM conversations")).scalar() == 1
    engine.dispose()
