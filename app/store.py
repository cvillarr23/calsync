"""User adapter definitions, stored in the database as the YAML the user wrote.

Every load goes through `parse_definition(..., builtin=False)`, so a stored
definition can never use the built-in-only python kind, whatever was written
to the table.
"""

import logging
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.schema import AdapterDefinition, parse_definition
from app.db import AdapterDef

log = logging.getLogger(__name__)


class DefinitionTextError(ValueError):
    """A definition body isn't valid YAML or JSON, or isn't a mapping."""


def parse_user_definition(data: Any) -> AdapterDefinition:
    """Validate a user definition, raising `ValidationError` with field paths."""
    return parse_definition(data, builtin=False)


def load_yaml(text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise DefinitionTextError(f"invalid YAML: {err}") from None
    if not isinstance(data, dict):
        raise DefinitionTextError("a definition must be a YAML mapping")
    return data


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_row(row: AdapterDef) -> AdapterDefinition:
    """Parse a stored row; raises if it is no longer a valid user definition."""
    return parse_user_definition(load_yaml(row.yaml))


class DefinitionStore:
    """Feeds stored user definitions to the adapter registry via `registry.add_source`."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def definitions(self) -> list[AdapterDefinition]:
        with self._sessions() as db:
            rows = db.scalars(select(AdapterDef).order_by(AdapterDef.id)).all()
        return [definition for row in rows if (definition := _valid_or_none(row))]


def _valid_or_none(row: AdapterDef) -> AdapterDefinition | None:
    """Skip a row that no longer validates, so one bad row can't hide the rest."""
    try:
        return load_row(row)
    except (DefinitionTextError, ValidationError) as err:
        log.warning("skipping stored adapter definition %r: %s", row.id, err)
        return None
