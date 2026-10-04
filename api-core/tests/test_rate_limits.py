"""Write endpoints must return 429 once the per-client quota is spent.

Limits are read from env at import time, so rather than reload modules we
assert against the configured default: send (limit + 1) requests and
expect the last one to be rejected. Defaults are parsed from the same
constants the routers use, so the test follows any change to them.
"""

from __future__ import annotations

import pytest

from src.security import rate_limit


def _count(limit: str) -> int:
    return int(limit.split("/")[0])


@pytest.fixture()
def token(signup):
    return signup()["access_token"]


def test_project_create_is_rate_limited(client, token, auth_headers):
    n = _count(rate_limit.WRITE_RATE_LIMIT)
    codes = [
        client.post(
            "/projects", json={"name": f"p{i}"}, headers=auth_headers(token)
        ).status_code
        for i in range(n + 1)
    ]
    assert codes[:n] == [201] * n
    assert codes[n] == 429


def test_project_rename_and_delete_are_rate_limited(client, token, auth_headers):
    pid = client.post(
        "/projects", json={"name": "x"}, headers=auth_headers(token)
    ).json()["id"]
    n = _count(rate_limit.WRITE_RATE_LIMIT)
    codes = [
        client.patch(
            f"/projects/{pid}", json={"name": f"n{i}"}, headers=auth_headers(token)
        ).status_code
        for i in range(n + 1)
    ]
    assert codes[-1] == 429
    codes = [
        client.delete(f"/projects/{pid}", headers=auth_headers(token)).status_code
        for _ in range(n + 1)
    ]
    assert codes[-1] == 429


def test_conversation_write_endpoints_are_rate_limited(client, token, auth_headers):
    n = _count(rate_limit.WRITE_RATE_LIMIT)
    patch = [
        client.patch(
            "/conversations/nope", json={"title": "t"}, headers=auth_headers(token)
        ).status_code
        for _ in range(n + 1)
    ]
    assert patch[:n] == [404] * n  # not found, but counted against the quota
    assert patch[n] == 429
    delete = [
        client.delete("/conversations/nope", headers=auth_headers(token)).status_code
        for _ in range(n + 1)
    ]
    assert delete[-1] == 429


def test_signup_is_rate_limited(client):
    n = _count(rate_limit.SIGNUP_RATE_LIMIT)
    codes = [
        client.post(
            "/auth/signup",
            json={"email": f"u{i}@example.com", "password": "correct-horse-battery"},
        ).status_code
        for i in range(n + 1)
    ]
    assert codes[:n] == [201] * n
    assert codes[n] == 429


def test_online_learning_build_dataset_is_rate_limited(client, token, auth_headers):
    n = _count(rate_limit.DATASET_BUILD_RATE_LIMIT)
    codes = [
        client.post(
            "/online-learning/build-dataset", json={}, headers=auth_headers(token)
        ).status_code
        for _ in range(n + 1)
    ]
    assert 429 not in codes[:n]
    assert codes[n] == 429
