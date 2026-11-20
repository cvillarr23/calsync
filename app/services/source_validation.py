"""Checks a source as a whole once its fields are set: interval, adapter and params."""

from typing import Any
from urllib.parse import urlsplit

from app.adapters.registry import AdapterRegistry
from app.adapters.schema import Param
from app.db.models import Source
from app.db.models.source import DEFAULT_INTERVAL_MIN
from app.settings import Settings

Problem = dict[str, str]
"""`{"loc": "params.url", "msg": "required"}`, the same shape as definition errors."""


def source_problems(source: Source, registry: AdapterRegistry, settings: Settings) -> list[Problem]:
    return [*_interval_problems(source, settings), *_adapter_problems(source, registry)]


def problem(loc: str, msg: object) -> Problem:
    return {"loc": loc, "msg": str(msg)}


def _interval_problems(source: Source, settings: Settings) -> list[Problem]:
    interval = source.interval_min if source.interval_min is not None else DEFAULT_INTERVAL_MIN
    if interval < settings.min_interval_min:
        return [problem("interval_min", f"must be at least {settings.min_interval_min} minutes")]
    return []


def _adapter_problems(source: Source, registry: AdapterRegistry) -> list[Problem]:
    definition = registry.get(source.adapter_id, source.user_id)
    if definition is None:
        return [problem("adapter_id", f"adapter {source.adapter_id!r} not found")]
    return _param_problems(definition.params, source.params_json or {})


def _param_problems(declared: dict[str, Param], given: dict[str, Any]) -> list[Problem]:
    """Every given param must be declared; every declared param needs a value or a default."""
    problems = [
        problem(f"params.{name}", "not a parameter of this adapter")
        for name in given
        if name not in declared
    ]
    for name, param in declared.items():
        msg = _param_problem(param, given.get(name))
        if msg:
            problems.append(problem(f"params.{name}", msg))
    return problems


def _param_problem(param: Param, value: Any) -> str | None:
    if value is None:
        return "required" if param.default is None else None
    if param.type == "int":
        return None if isinstance(value, int) and not isinstance(value, bool) else "must be an int"
    if not isinstance(value, str):
        return "must be a string"
    if param.type == "url" and not _is_http_url(value):
        return "must be an http(s) URL"
    return None


def _is_http_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)
