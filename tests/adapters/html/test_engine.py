from datetime import UTC, datetime

import pytest

from app.adapters.events import ENGINES, AdapterRunError
from app.adapters.fetch import FetchLimits
from app.adapters.html import HtmlEngine
from app.adapters.schema import parse_definition
from tests.adapters.html.page_server import AllowTestHost, fake_resolver, serve_pages
from tests.adapters.html.test_run import LIST_DEF

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def server():
    with serve_pages() as url:
        yield url


def engine():
    return HtmlEngine(FetchLimits(), guard=AllowTestHost(), resolver=fake_resolver)


async def test_returns_only_events_in_the_window(server):
    events = await engine()(
        parse_definition(LIST_DEF),
        {"url": f"{server}/list.html"},
        datetime(2026, 11, 22, 0, 0, tzinfo=UTC),
        datetime(2026, 12, 22, 0, 0, tzinfo=UTC),
    )
    assert [e.title for e in events] == ["Stick and Puck"]


async def test_fetch_failure_is_an_adapter_run_error(server):
    with pytest.raises(AdapterRunError, match="HTTP 404"):
        await engine()(
            parse_definition(LIST_DEF),
            {"url": f"{server}/missing.html"},
            datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 12, 1, tzinfo=UTC),
        )


async def test_every_item_failing_is_an_adapter_run_error(server):
    data = {**LIST_DEF, "map": {**LIST_DEF["map"], "title": {"selector": ".nope"}}}
    with pytest.raises(AdapterRunError, match=r"no event could be read: .*title: selector"):
        await engine()(
            parse_definition(data),
            {"url": f"{server}/list.html"},
            datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 12, 1, tzinfo=UTC),
        )


def test_app_registers_the_html_engine(client):
    assert isinstance(ENGINES["html"], HtmlEngine)
