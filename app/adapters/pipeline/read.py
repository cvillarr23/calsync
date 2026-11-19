"""Reading `map` fields from a JSON item with JSONPath, for the shared mappers."""

from typing import Any

from app.adapters.mappers import FieldFailure, Reader
from app.adapters.pipeline.documents import compiled
from app.adapters.pipeline.errors import CSS_UNSUPPORTED
from app.adapters.schema import FieldSpec


def jsonpath_reader(item: Any) -> Reader:
    """Reads each field as its JSONPath's first match in the item, or None."""

    def read(spec: FieldSpec, name: str) -> Any:
        if spec.jsonpath is None:
            raise FieldFailure(name, CSS_UNSUPPORTED)
        matches = compiled(spec.jsonpath).find(item)
        return matches[0].value if matches else None

    return read
