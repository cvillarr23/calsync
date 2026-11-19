from typing import Any

from pydantic import BaseModel


class AdapterSummary(BaseModel):
    id: str
    name: str
    kind: str
    version: int
    builtin: bool


class AdapterDetail(AdapterSummary):
    definition: dict[str, Any]
    yaml: str
