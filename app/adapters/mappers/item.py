"""Reading an item's fields and building the event: refine, skip, times, uid."""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.adapters.events import ScrapedEvent
from app.adapters.mappers.errors import FieldFailure
from app.adapters.mappers.times import event_times, text_or_none
from app.adapters.mappers.window import Window
from app.adapters.schema import FieldMap, FieldSpec

Reader = Callable[[FieldSpec, str], Any]
"""Reads a field's raw value from one item: `read(spec, field_name)`, None when nothing matched."""

DEFAULT_UID_FIELDS = ("title", "start", "location")
REQUIRED_FIELDS = ("title", "start", "date")
_EVENT_ATTRS = {"start": "start_utc", "end": "end_utc"}


class _Missing(Exception):
    """A field had no value; the message says why."""


def map_item(
    field_map: FieldMap,
    read: Reader,
    window: Window,
    uid_fields: list[str] | None = None,
) -> ScrapedEvent | None:
    """The item as an event, or None when `skip_if` matches. Raises `FieldFailure`."""
    values = _read_all(field_map, read)
    if _skipped(field_map.skip_if, values["skip_if"]):
        return None
    start, end = event_times(field_map, values, window)
    fields = _event_fields(values, start, end)
    return ScrapedEvent(uid=_uid(fields, uid_fields or DEFAULT_UID_FIELDS), **fields)


def _read_all(field_map: FieldMap, read: Reader) -> dict[str, Any]:
    """Every mapped field's refined value. Title, start and a mapped date are required."""
    values: dict[str, Any] = {}
    for name in FieldMap.model_fields:
        spec = getattr(field_map, name)
        values[name] = None if spec is None else _read_field(spec, name, read)
    return values


def _read_field(spec: FieldSpec, name: str, read: Reader) -> Any:
    try:
        return _refine(spec, read(spec, name))
    except _Missing as missing:
        if name in REQUIRED_FIELDS:
            raise FieldFailure(name, str(missing)) from None
        return None


def _refine(spec: FieldSpec, value: Any) -> Any:
    """Apply `regex` (first group, else the whole match) and `strip` to a raw value."""
    if value is None or value == "":
        raise _Missing(f"{_source(spec)} matched nothing")
    if spec.regex is not None:
        value = _regex_value(spec.regex, str(value))
    if spec.strip and isinstance(value, str):
        value = value.strip()
    return value


def _regex_value(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise _Missing(f"regex {pattern!r} didn't match {text!r}")
    return match.group(1) if match.re.groups else match.group(0)


def _source(spec: FieldSpec) -> str:
    """Names where a field reads from, for error messages: `selector 'h3'`."""
    for key in ("selector", "from_context", "jsonpath"):
        value = getattr(spec, key)
        if value is not None:
            attr = f" attr {spec.attr!r}" if spec.attr else ""
            return f"{key} {value!r}{attr}"
    return "field"


def _skipped(spec: FieldSpec | None, value: Any) -> bool:
    """HTML gives text, so `equals: -12` also matches the text `-12`."""
    if spec is None or value is None:
        return False
    return value == spec.equals or str(value) == str(spec.equals)


def _event_fields(values: dict[str, Any], start: datetime, end: datetime | None) -> dict[str, Any]:
    return {
        "title": str(values["title"]),
        "start_utc": start,
        "end_utc": end,
        "location": text_or_none(values["location"]),
        "description": text_or_none(values["description"]),
        "url": text_or_none(values["url"]),
    }


def _uid(fields: dict[str, Any], names: tuple[str, ...] | list[str]) -> str:
    """A stable id from the chosen map fields; `date` means the start's date."""
    values = [_uid_value(fields, name) for name in names]
    payload = json.dumps(values, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _uid_value(fields: dict[str, Any], name: str) -> Any:
    if name == "date":
        return fields["start_utc"].date().isoformat()
    value = fields[_EVENT_ATTRS.get(name, name)]
    return value.isoformat() if isinstance(value, datetime) else value
