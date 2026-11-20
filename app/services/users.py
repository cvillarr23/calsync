"""Signing a Google identity in as a calsync user."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth import Identity
from app.services.tokens import encrypt_token
from app.settings import Settings

LOCAL_USER_EMAIL = "local"
"""The user the API acted as before sign-in existed."""


def needs_consent(db: Session, identity: Identity) -> bool:
    """Google sent no refresh token and none is stored, so background syncs couldn't run."""
    if identity.refresh_token:
        return False
    user = _by_email(db, identity.email)
    return user is None or user.refresh_token_enc is None


def sign_in(db: Session, identity: Identity, settings: Settings) -> User:
    """The user for this identity, created on first sign-in; stores a new refresh token."""
    user = _by_email(db, identity.email) or _adopted_local_user(db, identity.email)
    if user is None:
        user = User(email=identity.email)
        db.add(user)
    if identity.refresh_token:
        user.refresh_token_enc = encrypt_token(settings, identity.refresh_token)
    db.flush()
    return user


def _by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def _adopted_local_user(db: Session, email: str) -> User | None:
    """The first person to sign in takes over the pre-sign-in local user and its sources."""
    user = _by_email(db, LOCAL_USER_EMAIL)
    if user is not None:
        user.email = email.lower()
    return user
