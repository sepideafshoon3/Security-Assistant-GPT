"""CORS_ORIGINS / APP_ENV resolution (src/api/http.py:_resolve_cors_origins).

Imported directly rather than exercised through the app, since the
interesting behavior here is what happens at *startup* under different
env combinations, not anything request-level.
"""

from __future__ import annotations

import pytest

from src.api.http import _resolve_cors_origins


def test_defaults_to_local_dev_origins_when_unset(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    origins = _resolve_cors_origins()

    assert "http://localhost:5173" in origins
    assert "http://localhost:3000" in origins


def test_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://app.example.com, https://admin.example.com"
    )
    monkeypatch.setenv("APP_ENV", "production")

    origins = _resolve_cors_origins()

    assert origins == ["https://app.example.com", "https://admin.example.com"]


def test_raises_if_unset_in_a_non_local_app_env(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        _resolve_cors_origins()


@pytest.mark.parametrize("local_env", ["development", "dev", "local", "DEV"])
def test_treats_all_local_app_env_spellings_as_local(monkeypatch, local_env):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("APP_ENV", local_env)

    # Should not raise.
    origins = _resolve_cors_origins()
    assert origins
