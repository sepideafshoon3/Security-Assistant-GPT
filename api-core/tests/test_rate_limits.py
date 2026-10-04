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


# ---------------------------------------------------------------------------
# Client-IP key: X-Forwarded-For handling
# ---------------------------------------------------------------------------


def _request(xff: list[str] | None = None, peer: str = "10.0.0.1"):
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", v.encode()) for v in (xff or [])]
    return Request(
        {"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET"}
    )


def test_client_ip_ignores_xff_by_default(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 0)
    assert rate_limit.client_ip(_request(["1.2.3.4"])) == "10.0.0.1"


def test_client_ip_reads_from_the_right(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    req = _request(["6.6.6.6, 203.0.113.9"])  # leftmost is forged by the client
    assert rate_limit.client_ip(req) == "203.0.113.9"
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 2)
    assert rate_limit.client_ip(_request(["6.6.6.6, 203.0.113.9, 172.16.0.5"])) == (
        "203.0.113.9"
    )


def test_client_ip_joins_repeated_headers(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    assert rate_limit.client_ip(_request(["6.6.6.6", "203.0.113.9"])) == "203.0.113.9"


def test_client_ip_falls_back_to_socket_when_chain_too_short(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 2)
    assert rate_limit.client_ip(_request(["203.0.113.9"])) == "10.0.0.1"
    assert rate_limit.client_ip(_request()) == "10.0.0.1"


def test_forged_leftmost_xff_cannot_dodge_login_limit(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    n = _count(rate_limit.LOGIN_RATE_LIMIT)
    codes = [
        client.post(
            "/auth/login",
            json={"email": "a@example.com", "password": "wrong-password-1"},
            headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.9"},
        ).status_code
        for i in range(n + 1)
    ]
    assert codes[n] == 429


def test_different_proxy_seen_clients_get_separate_buckets(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    n = _count(rate_limit.LOGIN_RATE_LIMIT)
    for _ in range(n + 1):
        client.post(
            "/auth/login",
            json={"email": "a@example.com", "password": "wrong-password-1"},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
    other = client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "wrong-password-1"},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert other.status_code != 429
