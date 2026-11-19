"""The adapter definition JSON Schema, for editors and other clients."""

from typing import Any

from fastapi import APIRouter

from app.adapters.schema import definition_json_schema

router = APIRouter()


@router.get("/schema/adapter.json")
def adapter_schema() -> dict[str, Any]:
    return definition_json_schema()
