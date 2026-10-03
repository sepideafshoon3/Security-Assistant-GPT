"""Shared fixtures for API tests.

Each test gets its own throwaway SQLite file, migrated with the real
Alembic chain (not Base.metadata.create_all — we want to test the schema
we'll actually run in production), wired into the real FastAPI app via a
``get_db`` override. Nothing here touches data/app.db.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.migrate import run_migrations
from src.db.session import get_db
from src.security.rate_limit import limiter


@pytest.fixture()
def db_session_factory(tmp_path) -> Generator[sessionmaker, None, None]:
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    run_migrations(db_url)

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    try:
        yield TestingSessionLocal
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_session_factory) -> Generator[TestClient, None, None]:
    # Imported here, not at module scope: importing src.api.http is what
    # triggers route/middleware registration, and we want that to happen
    # after conftest has had a chance to run (keeps import order obvious).
    from src.api.http import app

    def _override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # Rate limits are shared, in-memory, and keyed by client IP — without
    # a reset, a login/signup test later in the suite can get 429'd by
    # quota an earlier test already spent against the same TestClient IP.
    try:
        limiter.reset()
    except AttributeError:  # pragma: no cover - depends on slowapi version
        pass
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def db_session(db_session_factory):
    """A session for arranging data directly, bypassing the API — e.g.
    seeding a conversation to test ownership checks against."""
    db = db_session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def signup(client: TestClient):
    """Factory fixture: signup(email=..., password=...) -> parsed AuthResponse
    body (includes access_token), with a 201 assertion baked in so a broken
    signup fails at the call site instead of surfacing as a confusing 401
    somewhere later in the test."""

    def _signup(
        email: str = "alice@example.com", password: str = "correct-horse-battery"
    ) -> dict:
        response = client.post(
            "/auth/signup", json={"email": email, "password": password}
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _signup


@pytest.fixture()
def auth_headers():
    def _auth_headers(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers
