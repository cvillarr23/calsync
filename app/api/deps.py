"""Dependencies shared by the route modules."""

from typing import Annotated

from fastapi import Depends, Request

from app.adapters.registry import AdapterRegistry
from app.db.models import User
from app.db.session import Db
from app.services.users import local_user
from app.settings import Settings


def current_user(db: Db) -> User:
    """The user a request acts as: the local user until Google sign-in replaces this."""
    return local_user(db)


def _registry(request: Request) -> AdapterRegistry:
    return request.app.state.adapters


def _settings(request: Request) -> Settings:
    return request.app.state.settings


CurrentUser = Annotated[User, Depends(current_user, scope="function")]
Registry = Annotated[AdapterRegistry, Depends(_registry)]
AppSettings = Annotated[Settings, Depends(_settings)]
