"""Creating, replacing and deleting a user's adapter definitions."""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.adapters.schema import AdapterDefinition, error_list
from app.db.models import AdapterDef, Source, User
from app.services.definition_store import parse_user_definition
from app.services.definition_text import (
    DefinitionTextError,
    dump_yaml,
    load_json_object,
    load_yaml,
)
from app.services.errors import Conflict, Invalid, NotFound
from app.services.source_validation import problem


def parse_text(text: str, *, is_yaml: bool) -> tuple[AdapterDefinition, str]:
    """A definition from YAML or JSON text, plus the YAML to store.

    YAML is kept exactly as written, comments included; JSON is stored as YAML.
    """
    try:
        data = load_yaml(text) if is_yaml else load_json_object(text)
    except DefinitionTextError as err:
        raise Invalid([problem("(body)", err)]) from None
    try:
        definition = parse_user_definition(data)
    except ValidationError as err:
        raise Invalid(error_list(err)) from None
    return definition, text if is_yaml else dump_yaml(data)


def owned_definition(db: Session, user: User, adapter_id: str) -> AdapterDef:
    row = db.get(AdapterDef, adapter_id)
    if row is None or row.user_id != user.id:
        raise NotFound(f"adapter {adapter_id!r} not found")
    return row


def user_definitions(db: Session, user: User) -> list[AdapterDef]:
    query = select(AdapterDef).where(AdapterDef.user_id == user.id).order_by(AdapterDef.id)
    return list(db.scalars(query))


def create_definition(
    db: Session, user: User, registry: AdapterRegistry, definition: AdapterDefinition, text: str
) -> AdapterDef:
    _require_free_id(db, registry, definition.id)
    row = AdapterDef(id=definition.id, user_id=user.id, yaml=text, version=definition.version)
    db.add(row)
    db.flush()
    return row


def replace_definition(
    db: Session,
    registry: AdapterRegistry,
    row: AdapterDef,
    definition: AdapterDefinition,
    text: str,
) -> None:
    require_not_builtin(registry, row.id)
    _require_same_id(row.id, definition)
    row.yaml, row.version = text, definition.version
    db.flush()


def delete_definition(db: Session, registry: AdapterRegistry, row: AdapterDef) -> None:
    require_not_builtin(registry, row.id)
    _require_unused(db, row.id)
    db.delete(row)


def _require_free_id(db: Session, registry: AdapterRegistry, adapter_id: str) -> None:
    """Ids are unique across all users while `adapter_defs.id` is the primary key."""
    if registry.is_builtin(adapter_id) or db.get(AdapterDef, adapter_id) is not None:
        raise Conflict(f"adapter id {adapter_id!r} is taken")


def require_not_builtin(registry: AdapterRegistry, adapter_id: str) -> None:
    if registry.is_builtin(adapter_id):
        raise Conflict("built-in adapters are read-only")


def _require_same_id(adapter_id: str, definition: AdapterDefinition) -> None:
    if definition.id != adapter_id:
        msg = f"id must stay {adapter_id!r}; create a new definition to change it"
        raise Invalid([problem("id", msg)])


def _require_unused(db: Session, adapter_id: str) -> None:
    used = db.scalar(select(Source.id).where(Source.adapter_id == adapter_id).limit(1))
    if used is not None:
        raise Conflict(f"adapter {adapter_id!r} is used by sources")
