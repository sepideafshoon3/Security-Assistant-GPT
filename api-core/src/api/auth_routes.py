from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.schemas.schemas_auth import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    UserPublic,
)
from src.db.models import User
from src.db.session import get_db
from src.security.audit import audit_log
from src.security.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> AuthResponse:
    normalized_email = body.email.lower()

    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=normalized_email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    db.refresh(user)

    audit_log("auth_signup", {"user_id": user.id})

    token = create_access_token(user_id=user.id)
    return AuthResponse(
        access_token=token,
        user=UserPublic(id=user.id, email=user.email),
    )


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    normalized_email = body.email.lower()

    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    audit_log("auth_login", {"user_id": user.id})

    token = create_access_token(user_id=user.id)
    return AuthResponse(
        access_token=token,
        user=UserPublic(id=user.id, email=user.email),
    )


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic(id=current_user.id, email=current_user.email)
