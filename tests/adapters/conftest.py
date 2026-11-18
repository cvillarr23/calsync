import copy

import pytest

UW_EMS = {
    "id": "uw-ems",
    "version": 1,
    "name": "EMS Cloud browse page",
    "kind": "pipeline",
    "params": {"page_url": {"type": "url"}},
    "steps": [
        {"http": {"method": "GET", "url": "{{page_url}}", "follow_redirects": False}},
        {
            "extract": {
                "regex": r"vems\.browse\.CustomBrowseData = (\{.*?\});",
                "as": "browse_data",
                "parse": "json",
            }
        },
        {"paginate": {"window": "lookahead", "step_days": 7, "as": "date"}},
        {
            "http": {
                "method": "POST",
                "url": "{{origin(page_url)}}/web/AnonymousServersApi.aspx/CustomBrowseEvents",
                "json": {"date": "{{date:%Y-%m-%d %H:%M:%S}}", "data": "{{browse_data}}"},
            }
        },
        {"extract": {"jsonpath": "$.d", "parse": "json"}},
        {"items": {"jsonpath": "$.MonthlyBookingResults[*]"}},
    ],
    "map": {
        "title": {"jsonpath": "$.EventName", "strip": True},
        "start": {"jsonpath": "$.GmtStart", "tz": "UTC"},
        "end": {"jsonpath": "$.GmtEnd", "tz": "UTC"},
        "location": {"jsonpath": "$.Location"},
        "skip_if": {"jsonpath": "$.StatusTypeId", "equals": -12},
    },
}

HTML_DEF = {
    "id": "rec-center",
    "version": 1,
    "name": "Rec center schedule",
    "kind": "html",
    "params": {"url": {"type": "url"}},
    "fetch": {"url": "{{url}}"},
    "item": ".event",
    "map": {"title": {"selector": "h3"}, "start": {"selector": "time", "attr": "datetime"}},
}


@pytest.fixture
def uw_ems():
    return copy.deepcopy(UW_EMS)


@pytest.fixture
def html_def():
    return copy.deepcopy(HTML_DEF)


@pytest.fixture
def anyio_backend():
    return "asyncio"
