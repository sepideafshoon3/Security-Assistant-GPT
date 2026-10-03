"""Run Alembic migrations from application code.

``run_migrations()`` is what the API calls on startup (see api/http.py); it is
the programmatic equivalent of ``alembic upgrade head``.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from src.core.paths import BASE_DIR


def _alembic_config(database_url: str | None) -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    if database_url:
        # env.py falls back to src.db.session.DATABASE_URL when this is unset.
        cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    # Don't let Alembic reconfigure the app's logging (see migrations/env.py).
    cfg.attributes["configure_logger"] = False
    return cfg


def run_migrations(database_url: str | None = None, revision: str = "head") -> None:
    """Upgrade the database to ``revision`` (default: latest)."""
    command.upgrade(_alembic_config(database_url), revision)
