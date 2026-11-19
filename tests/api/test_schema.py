import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.main import create_app
from app.settings import load_settings


@pytest.fixture
def schema(required_env):
    response = TestClient(create_app(load_settings())).get("/schema/adapter.json")
    assert response.status_code == 200
    return response.json()


def test_schema_is_valid_json_schema(schema):
    Draft202012Validator.check_schema(schema)


def test_definitions_validate_against_schema(schema, uw_ems, html_def):
    validator = Draft202012Validator(schema)
    validator.validate(uw_ems)
    validator.validate(html_def)


def test_schema_rejects_unknown_keys(schema, uw_ems):
    uw_ems["steps"][0]["http"]["urll"] = "x"
    assert not Draft202012Validator(schema).is_valid(uw_ems)
