"""`/api/adapters`: built-in definitions (read-only) and the user's own definitions."""

from fastapi import APIRouter, Request, Response, status

from app.adapters.schema import AdapterDefinition
from app.api.deps import CurrentUser, Registry
from app.db.session import Db
from app.mappers.adapter import adapter_summary, builtin_detail, user_detail
from app.schemas.adapter import AdapterDetail, AdapterSummary
from app.services import adapter_defs

router = APIRouter(prefix="/adapters")


@router.get("")
def list_adapters(user: CurrentUser, registry: Registry) -> list[AdapterSummary]:
    return [
        adapter_summary(definition, builtin=registry.is_builtin(definition.id))
        for definition in registry.all(user.id)
    ]


@router.get("/{adapter_id}")
def get_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> AdapterDetail:
    builtin = registry.get(adapter_id) if registry.is_builtin(adapter_id) else None
    if builtin is not None:
        return builtin_detail(builtin)
    return user_detail(adapter_defs.owned_definition(db, user, adapter_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_adapter(
    request: Request, db: Db, user: CurrentUser, registry: Registry
) -> AdapterDetail:
    definition, text = await _definition_body(request)
    return user_detail(adapter_defs.create_definition(db, user, registry, definition, text))


@router.put("/{adapter_id}")
async def replace_adapter(
    adapter_id: str, request: Request, db: Db, user: CurrentUser, registry: Registry
) -> AdapterDetail:
    adapter_defs.require_not_builtin(registry, adapter_id)
    row = adapter_defs.owned_definition(db, user, adapter_id)
    definition, text = await _definition_body(request)
    adapter_defs.replace_definition(db, registry, row, definition, text)
    return user_detail(row)


@router.delete("/{adapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> Response:
    adapter_defs.require_not_builtin(registry, adapter_id)
    row = adapter_defs.owned_definition(db, user, adapter_id)
    adapter_defs.delete_definition(db, registry, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _definition_body(request: Request) -> tuple[AdapterDefinition, str]:
    """The request's definition, from YAML text or a JSON object, plus the YAML to store."""
    body = (await request.body()).decode()
    is_yaml = "yaml" in request.headers.get("content-type", "")
    return adapter_defs.parse_text(body, is_yaml=is_yaml)
