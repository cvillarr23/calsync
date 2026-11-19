import pytest

from app.adapters.pipeline import ParamError, resolve_params
from tests.adapters.pipeline.conftest import unit_definition


@pytest.fixture
def definition():
    return unit_definition(
        params={"room": {"type": "int", "default": 3}, "name": {"type": "string"}}
    )


def test_defaults_and_coercion(definition):
    assert resolve_params(definition, {"name": "x", "room": "7"}) == {"room": 7, "name": "x"}
    assert resolve_params(definition, {"name": "x"}) == {"room": 3, "name": "x"}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "missing param: name"),
        ({"name": "x", "other": "y"}, "unknown param"),
        ({"name": "x", "room": "seven"}, "must be an int"),
    ],
)
def test_bad_params(definition, raw, message):
    with pytest.raises(ParamError, match=message):
        resolve_params(definition, raw)
