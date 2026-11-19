"""`/api/sources`: the user's calendar sources."""

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.api.deps import AppSettings, CurrentUser, Registry
from app.api.errors import not_found, unprocessable
from app.db.models import Source, User
from app.db.session import Db
from app.mappers.source import source_columns, source_out
from app.schemas.source import SourceCreate, SourceOut, SourcePatch
from app.services.source_validation import source_problems
from app.settings import Settings

router = APIRouter(prefix="/sources")


@router.get("")
def list_sources(db: Db, user: CurrentUser, settings: AppSettings) -> list[SourceOut]:
    rows = db.scalars(select(Source).where(Source.user_id == user.id).order_by(Source.id))
    return [source_out(settings, row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceCreate, db: Db, user: CurrentUser, registry: Registry, settings: AppSettings
) -> SourceOut:
    source = Source(user_id=user.id)
    _apply(source, body, set(SourcePatch.model_fields), registry, settings)
    db.add(source)
    db.flush()
    return source_out(settings, source)


@router.get("/{source_id}")
def get_source(source_id: int, db: Db, user: CurrentUser, settings: AppSettings) -> SourceOut:
    return source_out(settings, _owned_source(db, user, source_id))


@router.patch("/{source_id}")
def update_source(
    source_id: int,
    body: SourcePatch,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
) -> SourceOut:
    source = _owned_source(db, user, source_id)
    _apply(source, body, body.model_fields_set, registry, settings)
    db.flush()
    return source_out(settings, source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, db: Db, user: CurrentUser) -> Response:
    db.delete(_owned_source(db, user, source_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _owned_source(db: Session, user: User, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.user_id != user.id:
        raise not_found(f"source {source_id} not found")
    return source


def _apply(
    source: Source,
    body: SourcePatch,
    fields: set[str],
    registry: AdapterRegistry,
    settings: Settings,
) -> None:
    """Write the given fields, then validate the source as a whole.

    A rejected change raises before the request's session commits, so nothing is saved.
    """
    for column, value in source_columns(body, fields).items():
        setattr(source, column, value)
    problems = source_problems(source, registry, settings)
    if problems:
        raise unprocessable(problems)
