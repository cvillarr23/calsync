"""Headless mode against JS-built pages served locally; skipped when Chromium is missing."""

from datetime import UTC, date, datetime

import pytest

from app.adapters.fetch import BlockedAddress, FetchLimits, PageLimitExceeded
from app.adapters.html import run_html
from app.adapters.mappers import Window
from app.adapters.schema import parse_definition
from tests.adapters.html.page_server import AllowTestHost, PageHandler, fake_resolver, serve_pages

pytestmark = pytest.mark.anyio

WINDOW = Window(start=date(2026, 10, 28), end=date(2026, 11, 27))

APP_DEF = {
    "id": "js-rink",
    "version": 1,
    "name": "JS-built schedule",
    "kind": "html",
    "params": {"url": {"type": "url"}},
    "fetch": {"url": "{{url}}", "mode": "headless", "wait_for": ".event"},
    "item": ".event",
    "map": {
        "title": {"selector": "h3"},
        "start": {"selector": "time", "attr": "datetime"},
    },
}


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def chromium():
    """Skip the module unless Playwright can launch Chromium here."""
    playwright = pytest.importorskip("playwright.async_api")
    try:
        async with playwright.async_playwright() as p:
            browser = await p.chromium.launch()
            await browser.close()
    except playwright.Error as err:
        pytest.skip(f"headless Chromium unavailable: {err.message.splitlines()[0]}")


@pytest.fixture(scope="module")
def server():
    with serve_pages() as url:
        yield url


async def run(data, url, limits=None):
    return await run_html(
        parse_definition(data),
        {"url": url},
        WINDOW,
        limits=limits or FetchLimits(timeout_s=20),
        guard=AllowTestHost(),
        resolver=fake_resolver,
    )


def titles(result):
    return [event.title for event in result.events]


async def test_renders_js_built_page(chromium, server):
    result = await run(APP_DEF, f"{server}/app.html")
    assert titles(result) == ["Public Skate", "Stick and Puck"]
    assert result.events[0].start_utc == datetime(2026, 11, 21, 19, 0, tzinfo=UTC)


async def test_static_mode_sees_no_events_on_the_same_page(server):
    data = {**APP_DEF, "fetch": {"url": "{{url}}"}}
    assert titles(await run(data, f"{server}/app.html")) == []


async def test_click_next_until_disabled(chromium, server):
    data = {**APP_DEF, "pagination": {"mode": "click_next", "selector": "#next", "max_pages": 5}}
    result = await run(data, f"{server}/pager.html")
    assert titles(result) == ["Week one skate", "Week two skate", "Week three skate"]


async def test_click_next_stops_at_max_pages(chromium, server):
    data = {**APP_DEF, "pagination": {"mode": "click_next", "selector": "#next", "max_pages": 2}}
    result = await run(data, f"{server}/pager.html")
    assert titles(result) == ["Week one skate", "Week two skate"]


async def test_private_subresources_are_blocked_and_page_still_renders(chromium, server):
    data = {
        **APP_DEF,
        "fetch": {"url": "{{url}}", "mode": "headless", "wait_for": ".event + .event"},
    }
    result = await run(data, f"{server}/leaky.html")
    assert titles(result) == ["Static Skate", "After Block"]


async def test_private_main_document_fails_the_run(chromium):
    with pytest.raises(BlockedAddress):
        await run(APP_DEF, "http://10.0.0.1/schedule.html")


async def test_subresources_count_against_the_page_budget(chromium, server):
    PageHandler.requests.clear()
    with pytest.raises(PageLimitExceeded):
        await run(APP_DEF, f"{server}/busy.html", FetchLimits(timeout_s=20, max_pages=3))
