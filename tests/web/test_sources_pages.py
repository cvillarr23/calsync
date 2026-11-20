from app.adapters.events import AdapterRunError
from tests.web.conftest import source_form


def create(client, **overrides):
    response = client.post("/sources/new", data=source_form(**overrides), follow_redirects=False)
    assert response.status_code == 303, response.text
    return client.get("/api/sources").json()[-1]


def test_empty_list_points_at_new_source(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "No sources yet" in page.text
    assert 'href="/sources/new"' in page.text


def test_create_source_from_the_form(client, adapter, runner):
    source = create(client)
    assert source["params"] == {"url": "https://rink.example/schedule"}
    assert source["include_kw"] == ["public skate"]
    assert source["exclude_kw"] == ["theme night"]
    assert source["lookahead_days"] == 30
    page = client.get("/")
    assert "Rink" in page.text
    assert source["feed_url"] in page.text
    assert "after first sync" in page.text


def test_form_errors_are_shown_next_to_fields(client, adapter):
    form = source_form(name="", interval_min="5")
    del form["param.url"]
    response = client.post("/sources/new", data=form)
    assert response.status_code == 422
    assert "at least 1 character" in response.text
    response = client.post("/sources/new", data=source_form(interval_min="5", **{"param.url": ""}))
    assert "must be at least 30 minutes" in response.text
    assert "required" in response.text
    assert client.get("/api/sources").json() == []


def test_edit_keeps_rejected_changes_out(client, adapter):
    source = create(client)
    response = client.post(f"/sources/{source['id']}", data=source_form(interval_min="1"))
    assert response.status_code == 422
    assert client.get(f"/api/sources/{source['id']}").json()["interval_min"] == 360
    response = client.post(
        f"/sources/{source['id']}", data=source_form(name="Renamed"), follow_redirects=False
    )
    assert response.status_code == 303
    assert client.get(f"/api/sources/{source['id']}").json()["name"] == "Renamed"


def test_sync_now_swaps_in_the_updated_row(client, adapter, runner):
    source = create(client)
    row = client.post(f"/sources/{source['id']}/sync")
    assert row.status_code == 200
    assert row.text.lstrip().startswith(f'<tr id="source-{source["id"]}"')
    assert "status-ok" in row.text
    assert "<td>1</td>" in row.text  # only Public Skate passes the filters
    assert "estimated" in row.text


def test_sync_error_shows_a_hint(client, adapter, runner):
    source = create(client)
    runner.error = AdapterRunError(
        "the adapter returned no events, so nothing was removed; check the definition"
    )
    row = client.post(f"/sources/{source['id']}/sync").text
    assert "status-error" in row
    assert "calsync kept the stored events" in row


def test_preview_updates_as_keywords_change(client, adapter, runner):
    preview = client.post("/sources/preview", data=source_form(include_kw="", exclude_kw="")).text
    assert "Matched (3)" in preview and "Excluded (0)" in preview

    preview = client.post("/sources/preview", data=source_form()).text
    assert "Matched (1)" in preview and "Excluded (2)" in preview
    matched = preview.split('id="excluded"')[0]
    assert "Public Skate" in matched and "Theme Night" not in matched

    preview = client.post("/sources/preview", data=source_form(exclude_kw="")).text
    assert "Matched (2)" in preview and "Excluded (1)" in preview
    assert len(runner.calls) == 1  # keyword changes reuse the cached run


def test_preview_asks_for_missing_params(client, adapter, runner):
    preview = client.post("/sources/preview", data=source_form(**{"param.url": ""})).text
    assert "params.url" in preview and "required" in preview
    assert runner.calls == []


def test_preview_shows_run_errors(client, adapter, runner):
    runner.error = AdapterRunError("step 0 (http): GET failed with 503")
    preview = client.post("/sources/preview", data=source_form()).text
    assert "503" in preview
    assert "Steps are numbered from 0" in preview


def test_suggest_selects_the_matching_adapter(client, adapter):
    page = client.get("/sources/suggest", params={"url": "https://www.rink.example/x"}).text
    assert '<option value="rec-center" selected>' in page
    assert "change, load" in page
    page = client.get("/sources/suggest", params={"url": "https://elsewhere.example/"}).text
    assert "selected" not in page and "No adapter lists this host" in page


def test_params_fields_come_from_the_definition(client, adapter):
    fields = client.get(
        "/sources/params", params={"adapter_id": "rec-center", "url": "https://rink.example/s"}
    ).text
    assert 'name="param.url"' in fields
    assert 'type="url"' in fields
    assert 'value="https://rink.example/s"' in fields


def test_other_users_sources_are_hidden(client, adapter, google):
    from tests.support import google_sign_in, page_csrf_token

    source = create(client)
    google_sign_in(client, google, email="other@example.com")
    client.headers["X-CSRF-Token"] = page_csrf_token(client)
    assert client.get(f"/sources/{source['id']}").status_code == 404
    assert "Rink" not in client.get("/").text
    assert client.get("/sources/params", params={"adapter_id": "rec-center"}).text.strip() == ""


def test_delete_source(client, adapter):
    source = create(client)
    client.post(f"/sources/{source['id']}/delete")
    assert client.get("/api/sources").json() == []
