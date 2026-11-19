import copy

import pytest
import yaml

from tests.adapters.conftest import HTML_DEF
from tests.support import PYTHON_DEF


@pytest.fixture
def adapter(client):
    response = client.post("/api/adapters", json=HTML_DEF)
    assert response.status_code == 201, response.text
    return response.json()


def new_source(**overrides):
    body = {
        "name": "Rink",
        "adapter_id": "rec-center",
        "params": {"url": "https://rink.example/schedule"},
        "include_kw": ["public skate"],
        "exclude_kw": ["theme night"],
    }
    return {**body, **overrides}


def test_create_adapter_from_json(adapter):
    assert adapter["id"] == "rec-center"
    assert adapter["builtin"] is False
    assert adapter["definition"]["item"] == ".event"
    assert yaml.safe_load(adapter["yaml"])["id"] == "rec-center"


def test_create_adapter_from_yaml_keeps_text(client):
    text = "# my rink\n" + yaml.safe_dump(HTML_DEF)
    response = client.post(
        "/api/adapters", content=text, headers={"content-type": "application/yaml"}
    )
    assert response.status_code == 201
    assert client.get("/api/adapters/rec-center").json()["yaml"] == text


def test_list_adapters(client, adapter):
    assert client.get("/api/adapters").json() == [
        {
            "id": "rec-center",
            "name": "Rec center schedule",
            "kind": "html",
            "version": 1,
            "builtin": False,
        }
    ]


def test_invalid_definition_gives_field_errors(client):
    bad = copy.deepcopy(HTML_DEF)
    bad["fetch"]["url"] = "{{nope}}"
    response = client.post("/api/adapters", json=bad)
    assert response.status_code == 422
    assert response.json()["detail"] == [{"loc": "fetch.url", "msg": "unknown variable(s): nope"}]


@pytest.mark.parametrize(
    ("content", "content_type"),
    [("{not json", "application/json"), ("[1, 2]", "application/json"), ("a: [", "text/yaml")],
)
def test_unparseable_body_is_422(client, content, content_type):
    response = client.post("/api/adapters", content=content, headers={"content-type": content_type})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == "(body)"


def test_python_kind_rejected(client):
    response = client.post("/api/adapters", json=PYTHON_DEF)
    assert response.status_code == 422
    assert "built-in adapters" in response.json()["detail"][0]["msg"]


def test_duplicate_id_conflicts(client, adapter):
    assert client.post("/api/adapters", json=HTML_DEF).status_code == 409


def test_replace_adapter(client, adapter):
    changed = dict(HTML_DEF, name="Renamed", version=2)
    response = client.put("/api/adapters/rec-center", json=changed)
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["version"]) == ("Renamed", 2)


def test_replace_cannot_change_id(client, adapter):
    response = client.put("/api/adapters/rec-center", json=dict(HTML_DEF, id="other"))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == "id"


def test_unknown_adapter_is_404(client):
    assert client.get("/api/adapters/nope").status_code == 404
    assert client.put("/api/adapters/nope", json=HTML_DEF).status_code == 404
    assert client.delete("/api/adapters/nope").status_code == 404


def test_delete_adapter(client, adapter):
    assert client.delete("/api/adapters/rec-center").status_code == 204
    assert client.get("/api/adapters/rec-center").status_code == 404


def test_delete_adapter_in_use_conflicts(client, adapter):
    client.post("/api/sources", json=new_source())
    assert client.delete("/api/adapters/rec-center").status_code == 409
