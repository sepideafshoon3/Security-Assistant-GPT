"""
Auth: password hashing, JWT session tokens, and a FastAPI dependency that
resolves the current authenticated user from the Authorization header.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from src.db.models import User
from src.db.session import get_db

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)

_DEV_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"
_cached_secret: Optional[str] = None


def _get_jwt_secret() -> str:
    global _cached_secret
    if _cached_secret is None:
        secret = os.getenv("JWT_SECRET_KEY")
        app_env = os.getenv("APP_ENV", "development").strip().lower()

        if not secret:
            if app_env not in ("development", "dev", "local"):
                raise RuntimeError(
                    f"JWT_SECRET_KEY is not set and APP_ENV={app_env!r} is not "
                    "a local/dev environment. Refusing to start with an "
                    "insecure default secret. Set JWT_SECRET_KEY (e.g. "
                    "`openssl rand -hex 32`) before deploying."
                )
            logger.warning(
                "[auth] JWT_SECRET_KEY is not set - using an insecure "
                "development default. Set JWT_SECRET_KEY in your .env "
                "before deploying."
            )
            secret = _DEV_DEFAULT_SECRET
        _cached_secret = secret
    return _cached_secret


def ensure_jwt_secret_configured() -> None:
    """Call once at app startup so a missing JWT_SECRET_KEY in a non-dev
    environment fails immediately, rather than on the first login request."""
    _get_jwt_secret()


def _get_jwt_algorithm() -> str:
    return os.getenv("JWT_ALGORITHM", "HS256")


def _get_jwt_expire_minutes() -> int:
    return int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24 * 7)))

def create_access_token(*, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=_get_jwt_expire_minutes()),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_get_jwt_algorithm())

def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_get_jwt_algorithm()])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user_id


_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user