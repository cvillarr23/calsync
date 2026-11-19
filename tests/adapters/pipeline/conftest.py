import copy

import pytest
import yaml

from app.adapters.schema import parse_definition
from tests.adapters.pipeline import fake_api as fake_api_module

BASE_MAP = {"title": {"jsonpath": "$.t"}, "start": {"jsonpath": "$.s"}}


@pytest.fixture(scope="module")
def fake_api():
    """Base URL of a running fake two-step API; see fake_api.py."""
    httpd, base_url = fake_api_module.serve()
    yield base_url
    httpd.shutdown()


@pytest.fixture
def two_step():
    """The fake API's definition as data, for tests to tweak."""
    return yaml.safe_load(fake_api_module.DEFINITION.read_text())


def unit_definition(field_map=None, **extra):
    """A minimal pipeline definition for testing `map` and params in isolation."""
    data = {
        "id": "unit",
        "version": 1,
        "name": "Unit",
        "kind": "pipeline",
        "steps": [{"http": {"url": "https://example.com/"}}, {"items": {"jsonpath": "$[*]"}}],
        "map": field_map or copy.deepcopy(BASE_MAP),
        **extra,
    }
    return parse_definition(data)
