#!/usr/bin/env python3
"""End-to-end smoke test against a *deployed* environment: signup ->
login -> chat -> rename -> delete -> logout. Doesn't touch local dev at
all -- point it at a real, reachable base URL (e.g. your Render staging
service).

Usage:
    python scripts/smoke_test_staging.py https://security-assistant-api.onrender.com

Exits 0 and prints "ALL CHECKS PASSED" on success; exits 1 and prints
exactly which step failed otherwise.

Notes:
- The chat step is a REAL LLM call (not mocked) -- the target needs a
  working OPENAI_API_KEY configured, and this will make one real API
  call each run.
- /auth/login and /chat are rate-limited (5/min and 20/min by default,
  see RATE_LIMIT_LOGIN / RATE_LIMIT_CHAT) -- re-running this in a tight
  loop against the same deployment can trip that.
- The free Render tier sleeps services after 15 min idle; the first
  request here may hang for 30-60s waking it up. That's expected, not
  a failure.
- "logout" has no server-side counterpart (stateless JWT, no session to
  revoke) -- the last check confirms that's genuinely how it behaves
  (the old token still works) rather than asserting a server-side
  invalidation that doesn't exist.
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_test_staging.py <base_url>", file=sys.stderr)
        return 2

    base_url = sys.argv[1].rstrip("/")
    email = f"smoke-test-{uuid.uuid4().hex[:8]}@example.com"
    password = "smoke-test-password-123"
    passed: list[str] = []

    def ok(label: str) -> None:
        passed.append(label)
        print(f"  ok: {label}")

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        # 1. signup
        r = client.post("/auth/signup", json={"email": email, "password": password})
        assert r.status_code == 201, f"signup failed: {r.status_code} {r.text}"
        ok("signup")

        # 2. login (separate code path from signup -- worth its own check)
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        ok("login")

        # 3. chat -- real LLM call, creates a conversation, streams SSE
        conversation_id: str | None = None
        reply_text = ""
        with client.stream(
            "POST",
            "/chat",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": "Reply with exactly the word: pong"}
                ]
            },
            timeout=60.0,
        ) as r:
            assert (
                r.status_code == 200
            ), f"chat failed to start: {r.status_code} {r.read()!r}"
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[len("data: ") :])
                if event["type"] == "start":
                    conversation_id = event["conversation_id"]
                elif event["type"] == "chunk":
                    reply_text += event["text"]
                elif event["type"] == "error":
                    raise AssertionError(f"chat generation error: {event['message']}")
                elif event["type"] == "done":
                    break
        assert conversation_id, "chat never sent a start event with a conversation_id"
        assert reply_text.strip(), "chat finished with an empty reply"
        ok(f"chat (conversation {conversation_id}, reply: {reply_text.strip()[:60]!r})")

        # 4. rename
        r = client.patch(
            f"/conversations/{conversation_id}",
            headers=headers,
            json={"title": "Smoke test conversation"},
        )
        assert r.status_code == 200, f"rename failed: {r.status_code} {r.text}"
        assert (
            r.json()["theme"] == "Smoke test conversation"
        ), f"rename didn't stick: {r.json()}"
        ok("rename")

        # 5. delete
        r = client.delete(f"/conversations/{conversation_id}", headers=headers)
        assert r.status_code == 204, f"delete failed: {r.status_code} {r.text}"
        r = client.get("/conversations", headers=headers)
        remaining_ids = [c["conversation_id"] for c in r.json()["conversations"]]
        assert conversation_id not in remaining_ids, "deleted conversation still listed"
        ok("delete")

        # 6. logout -- stateless JWT, no server-side session to revoke.
        # "Logging out" is the frontend discarding the token; confirm
        # that's really all it is by checking the old token still works.
        r = client.get("/auth/me", headers=headers)
        assert (
            r.status_code == 200
        ), "old token stopped working -- unexpected given stateless JWT auth"
        ok("logout (confirmed client-side-only: token isn't server-revoked)")

    print(f"\nALL CHECKS PASSED ({len(passed)}/6): {base_url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nSMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except httpx.HTTPError as exc:
        print(f"\nSMOKE TEST FAILED (network/HTTP error): {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
