"""Pre-deploy hardening: docs gating, no server-path leaks, safe event_type,
and the signup kill-switch."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.api.http import _docs_enabled
from src.learning.schemas_online_learning import IncomingOnlineLearningEvent

# ---------------------------------------------------------------- API docs


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [
        (None, True),  # unset == local development
        ("development", True),
        ("local", True),
        ("production", False),
        ("staging", False),
    ],
)
def test_docs_default_follows_app_env(monkeypatch, app_env, expected):
    monkeypatch.delenv("ENABLE_DOCS", raising=False)
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)

    assert _docs_enabled() is expected


@pytest.mark.parametrize(
    ("enable_docs", "expected"), [("1", True), ("true", True), ("0", False)]
)
def test_enable_docs_overrides_app_env(monkeypatch, enable_docs, expected):
    monkeypatch.setenv("APP_ENV", "production" if expected else "development")
    monkeypatch.setenv("ENABLE_DOCS", enable_docs)

    assert _docs_enabled() is expected


# ------------------------------------------------------------ path leaks


def test_health_does_not_expose_server_paths(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "events_log_dir" not in body
    assert "/" not in json.dumps(body).replace("//", "")


def test_build_dataset_returns_filename_not_server_paths(
    client, signup, auth_headers, tmp_path, monkeypatch
):
    from src.api.routers import online_learning

    monkeypatch.setattr(online_learning, "DATASETS_DIR", tmp_path / "datasets")
    monkeypatch.setattr(online_learning, "EVENTS_LOG_DIR", tmp_path / "events")
    (tmp_path / "datasets").mkdir()
    (tmp_path / "events").mkdir()
    token = signup()["access_token"]

    response = client.post(
        "/online-learning/build-dataset",
        headers=auth_headers(token),
        json={"output_filename": "../../escape.csv"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"success": True, "output_filename": "escape.csv"}
    assert str(tmp_path) not in response.text
    assert (tmp_path / "datasets" / "escape.csv").exists()
    assert not (tmp_path / "escape.csv").exists()


# --------------------------------------------------------- event_type safety


@pytest.mark.parametrize(
    "event_type", ["chat_turn", "openai_style_chat_turn", "pipeline_full_result"]
)
def test_event_type_accepts_names_in_use(event_type):
    evt = IncomingOnlineLearningEvent(ts=1.0, event_type=event_type, payload={})
    assert evt.event_type == event_type


@pytest.mark.parametrize(
    "event_type",
    ["../../etc/passwd", "a/b", "a\\b", "..", "x.jsonl", "", "a" * 65, "evil\x00"],
)
def test_event_type_rejects_path_like_values(event_type):
    with pytest.raises(ValidationError):
        IncomingOnlineLearningEvent(ts=1.0, event_type=event_type, payload={})


def test_collector_cannot_write_outside_events_dir(client, tmp_path, monkeypatch):
    from src.api.routers import online_learning

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(online_learning, "EVENTS_LOG_DIR", events_dir)
    monkeypatch.setenv("ONLINE_LEARNING_API_KEY", "svc-key")
    headers = {"Authorization": "Bearer svc-key"}

    bad = client.post(
        "/events",
        headers=headers,
        json={"ts": 1.0, "event_type": "../escape", "payload": {}},
    )
    good = client.post(
        "/events",
        headers=headers,
        json={"ts": 1.0, "event_type": "chat_turn", "payload": {}},
    )

    assert bad.status_code == 422
    assert not (tmp_path / "escape.jsonl").exists()
    assert good.status_code == 200
    assert (events_dir / "chat_turn.jsonl").exists()


# ------------------------------------------------------------ signup switch


@pytest.mark.parametrize("value", ["0", "false", "off", "no"])
def test_signup_can_be_closed(client, monkeypatch, value):
    monkeypatch.setenv("SIGNUP_ENABLED", value)

    response = client.post(
        "/auth/signup",
        json={"email": "new@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 403
    assert "closed" in response.json()["detail"].lower()


def test_closed_signup_does_not_block_existing_users(client, signup, monkeypatch):
    signup(email="old@example.com", password="correct-horse-battery")
    monkeypatch.setenv("SIGNUP_ENABLED", "0")

    response = client.post(
        "/auth/login",
        json={"email": "old@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 200


def test_signup_is_open_by_default(client, monkeypatch):
    monkeypatch.delenv("SIGNUP_ENABLED", raising=False)

    response = client.post(
        "/auth/signup",
        json={"email": "open@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 201
