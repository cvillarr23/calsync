import copy
from datetime import timedelta

import pytest
import yaml

from app.adapters.events import ScrapedEvent
from app.db.base import utcnow
from tests.adapters.conftest import HTML_DEF
from tests.adapters.html.page_server import AllowTestHost, fake_resolver, serve_pages
from tests.support import FakeRunner


def soon(uid, title, days, location=None):
    start = utcnow() + timedelta(days=days)
    return ScrapedEvent(uid, title, start, start + timedelta(hours=1), location=location)


RINK_EVENTS = [
    soon("a", "Public Skate", 1, "Main rink"),
    soon("b", "Public Skate Theme Night: EDM", 2),
    soon("c", "Drop-in Hockey", 3),
]


@pytest.fixture
def runner(client):
    fake = FakeRunner(events=RINK_EVENTS)
    client.app.state.runner = fake
    return fake


@pytest.fixture
def adapter(client):
    response = client.post("/api/adapters", json={**HTML_DEF, "match_hosts": ["rink.example"]})
    assert response.status_code == 201, response.text
    return response.json()


def source_form(**overrides):
    form = {
        "name": "Rink",
        "adapter_id": "rec-center",
        "param.url": "https://rink.example/schedule",
        "include_kw": "public skate",
        "exclude_kw": "theme night",
        "interval_min": "360",
        "lookahead_days": "30",
        "enabled": "on",
    }
    return {**form, **overrides}


@pytest.fixture(scope="module")
def pages():
    with serve_pages() as base:
        yield base


@pytest.fixture
def local_pages(client, pages):
    """Let test runs reach the local page server through the SSRF guard."""
    client.app.state.fetch_options = {"guard": AllowTestHost(False), "resolver": fake_resolver}
    return pages


def html_yaml(**changes):
    data = copy.deepcopy(HTML_DEF)
    data["map"] = {
        "title": {"selector": "h3", "strip": True},
        "start": {"selector": "time.start", "attr": "datetime"},
        "end": {"selector": "time.end", "attr": "datetime"},
        "location": {"selector": ".where"},
    }
    data.update(changes)
    return "# rink page\n" + yaml.safe_dump(data, sort_keys=False)
