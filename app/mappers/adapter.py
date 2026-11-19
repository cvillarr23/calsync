from typing import Any

from app.adapters.schema import AdapterDefinition
from app.db.models import AdapterDef
from app.schemas.adapter import AdapterDetail, AdapterSummary
from app.services.definition_store import load_row
from app.services.definition_text import dump_yaml


def adapter_summary(definition: AdapterDefinition, *, builtin: bool) -> AdapterSummary:
    return AdapterSummary(
        id=definition.id,
        name=definition.name,
        kind=definition.kind,
        version=definition.version,
        builtin=builtin,
    )


def builtin_detail(definition: AdapterDefinition) -> AdapterDetail:
    data = _definition_dict(definition)
    summary = adapter_summary(definition, builtin=True)
    return AdapterDetail(**summary.model_dump(), definition=data, yaml=dump_yaml(data))


def user_detail(row: AdapterDef) -> AdapterDetail:
    """A stored definition, with the YAML exactly as the user wrote it."""
    definition = load_row(row)
    summary = adapter_summary(definition, builtin=False)
    return AdapterDetail(
        **summary.model_dump(), definition=_definition_dict(definition), yaml=row.yaml
    )


def _definition_dict(definition: AdapterDefinition) -> dict[str, Any]:
    return definition.model_dump(mode="json", by_alias=True, exclude_defaults=True)
