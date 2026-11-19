"""`/api/adapters`: built-in definitions (read-only) and the user's own definitions."""

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.adapters.schema import AdapterDefinition, error_list
from app.api.deps import CurrentUser, Registry
from app.api.errors import conflict, not_found, unprocessable
from app.db.models import AdapterDef, Source, User
from app.db.session import Db
from app.mappers.adapter import adapter_summary, builtin_detail, user_detail
from app.schemas.adapter import AdapterDetail, AdapterSummary
from app.services.definition_store import parse_user_definition
from app.services.definition_text import (
    DefinitionTextError,
    dump_yaml,
    load_json_object,
    load_yaml,
)
from app.services.source_validation import problem

router = APIRouter(prefix="/adapters")


@router.get("")
def list_adapters(registry: Registry) -> list[AdapterSummary]:
    return [
        adapter_summary(definition, builtin=registry.is_builtin(definition.id))
        for definition in registry.all()
    ]


@router.get("/{adapter_id}")
def get_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> AdapterDetail:
    builtin = registry.get(adapter_id) if registry.is_builtin(adapter_id) else None
    if builtin is not None:
        return builtin_detail(builtin)
    return user_detail(_owned_definition(db, user, adapter_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_adapter(
    request: Request, db: Db, user: CurrentUser, registry: Registry
) -> AdapterDetail:
    definition, text = await _definition_body(request)
    _require_free_id(db, registry, definition.id)
    row = AdapterDef(id=definition.id, user_id=user.id, yaml=text, version=definition.version)
    db.add(row)
    db.flush()
    return user_detail(row)


@router.put("/{adapter_id}")
async def replace_adapter(
    adapter_id: str, request: Request, db: Db, user: CurrentUser, registry: Registry
) -> AdapterDetail:
    _require_not_builtin(registry, adapter_id)
    row = _owned_definition(db, user, adapter_id)
    definition, text = await _definition_body(request)
    _require_same_id(adapter_id, definition)
    row.yaml, row.version = text, definition.version
    db.flush()
    return user_detail(row)


@router.delete("/{adapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> Response:
    _require_not_builtin(registry, adapter_id)
    row = _owned_definition(db, user, adapter_id)
    _require_unused(db, adapter_id)
    db.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _definition_body(request: Request) -> tuple[AdapterDefinition, str]:
    """The request's definition, from YAML text or a JSON object, plus the YAML to store."""
    data, text = await _body_data(request)
    try:
        return parse_user_definition(data), text
    except ValidationError as err:
        raise unprocessable(error_list(err)) from None


async def _body_data(request: Request) -> tuple[dict[str, Any], str]:
    """Keep YAML exactly as written, comments included; JSON bodies are stored as YAML."""
    body = (await request.body()).decode()
    try:
        if "yaml" in request.headers.get("content-type", ""):
            return load_yaml(body), body
        data = load_json_object(body)
    except DefinitionTextError as err:
        raise unprocessable([problem("(body)", err)]) from None
    return data, dump_yaml(data)


def _owned_definition(db: Session, user: User, adapter_id: str) -> AdapterDef:
    row = db.get(AdapterDef, adapter_id)
    if row is None or row.user_id != user.id:
        raise not_found(f"adapter {adapter_id!r} not found")
    return row


def _require_free_id(db: Session, registry: AdapterRegistry, adapter_id: str) -> None:
    if registry.is_builtin(adapter_id) or db.get(AdapterDef, adapter_id) is not None:
        raise conflict(f"adapter id {adapter_id!r} is taken")


def _require_not_builtin(registry: AdapterRegistry, adapter_id: str) -> None:
    if registry.is_builtin(adapter_id):
        raise conflict("built-in adapters are read-only")


def _require_same_id(adapter_id: str, definition: AdapterDefinition) -> None:
    if definition.id != adapter_id:
        msg = f"id must stay {adapter_id!r}; create a new definition to change it"
        raise unprocessable([problem("id", msg)])


def _require_unused(db: Session, adapter_id: str) -> None:
    used = db.scalar(select(Source.id).where(Source.adapter_id == adapter_id).limit(1))
    if used is not None:
        raise conflict(f"adapter {adapter_id!r} is used by sources")
