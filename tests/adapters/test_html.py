from datetime import UTC, date, datetime

import pytest

from app.adapters.fetch import BlockedAddress, FetchError, FetchLimits
from app.adapters.html import run_html
from app.adapters.mapping import Window
from app.adapters.schema import parse_definition
from tests.adapters.page_server import AllowTestHost, PageHandler, fake_resolver, serve_pages

pytestmark = pytest.mark.anyio

WINDOW = Window(start=date(2026, 10, 28), end=date(2026, 11, 27))

LIST_DEF = {
    "id": "rink-list",
    "version": 1,
    "name": "Rink list page",
    "kind": "html",
    "params": {"url": {"type": "url"}},
    "fetch": {"url": "{{url}}"},
    "item": "li.event",
    "map": {
        "title": {"selector": "h3"},
        "start": {"selector": "time.start", "attr": "datetime"},
        "end": {"selector": "time.end", "attr": "datetime"},
        "location": {"selector": ".where"},
        "url": {"selector": "a", "attr": "href"},
        "skip_if": {"selector": ".status", "equals": "cancelled"},
    },
}

WEEK_DEF = {
    "id": "rink-week",
    "version": 1,
    "name": "Rink week grid",
    "kind": "html",
    "params": {"url": {"type": "url"}},
    "fetch": {"url": "{{url}}"},
    "item": "tr.slot",
    "map": {
        "title": {"selector": ".name"},
        "date": {"from_context": "tr.day th"},
        "start": {
            "selector": ".time",
            "tz": "America/Chicago",
            "time_range_regex": r"(.+?)\s*[–-]\s*(.+)",
        },
    },
}


@pytest.fixture(scope="module")
def server():
    with serve_pages() as url:
        yield url


async def run(data, params, **kwargs):
    kwargs.setdefault("limits", FetchLimits())
    kwargs.setdefault("guard", AllowTestHost())
    return await run_html(parse_definition(data), params, WINDOW, resolver=fake_resolver, **kwargs)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


async def test_list_page(server):
    result = await run(LIST_DEF, {"url": f"{server}/list.html"})
    rows = [(e.title, e.start, e.end, e.location, e.url) for e in result.events]
    assert rows == [
        (
            "Public Skate",
            utc(2026, 11, 21, 19, 0),
            utc(2026, 11, 21, 20, 30),
            "Main Rink",
            f"{server}/events/101",
        ),
        (
            "Stick and Puck",
            utc(2026, 11, 22, 15, 15),
            utc(2026, 11, 22, 16, 15),
            "Rink B",
            f"{server}/events/102",
        ),
    ]


async def test_missing_field_is_reported_not_raised(server):
    result = await run(LIST_DEF, {"url": f"{server}/list.html"})
    [problem] = result.problems
    assert (problem.item, problem.field) == (3, "start")
    assert problem.msg == "selector 'time.start' attr 'datetime' matched nothing"
    assert problem.page == f"{server}/list.html"


async def test_week_grid_dates_from_context_across_dst(server):
    result = await run(WEEK_DEF, {"url": f"{server}/week.html"})
    rows = [(e.title, e.start, e.end) for e in result.events]
    assert rows == [
        # Saturday is still CDT (UTC-5).
        ("Halloween Skate", utc(2026, 11, 1, 0, 0), utc(2026, 11, 1, 1, 30)),
        # Crosses midnight: the end rolls to the next day.
        ("Late Skate", utc(2026, 11, 1, 4, 0), utc(2026, 11, 1, 5, 30)),
        # DST ends at 2 AM on Sunday 1 November; the evening is CST (UTC-6).
        ("Sunday Skate", utc(2026, 11, 2, 1, 0), utc(2026, 11, 2, 2, 30)),
        ("Early Skate", utc(2026, 11, 2, 12, 0), utc(2026, 11, 2, 13, 0)),
    ]
    assert result.problems == []


async def test_url_template_pages_across_window_and_dedupes(server):
    data = {**LIST_DEF, "fetch": {}}
    data["pagination"] = {
        "mode": "url_template",
        "url_template": "{{url}}?week={{date:%Y-%m-%d}}",
        "step_days": 14,
    }
    PageHandler.requests.clear()
    result = await run(data, {"url": f"{server}/list.html"})
    assert PageHandler.requests == [
        "/list.html?week=2026-10-28",
        "/list.html?week=2026-11-11",
        "/list.html?week=2026-11-25",
    ]
    assert [e.title for e in result.events] == ["Public Skate", "Stick and Puck"]


async def test_format_and_default_duration(server):
    data = {**LIST_DEF, "map": dict(LIST_DEF["map"])}
    data["map"]["start"] = {
        "selector": "time.start",
        "regex": r"^\w+ (.+)$",
        "format": "%b %d, %I:%M %p",
        "tz": "America/Chicago",
        "default_duration_min": 45,
    }
    del data["map"]["end"]
    result = await run(data, {"url": f"{server}/list.html"})
    first = result.events[0]
    assert (first.start, first.end) == (utc(2026, 11, 21, 19, 0), utc(2026, 11, 21, 19, 45))


async def test_uid_is_stable_and_follows_uid_fields(server):
    first = await run(LIST_DEF, {"url": f"{server}/list.html"})
    again = await run(LIST_DEF, {"url": f"{server}/list.html"})
    by_title = await run({**LIST_DEF, "uid": ["title"]}, {"url": f"{server}/list.html"})
    assert [e.uid for e in first.events] == [e.uid for e in again.events]
    assert first.events[0].uid != by_title.events[0].uid


async def test_http_error_fails_the_run(server):
    with pytest.raises(FetchError, match="HTTP 404"):
        await run(LIST_DEF, {"url": f"{server}/missing.html"})


async def test_guard_applies(server):
    with pytest.raises(BlockedAddress):
        await run(LIST_DEF, {"url": "http://127.0.0.1:1/list.html"}, guard=None)
