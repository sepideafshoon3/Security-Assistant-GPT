"""One request tells the console which conversations are mid-reply.

Before this endpoint the console asked ``generation-status`` for every
conversation in the sidebar on every page load (N requests, N preflights,
N DB lookups).
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from src.api.generation import GenerationManager
from src.db.models import Conversation, User


class _FakeManager:
    def __init__(self, active_ids: list[str]) -> None:
        self._active_ids = active_ids

    def active_ids(self) -> list[str]:
        return list(self._active_ids)


def _conversation(db_session, user_id: str, title: str = "chat") -> str:
    conversation = Conversation(user_id=user_id, title=title)
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    return conversation.id


def test_requires_auth(client):
    assert client.get("/generations/active").status_code == 401


def test_empty_when_nothing_is_generating(client, signup, auth_headers, monkeypatch):
    monkeypatch.setattr("src.api.routers.chat.generation_manager", _FakeManager([]))
    alice = signup(email="alice@example.com")

    response = client.get(
        "/generations/active", headers=auth_headers(alice["access_token"])
    )

    assert response.status_code == 200
    assert response.json() == {"conversation_ids": []}


def test_returns_only_the_callers_active_conversations(
    client, db_session, signup, auth_headers, monkeypatch
):
    alice = signup(email="alice@example.com")
    generating = _conversation(db_session, alice["user"]["id"], "generating")
    _conversation(db_session, alice["user"]["id"], "idle")
    bob = User(email="bob@example.com", password_hash="not-a-real-hash")
    db_session.add(bob)
    db_session.commit()
    db_session.refresh(bob)
    bobs_generating = _conversation(db_session, bob.id, "bob's")
    monkeypatch.setattr(
        "src.api.routers.chat.generation_manager",
        # bob's id and a stale/unknown id are "active" too: neither may leak.
        _FakeManager([generating, bobs_generating, "no-such-conversation"]),
    )

    response = client.get(
        "/generations/active", headers=auth_headers(alice["access_token"])
    )

    assert response.status_code == 200
    assert response.json() == {"conversation_ids": [generating]}


def _slow_stream(n: int = 4, delay: float = 0.03) -> Iterator[str]:
    for i in range(n):
        time.sleep(delay)
        yield f"w{i} "


@pytest.mark.asyncio
async def test_manager_active_ids_tracks_running_generations() -> None:
    mgr = GenerationManager()
    assert mgr.active_ids() == []

    gen = mgr.start("c1", _slow_stream(), persist=lambda _text: None)
    assert mgr.active_ids() == ["c1"]

    async for _ in mgr.subscribe(gen):
        pass
    assert mgr.active_ids() == []
