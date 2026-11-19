"""Which user a request acts as."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User

LOCAL_USER_EMAIL = "local"


def local_user(db: Session) -> User:
    """The single local user every request acts as until Google sign-in exists.

    Created on first use. Sign-in replaces the API dependency that calls this.
    """
    user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        user = User(email=LOCAL_USER_EMAIL)
        db.add(user)
        db.flush()
    return user
