from datetime import UTC, datetime

import pytest

from app.adapters.events import ENGINES, AdapterRunError, default_runner
from app.adapters.fetch import FetchLimits
from app.adapters.pipeline import PipelineEngine
from app.adapters.schema import parse_definition
from tests.adapters.conftest import HTML_DEF

pytestmark = pytest.mark.anyio


async def test_engine_turns_the_sync_window_into_pages(fake_api, two_step):
    """Pages run from the window's first day; events outside the window are dropped."""
    port = fake_api.rsplit(":", 1)[1]
    two_step["params"]["page_url"]["default"] = f"http://127.0.0.1:{port}/calendar"
    runner = PipelineEngine(FetchLimits(allow_private=True))
    start = datetime(2026, 12, 1, 15, tzinfo=UTC)
    end = datetime(2026, 12, 10, tzinfo=UTC)
    events = await runner(parse_definition(two_step), {}, start, end)
    assert [e.title for e in events] == ["Public Skate", "Stick & Puck"]


async def test_engine_rejects_other_kinds():
    runner = PipelineEngine(FetchLimits())
    with pytest.raises(AdapterRunError, match="can't run a html definition"):
        await runner(parse_definition(HTML_DEF), {}, datetime.now(UTC), datetime.now(UTC))


async def test_engine_fails_when_no_item_can_be_read(fake_api, two_step):
    """Syncing an empty calendar would delete every event; report why nothing was read."""
    port = fake_api.rsplit(":", 1)[1]
    two_step["params"]["page_url"]["default"] = f"http://127.0.0.1:{port}/calendar"
    two_step["map"]["start"]["jsonpath"] = "$.Missing"
    runner = PipelineEngine(FetchLimits(allow_private=True))
    start, end = datetime(2026, 12, 1, tzinfo=UTC), datetime(2026, 12, 9, tzinfo=UTC)
    with pytest.raises(AdapterRunError, match=r"no event could be read: item 0: start: .*more\)"):
        await runner(parse_definition(two_step), {}, start, end)


def test_create_app_registers_the_engine(client):
    assert isinstance(ENGINES["pipeline"], PipelineEngine)


async def test_default_runner_runs_pipelines_once_the_app_registered_them(
    client, fake_api, two_step
):
    """`create_app` registers the engine with the configured fetch limits."""
    port = fake_api.rsplit(":", 1)[1]
    two_step["params"]["page_url"]["default"] = f"http://127.0.0.1:{port}/calendar"
    with pytest.raises(AdapterRunError, match=r"step 0 \(http\).*non-public address"):
        await default_runner(parse_definition(two_step), {}, datetime.now(UTC), datetime.now(UTC))
