"""Start and end times: dates, formats, time ranges, time zones and default durations."""

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import dateparser

from app.adapters.mappers.errors import FieldFailure
from app.adapters.mappers.window import Window
from app.adapters.schema import FieldMap, FieldSpec

_DAY_DIRECTIVES = re.compile(r"%[djxcaAuwUW]")
_YEAR_DIRECTIVES = re.compile(r"%[yYGxc]")


def event_times(
    field_map: FieldMap, values: dict[str, Any], window: Window
) -> tuple[datetime, datetime | None]:
    """Start and end in UTC, from start/end/date fields, a time range and a default duration."""
    start_text, end_text = str(values["start"]), text_or_none(values["end"])
    if field_map.start.time_range_regex:
        start_text, ranged_end = _split_range(field_map.start.time_range_regex, start_text)
        end_text = end_text or ranged_end
    day = _parse_date(field_map.date, values["date"], window)
    local_start = _parse_when(field_map.start, start_text, day, window, "start")
    start = _to_utc(local_start, _tz(field_map.start, field_map.date))
    end_spec = field_map.end or field_map.start
    end_tz = _tz(field_map.end, field_map.start, field_map.date)
    end = _end(end_spec, end_text, local_start.date(), window, end_tz)
    return start, _end_after_start(start, end, _duration(field_map))


def text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _split_range(pattern: str, text: str) -> tuple[str, str | None]:
    """`7:00–8:30 PM` → (`7:00 PM`, `8:30 PM`), using groups `start`/`end` or 1 and 2.

    A trailing am/pm on the end applies to the start too, when the start has none.
    """
    match = re.search(pattern, text)
    if match is None:
        raise FieldFailure("start", f"time_range_regex {pattern!r} didn't match {text!r}")
    named = match.groupdict()
    if "start" in named:
        start, end = named["start"], named.get("end")
    else:
        start, end = match.group(1), match.group(2) if match.re.groups > 1 else None
    return _shared_meridiem(start.strip(), end.strip() if end else None), end


def _shared_meridiem(start: str, end: str | None) -> str:
    meridiem = re.search(r"\s*([ap]\.?m\.?)$", end or "", re.IGNORECASE)
    if meridiem and not re.search(r"[ap]\.?m\.?$", start, re.IGNORECASE):
        return f"{start} {meridiem.group(1)}"
    return start


def _parse_date(spec: FieldSpec | None, value: Any, window: Window) -> date | None:
    if spec is None or value is None:
        return None
    return _parse_when(spec, str(value), None, window, "date").date()


def _parse_when(
    spec: FieldSpec, text: str, day: date | None, window: Window, field: str
) -> datetime:
    """Parse with `format` when given, else with dateparser.

    A time-only value takes its day from the `date` field (or the window start);
    a year-less value takes the year that puts it nearest after the window start.
    """
    if spec.format:
        return _strptime(spec.format, text, day, window, field)
    base = datetime.combine(day, time()) if day else window.base
    settings = {"RELATIVE_BASE": base, "PREFER_DATES_FROM": "future"}
    parsed = dateparser.parse(text, settings=settings)
    if parsed is None:
        raise FieldFailure(field, f"can't read a date or time from {text!r}")
    return parsed


def _strptime(fmt: str, text: str, day: date | None, window: Window, field: str) -> datetime:
    try:
        parsed = datetime.strptime(text, fmt)
    except ValueError:
        raise FieldFailure(field, f"{text!r} doesn't match format {fmt!r}") from None
    if not _DAY_DIRECTIVES.search(fmt):
        return datetime.combine(day or window.start, parsed.timetz())
    if not _YEAR_DIRECTIVES.search(fmt):
        return _nearest_year(parsed, window)
    return parsed


def _nearest_year(parsed: datetime, window: Window) -> datetime:
    """`Nov 2` read in late December means next November, not last."""
    candidate = parsed.replace(year=window.start.year)
    if candidate < window.base - timedelta(days=180):
        candidate = candidate.replace(year=window.start.year + 1)
    return candidate


def _tz(*specs: FieldSpec | None) -> str:
    """The first `tz` set on the given fields, else UTC."""
    return next((spec.tz for spec in specs if spec is not None and spec.tz), "UTC")


def _to_utc(when: datetime, tz: str) -> datetime:
    """Naive times are local to `tz`; times that carry an offset keep it."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(tz))
    return when.astimezone(UTC)


def _end(
    spec: FieldSpec, text: str | None, day: date | None, window: Window, tz: str
) -> datetime | None:
    if text is None:
        return None
    return _to_utc(_parse_when(spec, text, day, window, "end"), tz)


def _duration(field_map: FieldMap) -> timedelta | None:
    for spec in (field_map.end, field_map.start):
        if spec is not None and spec.default_duration_min:
            return timedelta(minutes=spec.default_duration_min)
    return None


def _end_after_start(
    start: datetime, end: datetime | None, duration: timedelta | None
) -> datetime | None:
    """An end at or before the start crossed midnight; a missing end uses the default duration."""
    if end is None:
        return start + duration if duration else None
    if end <= start:
        end += timedelta(days=1)
    if end <= start:
        raise FieldFailure("end", f"end {end.isoformat()} is before start {start.isoformat()}")
    return end
