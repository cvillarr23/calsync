from datetime import UTC, date, datetime, timedelta

import pytest

from app.adapters.mappers import Window
from app.adapters.pipeline import StepError, run_pipeline
from app.adapters.schema import parse_definition
from tests.adapters.pipeline.fake_api import fetch_session

pytestmark = pytest.mark.anyio

DECEMBER = date(2026, 12, 1)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


async def run(data, params, days=21):
    """Run over `days` dates from 1 December; the result's events."""
    window = Window(start=DECEMBER, end=DECEMBER + timedelta(days=days - 1))
    async with fetch_session() as session:
        result = await run_pipeline(parse_definition(data), params, window, session=session)
    return result.events


async def test_two_step_api_yields_expected_events(fake_api, two_step):
    events = await run(two_step, {"page_url": f"{fake_api}/calendar"})
    assert [(e.title, e.start_utc, e.end_utc, e.location) for e in events] == [
        ("Public Skate", utc(2026, 12, 2, 18), utc(2026, 12, 2, 19, 30), "Main Rink"),
        ("Stick & Puck", utc(2026, 12, 9, 12), utc(2026, 12, 9, 13), "Main Rink"),
        ("Figure Skating", utc(2026, 12, 16, 7), utc(2026, 12, 16, 8), "Studio Rink"),
    ]


async def test_overlapping_pages_are_deduped_by_uid(fake_api, two_step):
    """Each 7-day page returns 14 days, so Dec 9 and Dec 16 arrive twice."""
    events = await run(two_step, {"page_url": f"{fake_api}/calendar"})
    assert len({e.uid for e in events}) == len(events) == 3


async def test_following_the_redirect_loses_the_embedded_object(fake_api, two_step):
    two_step["steps"][0]["http"]["follow_redirects"] = True
    with pytest.raises(StepError, match=r"^step 1 \(extract\): regex .* matched nothing") as exc:
        await run(two_step, {"page_url": f"{fake_api}/calendar"})
    assert (exc.value.index, exc.value.kind) == (1, "extract")


async def test_http_error_names_the_step(fake_api, two_step):
    two_step["steps"][3]["http"]["url"] = "{{origin(page_url)}}/api/broken"
    with pytest.raises(StepError, match=r"^step 3 \(http\): POST .*/api/broken returned HTTP 500"):
        await run(two_step, {"page_url": f"{fake_api}/calendar"})


async def test_css_steps_are_not_supported_yet(fake_api, two_step):
    two_step["steps"][5] = {"items": {"css": ".event"}}
    with pytest.raises(StepError, match=r"^step 5 \(items\): css is not supported"):
        await run(two_step, {"page_url": f"{fake_api}/calendar"})


async def test_pipeline_without_paginate_runs_once(fake_api, two_step):
    del two_step["steps"][2]
    two_step["steps"][2]["http"]["json"]["date"] = "2026-12-08 00:00:00"
    events = await run(two_step, {"page_url": f"{fake_api}/calendar"})
    assert [e.title for e in events] == ["Stick & Puck", "Figure Skating"]
