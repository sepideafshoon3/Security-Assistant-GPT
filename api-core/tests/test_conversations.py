"""Conversation listing, rename, delete, and ownership enforcement.

Conversations are only ever created inside the chat flow (there's no
POST /conversations endpoint), so these tests seed a Conversation
directly via the DB session and exercise the API against it — the same
split as test_migrations.py uses between "arrange via ORM" and "act via
the thing under test".
"""

from __future__ import annotations

from src.db.models import Conversation, User


def _make_user_and_conversation(db_session, email: str, title: str = "New chat"):
    user = User(email=email, password_hash="not-a-real-hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    conversation = Conversation(user_id=user.id, title=title)
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)

    return user.id, conversation


def test_list_conversations_only_returns_the_caller_s_own(
    client, db_session, signup, auth_headers
):
    alice = signup(email="alice@example.com")
    _bob_id, bob_conv = _make_user_and_conversation(db_session, "bob@example.com")
    db_session.add(Conversation(user_id=alice["user"]["id"], title="Alice's chat"))
    db_session.commit()

    response = client.get("/conversations", headers=auth_headers(alice["access_token"]))

    assert response.status_code == 200
    conversations = response.json()["conversations"]
    assert [c["theme"] for c in conversations] == ["Alice's chat"]
    assert bob_conv.id not in [c["conversation_id"] for c in conversations]


def test_list_conversations_requires_auth(client):
    response = client.get("/conversations")

    assert response.status_code == 401


def test_rename_own_conversation_succeeds(client, db_session, signup, auth_headers):
    alice = signup(email="alice@example.com")
    conversation = Conversation(user_id=alice["user"]["id"], title="Untitled")
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)

    response = client.patch(
        f"/conversations/{conversation.id}",
        json={"title": "  Renamed chat  "},
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 200
    assert response.json()["theme"] == "Renamed chat"  # trimmed


def test_rename_rejects_empty_title(client, db_session, signup, auth_headers):
    alice = signup(email="alice@example.com")
    conversation = Conversation(user_id=alice["user"]["id"], title="Untitled")
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)

    response = client.patch(
        f"/conversations/{conversation.id}",
        json={"title": "   "},
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 400


def test_cannot_rename_another_user_s_conversation(
    client, db_session, signup, auth_headers
):
    alice = signup(email="alice@example.com")
    _bob_id, bob_conv = _make_user_and_conversation(db_session, "bob@example.com")

    response = client.patch(
        f"/conversations/{bob_conv.id}",
        json={"title": "Hijacked"},
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 404
    db_session.refresh(bob_conv)
    assert bob_conv.title == "New chat"  # untouched


def test_delete_own_conversation_succeeds(client, db_session, signup, auth_headers):
    alice = signup(email="alice@example.com")
    conversation = Conversation(user_id=alice["user"]["id"], title="To delete")
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)

    response = client.delete(
        f"/conversations/{conversation.id}",
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 204
    # The delete happened through a different session (the one `get_db`
    # hands the request). db_session's identity map doesn't know that —
    # without expiring it first, .get() returns the cached pre-delete
    # object instead of re-querying.
    db_session.expire_all()
    assert db_session.get(Conversation, conversation.id) is None


def test_cannot_delete_another_user_s_conversation(
    client, db_session, signup, auth_headers
):
    alice = signup(email="alice@example.com")
    _bob_id, bob_conv = _make_user_and_conversation(db_session, "bob@example.com")

    response = client.delete(
        f"/conversations/{bob_conv.id}",
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 404
    assert db_session.get(Conversation, bob_conv.id) is not None


def test_delete_nonexistent_conversation_returns_404(client, signup, auth_headers):
    alice = signup(email="alice@example.com")

    response = client.delete(
        "/conversations/does-not-exist",
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 404
