import copy

import yaml

from tests.adapters.conftest import UW_EMS
from tests.web.conftest import html_yaml


def test_new_editor_starts_from_a_valid_template(client):
    page = client.get("/adapters/new").text
    assert "id: my-calendar" in page
    assert "Valid html definition" in page


def test_validate_reports_step_order_with_line_and_hint(client):
    data = copy.deepcopy(UW_EMS)
    data["steps"].append(data["steps"].pop(2))  # paginate last
    text = yaml.safe_dump(data, sort_keys=False)
    response = client.post("/adapters/validate", data={"yaml": text}).text
    assert "steps.5" in response
    assert "items must be the last step" in response
    assert "line " in response
    assert "Steps run top to bottom" in response


def test_validate_explains_jsonpath_and_css_errors(client):
    data = copy.deepcopy(UW_EMS)
    data["map"]["title"]["jsonpath"] = "$.[EventName"
    text = yaml.safe_dump(data, sort_keys=False)
    response = client.post("/adapters/validate", data={"yaml": text}).text
    assert "map.title.jsonpath" in response
    assert "JSONPath starts at the document root" in response

    response = client.post("/adapters/validate", data={"yaml": html_yaml(item="li[")}).text
    assert "item" in response and "invalid CSS selector" in response
    assert "Value error" not in response
    assert "Use a CSS selector" in response


def test_validate_bad_yaml(client):
    response = client.post("/adapters/validate", data={"yaml": "id: [unclosed"}).text
    assert "invalid YAML" in response


def test_valid_definition_refreshes_test_params(client):
    response = client.post(
        "/adapters/validate", data={"yaml": html_yaml(), "param.url": "https://x.example/"}
    ).text
    assert "Valid html definition" in response
    assert 'id="test-params" hx-swap-oob="true"' in response
    assert 'value="https://x.example/"' in response


def test_test_with_params_shows_rows_and_field_errors(client, local_pages):
    form = {"yaml": html_yaml(), "param.url": f"{local_pages}/list.html", "days": "14"}
    response = client.post("/adapters/test", data=form).text
    assert "Public Skate" in response and "Stick and Puck" in response
    assert "Field errors" in response
    assert "start" in response and "matched nothing" in response


def test_test_with_params_shows_fetch_errors(client, local_pages):
    form = {"yaml": html_yaml(), "param.url": f"{local_pages}/missing.html"}
    response = client.post("/adapters/test", data=form).text
    assert "404" in response


def test_test_with_params_blocks_private_addresses(client):
    form = {"yaml": html_yaml(), "param.url": "http://127.0.0.1:9/"}
    response = client.post("/adapters/test", data=form).text
    assert "non-public address" in response
    assert "CALSYNC_FETCH_ALLOW_PRIVATE" in response


def test_save_shows_errors_and_saves_nothing(client):
    response = client.post("/adapters", data={"yaml": html_yaml(item="")})
    assert response.status_code == 422
    assert "Not saved" in response.text
    assert client.get("/api/adapters").json() == []


def test_save_keeps_yaml_as_written_and_export_returns_it(client):
    text = html_yaml()
    response = client.post("/adapters", data={"yaml": text}, follow_redirects=False)
    assert response.headers["location"] == "/adapters/rec-center?saved=1"
    export = client.get("/adapters/rec-center.yaml")
    assert export.text == text
    assert export.headers["content-disposition"] == 'attachment; filename="rec-center.yaml"'
    assert "Saved." in client.get("/adapters/rec-center?saved=1").text


def test_duplicate_id_is_a_conflict(client):
    client.post("/adapters", data={"yaml": html_yaml()})
    response = client.post("/adapters", data={"yaml": html_yaml()})
    assert response.status_code == 409
    assert "is taken" in response.text


def test_edit_cannot_change_id(client):
    client.post("/adapters", data={"yaml": html_yaml()})
    response = client.post("/adapters/rec-center", data={"yaml": html_yaml(id="renamed")})
    assert response.status_code == 422
    assert "id must stay" in response.text


def test_import_creates_a_definition(client):
    response = client.post("/adapters/import", data={"yaml": html_yaml()}, follow_redirects=False)
    assert response.status_code == 303
    assert [a["id"] for a in client.get("/api/adapters").json()] == ["rec-center"]
    assert "rec-center" in client.get("/adapters").text


def test_import_shows_problems(client):
    response = client.post("/adapters/import", data={"yaml": "kind: python\nid: x"})
    assert response.status_code == 422
    assert "Not imported" in response.text


def test_copy_as_new_renames_the_id(client):
    client.post("/adapters", data={"yaml": html_yaml()})
    page = client.get("/adapters/new?copy=rec-center").text
    assert "id: rec-center-copy" in page
    assert "# rink page" in page


def test_delete_adapter(client):
    client.post("/adapters", data={"yaml": html_yaml()})
    client.post("/adapters/rec-center/delete")
    assert client.get("/api/adapters").json() == []


def test_builtins_open_read_only(client, tmp_path):
    registry = client.app.state.adapters
    registry.load_builtin_dir(_builtin_dir(tmp_path))
    page = client.get("/adapters/uw-ems").text
    assert "built-in, read-only" in page
    assert "readonly" in page
    assert 'type="submit">Save' not in page
    assert client.post("/adapters/uw-ems", data={"yaml": "x"}).status_code == 409


def _builtin_dir(tmp_path):
    (tmp_path / "uw.yaml").write_text(yaml.safe_dump(UW_EMS))
    return tmp_path
