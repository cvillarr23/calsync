import pytest
from pydantic import ValidationError

from app.adapters.schema import (
    HtmlDefinition,
    PipelineDefinition,
    PythonDefinition,
    error_list,
    parse_definition,
)


def errors_for(data, **kwargs):
    with pytest.raises(ValidationError) as exc:
        parse_definition(data, **kwargs)
    return error_list(exc.value)


def locs(data, **kwargs):
    return [row["loc"] for row in errors_for(data, **kwargs)]


def test_epic_sketch_parses(uw_ems):
    definition = parse_definition(uw_ems)
    assert isinstance(definition, PipelineDefinition)
    assert [step.kind for step in definition.steps] == [
        "http",
        "extract",
        "paginate",
        "http",
        "extract",
        "items",
    ]
    assert definition.steps[3].http.json_["data"] == "{{browse_data}}"
    assert definition.steps[1].extract.as_ == "browse_data"
    assert definition.map.skip_if.equals == -12


def test_html_definition_parses(html_def):
    definition = parse_definition(html_def)
    assert isinstance(definition, HtmlDefinition)
    assert definition.pagination.mode == "none"


def test_unknown_kind_is_rejected(uw_ems):
    uw_ems["kind"] = "scraper"
    assert errors_for(uw_ems) == [
        {"loc": "kind", "msg": "kind must be one of: pipeline, html, python"}
    ]


def test_unknown_key_reports_its_path(uw_ems):
    uw_ems["steps"][0]["http"]["urll"] = "x"
    assert "steps.0.http.urll" in locs(uw_ems)


def test_step_needs_exactly_one_kind(uw_ems):
    uw_ems["steps"][0]["extract"] = {"css": "a"}
    assert "steps.0" in locs(uw_ems)


def test_json_and_form_are_exclusive(uw_ems):
    uw_ems["steps"][3]["http"]["form"] = {"a": "b"}
    assert "steps.3.http" in locs(uw_ems)


def test_regex_needs_capture_group(uw_ems):
    uw_ems["steps"][1]["extract"]["regex"] = "CustomBrowseData"
    rows = errors_for(uw_ems)
    assert rows[0]["loc"] == "steps.1.extract.regex"
    assert "capture group" in rows[0]["msg"]


def test_invalid_regex_and_tz(uw_ems):
    uw_ems["steps"][1]["extract"]["regex"] = "(unclosed"
    uw_ems["map"]["start"]["tz"] = "Mars/Olympus"
    assert locs(uw_ems) == ["steps.1.extract.regex", "map.start.tz"]


def test_unknown_template_variable_reports_step_path(uw_ems):
    uw_ems["steps"][3]["http"]["url"] = "{{origin(page_uri)}}/api"
    rows = errors_for(uw_ems)
    assert rows == [{"loc": "steps.3.http.url", "msg": "unknown variable(s): page_uri"}]


def test_variable_used_before_its_step_defines_it(uw_ems):
    uw_ems["steps"][0]["http"]["url"] = "{{page_url}}?d={{date:%Y}}"
    assert locs(uw_ems) == ["steps.0.http.url"]


def test_template_in_json_body_is_checked(uw_ems):
    uw_ems["steps"][3]["http"]["json"]["data"] = "{{browse}}"
    assert locs(uw_ems) == ["steps.3.http.json"]


def test_malformed_template_is_rejected(uw_ems):
    uw_ems["steps"][0]["http"]["url"] = "{{upper(page_url)}}"
    rows = errors_for(uw_ems)
    assert rows[0]["loc"] == "steps.0.http.url"
    assert "unknown helper" in rows[0]["msg"]


def test_pipeline_needs_one_items_step(uw_ems):
    uw_ems["steps"].pop()
    assert locs(uw_ems) == ["steps"]


def test_uid_must_name_mapped_fields(uw_ems):
    uw_ems["uid"] = ["title", "description"]
    assert locs(uw_ems) == ["uid.1"]


def test_field_needs_one_value_source(uw_ems):
    uw_ems["map"]["title"] = {"jsonpath": "$.a", "selector": "h3"}
    assert locs(uw_ems) == ["map.title"]


def test_param_default_must_match_type(uw_ems):
    uw_ems["params"]["days"] = {"type": "int", "default": "seven"}
    assert locs(uw_ems) == ["params.days"]


def test_bad_param_name(uw_ems):
    uw_ems["params"]["page-url"] = {"type": "url"}
    assert "params.page-url.[key]" in locs(uw_ems)


def test_click_next_needs_headless(html_def):
    html_def["pagination"] = {"mode": "click_next", "selector": ".next", "max_pages": 3}
    assert locs(html_def) == ["pagination.mode"]
    html_def["fetch"]["mode"] = "headless"
    assert parse_definition(html_def).pagination.max_pages == 3


def test_pagination_fields_must_match_mode(html_def):
    html_def["pagination"] = {"mode": "url_template", "selector": ".next"}
    assert locs(html_def) == ["pagination"]


def test_url_template_knows_date(html_def):
    html_def["pagination"] = {
        "mode": "url_template",
        "url_template": "{{url}}?week={{date:%Y-%m-%d}}",
        "step_days": 7,
    }
    assert parse_definition(html_def).pagination.step_days == 7
    html_def["pagination"]["url_template"] = "{{url}}?week={{day}}"
    assert locs(html_def) == ["pagination.url_template"]


PYTHON_DEF = {
    "id": "odd-site",
    "version": 1,
    "name": "Odd site",
    "kind": "python",
    "entrypoint": "app.adapters.builtin.odd:run",
}


def test_python_kind_is_builtin_only():
    assert errors_for(dict(PYTHON_DEF)) == [
        {"loc": "kind", "msg": "the python kind is only available to built-in adapters"}
    ]
    assert isinstance(parse_definition(dict(PYTHON_DEF), builtin=True), PythonDefinition)


def test_python_entrypoint_format():
    assert locs({**PYTHON_DEF, "entrypoint": "os.system"}, builtin=True) == ["entrypoint"]


def test_equals_only_applies_to_skip_if(uw_ems):
    uw_ems["map"]["title"]["equals"] = "x"
    [error] = errors_for(uw_ems)
    assert error["loc"] == "map"
    assert error["msg"].endswith("title: equals only applies to skip_if")
