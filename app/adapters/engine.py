"""Runs `pipeline` adapter definitions: http → extract → paginate → items → map.

Steps run in order over a context of variables (the params plus anything saved
with `as`) and a current *document*: the last response body, or the last value
extracted without `as`. `paginate` re-runs the steps after it once per date in
the window; the items from every page are mapped to events and deduped by uid.

Also a CLI for trying a definition out:

    python -m app.adapters.engine def.yaml page_url=https://... [--days N] [--json]
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dateparser
import yaml
from jsonpath_ng import JSONPath
from jsonpath_ng.ext import parse as parse_jsonpath
from pydantic import ValidationError

from app.adapters import template
from app.adapters.fetch import FetchError, FetchLimits, FetchSession
from app.adapters.schema import (
    ExtractSpec,
    FieldSpec,
    HttpSpec,
    ItemsSpec,
    Param,
    PipelineDefinition,
    Step,
    error_list,
    parse_definition,
)

DEFAULT_UID_FIELDS = ("title", "start", "location")
DEFAULT_DAYS = 60
# TODO: support css once the html kind lands its selector code (cvillarr23/calsync#5).
CSS_UNSUPPORTED = "css is not supported in pipeline definitions yet"


@dataclass(frozen=True)
class Event:
    """One mapped event. Times are timezone-aware and in UTC."""

    uid: str
    title: str
    start: datetime
    end: datetime | None = None
    location: str | None = None
    description: str | None = None
    url: str | None = None


class AdapterError(RuntimeError):
    """An adapter run failed; the message says where."""


class ParamError(AdapterError):
    """The source's params don't fit the definition."""


class StepError(AdapterError):
    """A pipeline step failed. The message names the step's index and kind."""

    def __init__(self, index: int, kind: str, message: str) -> None:
        super().__init__(f"step {index} ({kind}): {message}")
        self.index = index
        self.kind = kind


class MapError(AdapterError):
    """A `map` field couldn't be resolved for one item."""

    def __init__(self, item: int, field: str, message: str) -> None:
        super().__init__(f"item {item}, map.{field}: {message}")
        self.item = item
        self.field = field


class _Failure(Exception):
    """Raised inside a step or field; the caller adds the step or field it happened in."""


@dataclass
class _State:
    variables: dict[str, Any]
    document: Any = None

    def save(self, name: str | None, value: Any) -> None:
        """Into the named variable, or over the document when there's no name."""
        if name:
            self.variables[name] = value
        else:
            self.document = value

    def fork(self, name: str, value: Any) -> "_State":
        return _State({**self.variables, name: value}, self.document)


@dataclass(frozen=True)
class _Run:
    steps: Sequence[Step]
    session: FetchSession
    start: date
    days: int


@dataclass
class _Times:
    start: datetime
    end: datetime | None = None


# ---------------------------------------------------------------------------
# Running steps


async def run_pipeline(
    definition: PipelineDefinition,
    params: Mapping[str, Any],
    *,
    session: FetchSession,
    start: date,
    days: int = DEFAULT_DAYS,
) -> list[Event]:
    """Run every step, map the items to events and dedupe them by uid, sorted by start."""
    run = _Run(definition.steps, session, start, days)
    items = await _run_steps(run, 0, _State(dict(params)))
    events = (map_item(definition, item, index) for index, item in enumerate(items))
    return _deduped(event for event in events if event is not None)


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


async def _run_steps(run: _Run, first: int, state: _State) -> list[Any]:
    """Run steps from `first` on; validation guarantees the last one is `items`."""
    for index in range(first, len(run.steps)):
        step = run.steps[index]
        if step.paginate is not None:
            return await _paginate(run, index, state)
        with _step_errors(index, step.kind):
            if step.items is not None:
                return _items(step.items, state)
            await _apply(run.session, step, state)
    return []


async def _apply(session: FetchSession, step: Step, state: _State) -> None:
    if step.http is not None:
        await _http(session, step.http, state)
    elif step.extract is not None:
        _extract(step.extract, state)


async def _paginate(run: _Run, index: int, state: _State) -> list[Any]:
    """Run the remaining steps once per page date, concatenating their items.

    The variable holds a `datetime`, not a string, so templates can format it
    with `{{date:%Y-%m-%d}}`.
    """
    spec = run.steps[index].paginate
    assert spec is not None
    items: list[Any] = []
    for day in _page_dates(run.start, run.days, spec.step_days):
        items += await _run_steps(run, index + 1, state.fork(spec.as_, day))
    return items


def _page_dates(start: date, days: int, step_days: int) -> Iterator[datetime]:
    midnight = datetime.combine(start, time())
    for offset in range(0, max(days, 1), step_days):
        yield midnight + timedelta(days=offset)


@contextmanager
def _step_errors(index: int, kind: str) -> Iterator[None]:
    """Name the failing step, so the editor can point at it."""
    try:
        yield
    except (_Failure, FetchError, template.TemplateError) as err:
        raise StepError(index, kind, str(err)) from None


async def _http(session: FetchSession, spec: HttpSpec, state: _State) -> None:
    url = template.render(spec.url, state.variables)
    page = await session.fetch(
        url,
        method=spec.method,
        headers=_render_all(spec.headers, state.variables),
        json=_json_body(spec, state.variables),
        data=_render_all(spec.form, state.variables) if spec.form is not None else None,
        follow_redirects=spec.follow_redirects,
    )
    if page.status_code >= 400:
        raise _Failure(f"{spec.method} {url} returned HTTP {page.status_code}")
    state.document = page.text


def _render_all(values: Mapping[str, str], variables: Mapping[str, Any]) -> dict[str, str]:
    return {key: template.render(value, variables) for key, value in values.items()}


def _json_body(spec: HttpSpec, variables: Mapping[str, Any]) -> Any:
    return None if spec.json_ is None else template.render_value(spec.json_, variables)


def _extract(spec: ExtractSpec, state: _State) -> None:
    value = _extracted(spec, state.document)
    if spec.parse == "json":
        value = _parsed_json(value)
    state.save(spec.as_, value)


def _extracted(spec: ExtractSpec, document: Any) -> Any:
    if spec.regex is not None:
        return _first_group(spec.regex, document)
    if spec.jsonpath is not None:
        return _first_match(spec.jsonpath, _as_json(document))
    raise _Failure(CSS_UNSUPPORTED)


def _first_group(pattern: str, document: Any) -> str:
    text = document if isinstance(document, str) else json.dumps(document)
    match = re.search(pattern, text)
    if match is None:
        raise _Failure(f"regex {pattern!r} matched nothing")
    return match.group(1)


def _first_match(path: str, document: Any) -> Any:
    matches = _compiled(path).find(document)
    if not matches:
        raise _Failure(f"JSONPath {path} matched nothing")
    return matches[0].value


def _as_json(document: Any) -> Any:
    """A text document is decoded first, so JSONPath can read a JSON response body."""
    return _parsed_json(document) if isinstance(document, str) else document


def _parsed_json(value: Any) -> Any:
    if not isinstance(value, str):
        raise _Failure(f"parse: json needs a string, got {type(value).__name__}")
    try:
        return json.loads(value)
    except json.JSONDecodeError as err:
        raise _Failure(f"not valid JSON: {err}") from None


def _items(spec: ItemsSpec, state: _State) -> list[Any]:
    if spec.jsonpath is None:
        raise _Failure(CSS_UNSUPPORTED)
    return [match.value for match in _compiled(spec.jsonpath).find(_as_json(state.document))]


@lru_cache(maxsize=256)
def _compiled(path: str) -> JSONPath:
    return parse_jsonpath(path)


def _deduped(events: Iterable[Event]) -> list[Event]:
    """Overlapping pages return the same event more than once; keep the first."""
    unique: dict[str, Event] = {}
    for event in events:
        unique.setdefault(event.uid, event)
    return sorted(unique.values(), key=lambda event: event.start)


# ---------------------------------------------------------------------------
# Mapping items to events


def map_item(definition: PipelineDefinition, item: Any, index: int) -> Event | None:
    """Map one item to an event, or None when `skip_if` drops it."""
    fields = definition.map
    try:
        if fields.skip_if is not None and _skipped(fields.skip_if, item):
            return None
        return _event(definition, item)
    except _FieldFailure as err:
        raise MapError(index, err.field, str(err)) from None


class _FieldFailure(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def _skipped(spec: FieldSpec, item: Any) -> bool:
    """Skip when the value equals `equals`; without `equals`, when it's truthy."""
    value = _field_value("skip_if", spec, item)
    return bool(value) if spec.equals is None else value == spec.equals


def _event(definition: PipelineDefinition, item: Any) -> Event:
    fields = definition.map
    times = _times(fields.start, fields.end, fields.date, item)
    values = {
        "title": _required_text("title", fields.title, item),
        "start": times.start,
        "end": times.end,
        "location": _optional_text("location", fields.location, item),
        "description": _optional_text("description", fields.description, item),
        "url": _optional_text("url", fields.url, item),
    }
    return Event(uid=_uid(definition.uid or DEFAULT_UID_FIELDS, values), **values)


def _field_value(name: str, spec: FieldSpec, item: Any) -> Any:
    """The first JSONPath match, refined by `regex` and `strip`; None when nothing matches."""
    if spec.jsonpath is None:
        raise _FieldFailure(name, CSS_UNSUPPORTED)
    matches = _compiled(spec.jsonpath).find(item)
    value = matches[0].value if matches else None
    return _refined(spec, value) if isinstance(value, str) else value


def _refined(spec: FieldSpec, text: str) -> str | None:
    if spec.regex is not None:
        match = re.search(spec.regex, text)
        if match is None:
            return None
        text = match.group(1) if match.re.groups else match.group(0)
    return text.strip() if spec.strip else text


def _required_text(name: str, spec: FieldSpec, item: Any) -> str:
    text = _optional_text(name, spec, item)
    if not text:
        raise _FieldFailure(name, "no value")
    return text


def _optional_text(name: str, spec: FieldSpec | None, item: Any) -> str | None:
    if spec is None:
        return None
    value = _field_value(name, spec, item)
    return None if value is None else str(value)


def _times(
    start: FieldSpec, end: FieldSpec | None, day_spec: FieldSpec | None, item: Any
) -> _Times:
    """Start and end in UTC, from separate fields, a `date` plus times, or one time range."""
    day = _day(day_spec, item) if day_spec is not None else None
    start_text = _text_value("start", start, item)
    end_text = _text_value("end", end, item) if end is not None else None
    if start.time_range_regex is not None:
        start_text, range_end = _split_range(start.time_range_regex, start_text)
        end_text = end_text or range_end
    times = _Times(_datetime("start", start, start_text, day))
    if end_text:
        times.end = _datetime("end", end or start, end_text, day)
    return _with_default_end(times, end, start)


def _text_value(name: str, spec: FieldSpec, item: Any) -> str:
    value = _field_value(name, spec, item)
    if value is None or value == "":
        raise _FieldFailure(name, "no value")
    return str(value)


def _split_range(pattern: str, text: str) -> tuple[str, str | None]:
    """`7:00–8:30 PM` → (`7:00 PM`, `8:30 PM`): groups 1 and 2, sharing a trailing AM/PM."""
    match = re.search(pattern, text)
    if match is None:
        raise _FieldFailure("start", f"time_range_regex matched nothing in {text!r}")
    start, end = match.group(1), match.group(2) if match.re.groups >= 2 else None
    return _shared_meridiem(start, end), end


def _shared_meridiem(start: str, end: str | None) -> str:
    meridiem = re.search(r"\s*([AaPp]\.?[Mm]\.?)\s*$", end or "")
    if meridiem and not re.search(r"[AaPp]\.?[Mm]\.?\s*$", start):
        return f"{start.strip()} {meridiem.group(1)}"
    return start


def _with_default_end(times: _Times, end: FieldSpec | None, start: FieldSpec) -> _Times:
    minutes = (end.default_duration_min if end else None) or start.default_duration_min
    if times.end is None and minutes:
        times.end = times.start + timedelta(minutes=minutes)
    return times


def _day(spec: FieldSpec, item: Any) -> date:
    text = _text_value("date", spec, item)
    parsed = _parsed_datetime(spec, text, None)
    if parsed is None:
        raise _FieldFailure("date", f"can't parse {text!r} as a date")
    return parsed.date()


def _datetime(name: str, spec: FieldSpec, text: str, day: date | None) -> datetime:
    """Parse, attach `tz` (default UTC) when the text has no offset, and convert to UTC."""
    parsed = _parsed_datetime(spec, text, day)
    if parsed is None:
        raise _FieldFailure(name, f"can't parse {text!r} as a date and time")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(spec.tz or "UTC"))
    return parsed.astimezone(UTC)


def _parsed_datetime(spec: FieldSpec, text: str, day: date | None) -> datetime | None:
    """`format` via strptime, else dateparser; a time-only value lands on `day`."""
    if spec.format is None:
        base = datetime.combine(day, time()) if day else None
        return dateparser.parse(text, settings=_dateparser_settings(base))
    try:
        parsed = datetime.strptime(text, spec.format)
    except ValueError:
        return None
    return datetime.combine(day, parsed.timetz()) if day and parsed.year == 1900 else parsed


def _dateparser_settings(base: datetime | None) -> dict[str, Any]:
    return {"RELATIVE_BASE": base} if base else {}


def _uid(names: Iterable[str], values: Mapping[str, Any]) -> str:
    """A stable id from the chosen fields, so re-runs update events instead of duplicating."""
    raw = "\x1f".join(_uid_part(values.get(name)) for name in names)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _uid_part(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# CLI


def main(argv: Sequence[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)
    try:
        events = asyncio.run(_cli_run(args))
    except (AdapterError, OSError, yaml.YAMLError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(_events_json(events) if args.json else _events_table(events))
    return 0


def _arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.adapters.engine", description="Run a pipeline adapter definition."
    )
    parser.add_argument("definition", type=Path, help="YAML or JSON definition file")
    parser.add_argument("params", nargs="*", metavar="key=value", help="definition params")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="lookahead window")
    parser.add_argument("--start", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--allow-private", action="store_true", help="allow fetching private network addresses"
    )
    return parser


async def _cli_run(args: argparse.Namespace) -> list[Event]:
    definition = _load_definition(args.definition)
    params = resolve_params(definition, _param_pairs(args.params))
    limits = FetchLimits(allow_private=args.allow_private)
    async with FetchSession(limits) as session:
        start = args.start or date.today()
        return await run_pipeline(definition, params, session=session, start=start, days=args.days)


def _load_definition(path: Path) -> PipelineDefinition:
    try:
        definition = parse_definition(yaml.safe_load(path.read_text()), builtin=True)
    except ValidationError as err:
        problems = "; ".join(f"{row['loc'] or '(root)'}: {row['msg']}" for row in error_list(err))
        raise AdapterError(f"invalid definition: {problems}") from None
    if not isinstance(definition, PipelineDefinition):
        raise AdapterError(f"{path} is a {definition.kind} definition; this runs pipelines")
    return definition


def _param_pairs(pairs: Sequence[str]) -> dict[str, str]:
    malformed = [pair for pair in pairs if "=" not in pair]
    if malformed:
        raise ParamError(f"params must be key=value, got: {', '.join(malformed)}")
    return dict(pair.split("=", 1) for pair in pairs)


def _events_json(events: Sequence[Event]) -> str:
    return json.dumps([asdict(event) for event in events], indent=2, default=str)


def _events_table(events: Sequence[Event]) -> str:
    rows = [("start (UTC)", "end (UTC)", "title", "location")]
    rows += [_table_row(event) for event in events]
    widths = [max(len(row[col]) for row in rows) for col in range(len(rows[0]))]
    lines = ["  ".join(_padded(row, widths)).rstrip() for row in rows]
    return "\n".join([*lines, f"{len(events)} event(s)"])


def _padded(row: Sequence[str], widths: Sequence[int]) -> list[str]:
    return [cell.ljust(width) for cell, width in zip(row, widths, strict=True)]


def _table_row(event: Event) -> tuple[str, str, str, str]:
    end = f"{event.end:%Y-%m-%d %H:%M}" if event.end else ""
    return f"{event.start:%Y-%m-%d %H:%M}", end, event.title, event.location or ""


if __name__ == "__main__":
    raise SystemExit(main())
