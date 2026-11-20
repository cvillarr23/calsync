"""Creating, changing and deleting a user's sources."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.db.models import Source, User
from app.services.errors import Invalid, NotFound
from app.services.source_validation import source_problems
from app.settings import Settings


def user_sources(db: Session, user: User) -> list[Source]:
    return list(db.scalars(select(Source).where(Source.user_id == user.id).order_by(Source.id)))


def owned_source(db: Session, user: User, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.user_id != user.id:
        raise NotFound(f"source {source_id} not found")
    return source


def create_source(
    db: Session,
    user: User,
    columns: dict[str, Any],
    registry: AdapterRegistry,
    settings: Settings,
) -> Source:
    source = Source(user_id=user.id)
    update_source(source, columns, registry, settings)
    db.add(source)
    db.flush()
    return source


def update_source(
    source: Source, columns: dict[str, Any], registry: AdapterRegistry, settings: Settings
) -> None:
    """Write the columns, then validate the source as a whole.

    A rejected change raises before the request's session commits, so nothing is saved.
    """
    for column, value in columns.items():
        setattr(source, column, value)
    problems = source_problems(source, registry, settings)
    if problems:
        raise Invalid(problems)
