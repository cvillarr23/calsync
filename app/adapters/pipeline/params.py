"""Checking a source's params against the definition before a run."""

from collections.abc import Mapping
from typing import Any

from app.adapters.pipeline.errors import ParamError
from app.adapters.schema import Param, PipelineDefinition


def resolve_params(definition: PipelineDefinition, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Fill in defaults and coerce types, failing on unknown or missing params."""
    unknown = sorted(set(raw) - set(definition.params))
    if unknown:
        raise ParamError(f"unknown param(s): {', '.join(unknown)}")
    return {
        name: _param_value(name, param, raw.get(name, param.default))
        for name, param in definition.params.items()
    }


def _param_value(name: str, param: Param, value: Any) -> Any:
    if value is None:
        raise ParamError(f"missing param: {name}")
    if param.type != "int":
        return str(value)
    try:
        return int(value)
    except ValueError:
        raise ParamError(f"param {name} must be an int, got {value!r}") from None
