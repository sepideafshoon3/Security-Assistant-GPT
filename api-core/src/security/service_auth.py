from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def verify_online_learning_api_key(
    authorization: str | None = Header(default=None),
) -> None:
    expected = os.getenv("ONLINE_LEARNING_API_KEY")
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Online learning collector is not configured.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
