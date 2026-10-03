"""Signup, login, and /auth/me."""

from __future__ import annotations


def test_signup_creates_user_and_returns_token(client, signup):
    body = signup(email="new@example.com", password="correct-horse-battery")

    assert body["user"]["email"] == "new@example.com"
    assert "id" in body["user"]
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_signup_rejects_duplicate_email(client, signup):
    signup(email="dup@example.com")

    response = client.post(
        "/auth/signup",
        json={"email": "dup@example.com", "password": "another-password"},
    )

    assert response.status_code == 409


def test_signup_email_is_case_insensitive_for_dedup(client, signup):
    signup(email="Case@Example.com")

    response = client.post(
        "/auth/signup",
        json={"email": "case@example.com", "password": "another-password"},
    )

    assert response.status_code == 409


def test_signup_rejects_short_password(client):
    response = client.post(
        "/auth/signup", json={"email": "short@example.com", "password": "short"}
    )

    assert response.status_code == 422


def test_login_with_correct_credentials_succeeds(client, signup):
    signup(email="login@example.com", password="correct-horse-battery")

    response = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_with_wrong_password_rejected(client, signup):
    signup(email="wrongpw@example.com", password="correct-horse-battery")

    response = client.post(
        "/auth/login",
        json={"email": "wrongpw@example.com", "password": "not-the-password"},
    )

    assert response.status_code == 401


def test_login_with_unknown_email_rejected(client):
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "whatever-it-is"},
    )

    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_rejects_garbage_token(client, auth_headers):
    response = client.get("/auth/me", headers=auth_headers("not-a-real-jwt"))

    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client, signup, auth_headers):
    body = signup(email="me@example.com")

    response = client.get("/auth/me", headers=auth_headers(body["access_token"]))

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"
    assert response.json()["id"] == body["user"]["id"]
