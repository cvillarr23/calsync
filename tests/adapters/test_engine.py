import copy
import json
from datetime import UTC, date, datetime

import pytest
import yaml

from app.adapters.engine import (
    MapError,
    ParamError,
    StepError,
    main,
    map_item,
    resolve_params,
    run_pipeline,
)
from app.adapters.schema import parse_definition
from tests.adapters.fake_api import DEFINITION, fetch_session

pytestmark = pytest.mark.anyio

DECEMBER = date(2026, 12, 1)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def two_step():
    return yaml.safe_load(DEFINITION.read_text())


async def run(data, params, days=21):
    definition = parse_definition(data)
    async with fetch_session() as session:
        return await run_pipeline(
            definition,
            resolve_params(definition, params),
            session=session,
            start=DECEMBER,
            days=days,
        )


async def test_two_step_api_yields_expected_events(fake_api, two_step):
    events = await run(two_step, {"page_url": f"{fake_api}/calendar"})
    assert [(e.title, e.start, e.end, e.location) for e in events] == [
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


# --- map -------------------------------------------------------------------


def definition_with_map(field_map, **extra):
    data = {
        "id": "unit",
        "version": 1,
        "name": "Unit",
        "kind": "pipeline",
        "steps": [{"http": {"url": "https://example.com/"}}, {"items": {"jsonpath": "$[*]"}}],
        "map": field_map,
        **extra,
    }
    return parse_definition(data)


BASE_MAP = {"title": {"jsonpath": "$.t"}, "start": {"jsonpath": "$.s"}}


def mapped(item, **fields):
    return map_item(definition_with_map({**copy.deepcopy(BASE_MAP), **fields}), item, 0)


def test_skip_if_without_equals_skips_truthy_values():
    skip = {"skip_if": {"jsonpath": "$.cancelled"}}
    assert mapped({"t": "A", "s": "2026-12-01T10:00", "cancelled": True}, **skip) is None
    assert mapped({"t": "A", "s": "2026-12-01T10:00", "cancelled": 0}, **skip) is not None
    assert mapped({"t": "A", "s": "2026-12-01T10:00"}, **skip) is not None


def test_tz_applies_to_naive_times_and_converts_to_utc():
    event = mapped(
        {"t": "A", "s": "2026-12-01 10:00"}, start={"jsonpath": "$.s", "tz": "America/Los_Angeles"}
    )
    assert event.start == utc(2026, 12, 1, 18)


def test_explicit_offset_wins_over_tz():
    event = mapped(
        {"t": "A", "s": "2026-12-01T10:00:00+01:00"},
        start={"jsonpath": "$.s", "tz": "America/Los_Angeles"},
    )
    assert event.start == utc(2026, 12, 1, 9)


def test_format_and_default_duration():
    start = {"jsonpath": "$.s", "format": "%d/%m/%Y %H.%M", "default_duration_min": 45}
    event = mapped({"t": "A", "s": "03/12/2026 09.30"}, start=start)
    assert (event.start, event.end) == (utc(2026, 12, 3, 9, 30), utc(2026, 12, 3, 10, 15))


def test_date_field_and_time_range():
    start = {"jsonpath": "$.when", "time_range_regex": r"(\S+)\s*[–-]\s*(.+)"}
    event = mapped(
        {"t": "A", "day": "Thursday, December 3, 2026", "when": "7:00–8:30 PM"},
        start=start,
        date={"jsonpath": "$.day"},
    )
    assert (event.start, event.end) == (utc(2026, 12, 3, 19), utc(2026, 12, 3, 20, 30))


def test_regex_and_strip_refine_text():
    title = {"jsonpath": "$.t", "regex": r"Event: (.*)", "strip": True}
    assert mapped({"t": "Event:  Skate  ", "s": "2026-12-01T10:00"}, title=title).title == "Skate"


def test_uid_uses_chosen_fields():
    definition = definition_with_map(copy.deepcopy(BASE_MAP), uid=["start"])
    first = map_item(definition, {"t": "A", "s": "2026-12-01T10:00"}, 0)
    renamed = map_item(definition, {"t": "B", "s": "2026-12-01T10:00"}, 0)
    assert first.uid == renamed.uid
    default_a = mapped({"t": "A", "s": "2026-12-01T10:00"})
    default_b = mapped({"t": "B", "s": "2026-12-01T10:00"})
    assert default_a.uid != default_b.uid


def test_unparseable_start_names_item_and_field():
    with pytest.raises(MapError, match=r"^item 0, map\.start: can't parse 'soon-ish\?'"):
        mapped({"t": "A", "s": "soon-ish?"})


def test_missing_title_is_an_error():
    with pytest.raises(MapError, match=r"map\.title: no value"):
        mapped({"s": "2026-12-01T10:00"})


# --- params and CLI ----------------------------------------------------------


def test_resolve_params_defaults_and_coercion():
    definition = definition_with_map(
        copy.deepcopy(BASE_MAP),
        params={"room": {"type": "int", "default": 3}, "name": {"type": "string"}},
    )
    assert resolve_params(definition, {"name": "x", "room": "7"}) == {"room": 7, "name": "x"}
    assert resolve_params(definition, {"name": "x"}) == {"room": 3, "name": "x"}
    with pytest.raises(ParamError, match="missing param: name"):
        resolve_params(definition, {})
    with pytest.raises(ParamError, match="unknown param"):
        resolve_params(definition, {"name": "x", "other": "y"})
    with pytest.raises(ParamError, match="must be an int"):
        resolve_params(definition, {"name": "x", "room": "seven"})


def cli(fake_api, *extra):
    port = fake_api.rsplit(":", 1)[1]
    page_url = f"page_url=http://127.0.0.1:{port}/calendar"
    args = [str(DEFINITION), page_url, "--start", "2026-12-01", "--days", "21", "--allow-private"]
    return main([*args, *extra])


def test_cli_prints_a_table(fake_api, capsys):
    assert cli(fake_api) == 0
    out = capsys.readouterr().out
    assert "2026-12-02 18:00  2026-12-02 19:30  Public Skate" in out
    assert out.strip().endswith("3 event(s)")


def test_cli_prints_json(fake_api, capsys):
    assert cli(fake_api, "--json") == 0
    events = json.loads(capsys.readouterr().out)
    assert [e["title"] for e in events] == ["Public Skate", "Stick & Puck", "Figure Skating"]
    assert events[0]["start"] == "2026-12-02 18:00:00+00:00"


def test_cli_reports_errors(fake_api, capsys):
    port = fake_api.rsplit(":", 1)[1]
    args = [str(DEFINITION), f"page_url=http://127.0.0.1:{port}/calendar"]
    assert main(args) == 1
    assert "step 0 (http)" in capsys.readouterr().err
