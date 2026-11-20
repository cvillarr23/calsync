"""The source form's fields ↔ a `SourcePatch` body, and a source back into form values."""

import re
from collections.abc import Mapping
from typing import Any

from app.adapters.schema import AdapterDefinition, Param
from app.db.models import Source
from app.db.models.source import DEFAULT_INTERVAL_MIN, DEFAULT_LOOKAHEAD_DAYS

PARAM_PREFIX = "param."
_INT = re.compile(r"^-?\d+$")


def source_form_data(form: Mapping[str, Any], definition: AdapterDefinition | None) -> dict:
    """The posted form as a `SourcePatch` body. Blank numbers mean "use the default"."""
    return {
        "name": str(form.get("name", "")).strip(),
        "adapter_id": str(form.get("adapter_id", "")),
        "params": form_params(form, definition),
        "include_kw": _lines(form.get("include_kw")),
        "exclude_kw": _lines(form.get("exclude_kw")),
        "interval_min": _blank_to_none(form.get("interval_min")),
        "lookahead_days": _blank_to_none(form.get("lookahead_days")),
        "target_calendar_id": _blank_to_none(form.get("target_calendar_id")),
        "enabled": form.get("enabled") == "on",
    }


def form_params(form: Mapping[str, Any], definition: AdapterDefinition | None) -> dict[str, Any]:
    """`param.<name>` fields for the definition's declared params; blanks are left out."""
    declared = definition.params if definition else {}
    values = {name: str(form.get(PARAM_PREFIX + name, "")).strip() for name in declared}
    return {name: _typed(declared[name], raw) for name, raw in values.items() if raw}


def source_form_values(source: Source) -> dict[str, Any]:
    return {
        "name": source.name,
        "adapter_id": source.adapter_id,
        "params": source.params_json,
        "include_kw": "\n".join(source.include_kw),
        "exclude_kw": "\n".join(source.exclude_kw),
        "interval_min": source.interval_min,
        "lookahead_days": source.lookahead_days,
        "target_calendar_id": source.target_calendar_id,
        "enabled": source.enabled,
    }


def blank_form_values() -> dict[str, Any]:
    return {
        "name": "",
        "adapter_id": "",
        "params": {},
        "include_kw": "",
        "exclude_kw": "",
        "interval_min": DEFAULT_INTERVAL_MIN,
        "lookahead_days": DEFAULT_LOOKAHEAD_DAYS,
        "target_calendar_id": None,
        "enabled": True,
    }


def echo_form_values(data: dict[str, Any]) -> dict[str, Any]:
    """A rejected form's values, shaped like `source_form_values` for re-rendering."""
    return {
        **data,
        "include_kw": "\n".join(data["include_kw"]),
        "exclude_kw": "\n".join(data["exclude_kw"]),
    }


def _typed(param: Param, raw: str) -> Any:
    """Int params become ints when they look like one; validation reports anything else."""
    return int(raw) if param.type == "int" and _INT.match(raw) else raw


def _lines(value: Any) -> list[str]:
    """One keyword per line; commas also separate, since people paste lists."""
    parts = re.split(r"[\n,]", str(value or ""))
    return [part.strip() for part in parts if part.strip()]


def _blank_to_none(value: Any) -> Any:
    return None if value is None or str(value).strip() == "" else str(value).strip()
