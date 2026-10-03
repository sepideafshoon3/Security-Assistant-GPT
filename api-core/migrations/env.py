"""Alembic environment.

Single source of truth for the database URL and the schema is
``src.db.session`` / ``src.db.models`` -- nothing is duplicated here.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, pool

from src.core.paths import BASE_DIR

# Same .env the API loads, so `alembic ...` from a shell sees DATABASE_URL.
# (Must run before src.db.session is imported: it reads DATABASE_URL at import.)
load_dotenv(BASE_DIR / ".env")

from src.db import models  # noqa: E402, F401  (registers tables on Base.metadata)
from src.db.session import DATABASE_URL, Base  # noqa: E402

config = context.config

# When the app calls us programmatically (src/db/migrate.py) it sets
# `configure_logger=False` so Alembic doesn't reset the app's logging.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# A URL passed in programmatically (tests, tooling) wins over the app default.
url = config.get_main_option("sqlalchemy.url") or DATABASE_URL
is_sqlite = url.startswith("sqlite")


def _context_options() -> dict:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        # SQLite can't ALTER most things in place; batch mode rebuilds the
        # table instead. Harmless (a no-op) on Postgres.
        "render_as_batch": is_sqlite,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (``alembic upgrade --sql``)."""
    context.configure(url=url, literal_binds=True, **_context_options())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Deliberately NOT the app's engine: that one turns SQLite foreign-key
    # enforcement ON for every connection (see db/session.py). Batch
    # migrations rebuild tables via DROP TABLE, and with enforcement on that
    # implicit DELETE would fire ON DELETE CASCADE and wipe child rows
    # (e.g. every message when `conversations` is rebuilt).
    engine = create_engine(url, poolclass=pool.NullPool, future=True)
    if is_sqlite:
        # Set at connect time, not via connection.exec_driver_sql(): the latter
        # would open a transaction that Alembic then never commits.
        @event.listens_for(engine, "connect")
        def _foreign_keys_off(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.close()

    with engine.connect() as connection:
        context.configure(connection=connection, **_context_options())
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
