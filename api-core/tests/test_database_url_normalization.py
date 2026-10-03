"""DATABASE_URL normalization (src/db/session.py:_normalize_database_url).

Managed Postgres providers (Render included) hand out a bare postgres://
or postgresql:// string with no driver specified; we need it pointed at
psycopg (v3), the driver the `postgres` extra actually installs.
"""

from __future__ import annotations

from src.db.session import _normalize_database_url


def test_rewrites_bare_postgres_scheme_to_psycopg3():
    url = "postgres://user:pass@host:5432/dbname"

    assert (
        _normalize_database_url(url)
        == "postgresql+psycopg://user:pass@host:5432/dbname"
    )


def test_rewrites_bare_postgresql_scheme_to_psycopg3():
    url = "postgresql://user:pass@host:5432/dbname"

    assert (
        _normalize_database_url(url)
        == "postgresql+psycopg://user:pass@host:5432/dbname"
    )


def test_leaves_an_already_explicit_driver_untouched():
    url = "postgresql+psycopg://user:pass@host:5432/dbname"

    assert _normalize_database_url(url) == url


def test_leaves_sqlite_untouched():
    url = "sqlite:////tmp/app.db"

    assert _normalize_database_url(url) == url
