"""Dependencies shared by the API and web routers."""

from typing import Annotated

from fastapi import Depends, Request

from app.adapters.registry import AdapterRegistry
from app.db.models import User
from app.db.session import Db
from app.services.auth import GoogleOAuth
from app.services.scheduling import SyncScheduler
from app.settings import Settings

SESSION_USER = "user_id"


class NotSignedIn(Exception):
    """No valid session: the API answers 401, pages redirect to sign-in."""


def current_user(request: Request, db: Db) -> User:
    """The signed-in user, from the signed session cookie."""
    user_id = request.session.get(SESSION_USER)
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        raise NotSignedIn
    return user


def _registry(request: Request) -> AdapterRegistry:
    return request.app.state.adapters


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _scheduler(request: Request) -> SyncScheduler:
    return request.app.state.scheduler


def _google(request: Request) -> GoogleOAuth:
    return request.app.state.google


CurrentUser = Annotated[User, Depends(current_user, scope="function")]
Registry = Annotated[AdapterRegistry, Depends(_registry)]
AppSettings = Annotated[Settings, Depends(_settings)]
AppScheduler = Annotated[SyncScheduler, Depends(_scheduler)]
Google = Annotated[GoogleOAuth, Depends(_google)]
