from datetime import date, datetime

import pytest

from app.adapters import template
from app.adapters.template import TemplateError


def test_renders_plain_variables():
    assert template.render("{{a}}-{{ b }}", {"a": "x", "b": 2}) == "x-2"


def test_origin_helper():
    ctx = {"page_url": "https://ems.example.edu:8443/web/Browse.aspx?id=1"}
    assert template.render("{{origin(page_url)}}/api", ctx) == "https://ems.example.edu:8443/api"


def test_origin_rejects_relative_url():
    with pytest.raises(TemplateError, match="absolute URL"):
        template.render("{{origin(u)}}", {"u": "/relative"})


def test_date_format():
    ctx = {"date": datetime(2026, 11, 18, 9, 30)}
    assert template.render("{{date:%Y-%m-%d %H:%M:%S}}", ctx) == "2026-11-18 09:30:00"


def test_date_format_needs_a_date():
    with pytest.raises(TemplateError, match="not a date"):
        template.render("{{x:%Y}}", {"x": "2026"})


def test_objects_interpolate_as_json_and_dates_as_iso():
    ctx = {"obj": {"a": [1, 2]}, "d": date(2026, 1, 2)}
    assert template.render("x={{obj}} d={{d}}", ctx) == 'x={"a":[1,2]} d=2026-01-02'


def test_render_value_embeds_raw_objects():
    body = {"date": "{{d:%Y}}", "data": "{{obj}}", "n": 3, "list": ["{{obj}}", "k={{d}}"]}
    ctx = {"obj": {"RoomId": 5}, "d": date(2026, 1, 2)}
    assert template.render_value(body, ctx) == {
        "date": "2026",
        "data": {"RoomId": 5},
        "n": 3,
        "list": [{"RoomId": 5}, "k=2026-01-02"],
    }


def test_names_and_check():
    text = "{{origin(page_url)}}/{{date:%Y}}"
    assert template.names(text) == {"page_url", "date"}
    template.check(text, {"page_url", "date"})
    with pytest.raises(TemplateError, match="unknown variable.*date"):
        template.check(text, {"page_url"})


def test_unknown_variable_at_render():
    with pytest.raises(TemplateError, match="unknown variable: missing"):
        template.render("{{missing}}", {})


@pytest.mark.parametrize(
    "text",
    [
        "{{upper(x)}}",
        "{{__import__('os')}}",
        "{{x.__class__}}",
        "{{x[0]}}",
        "{{x + 1}}",
        "{{origin(x, y)}}",
        "{{}}",
        "{{x",
        "x}}",
        "{{x|upper}}",
    ],
)
def test_refuses_anything_outside_the_whitelist(text):
    with pytest.raises(TemplateError):
        template.render(text, {"x": "https://a.example"})


def test_unknown_helper_names_the_whitelist():
    with pytest.raises(TemplateError, match="unknown helper upper.*allowed: origin"):
        template.parse("{{upper(x)}}")
