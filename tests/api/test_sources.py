import pytest

from tests.adapters.conftest import HTML_DEF


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


def test_create_source(client, adapter):
    response = client.post("/api/sources", json=new_source())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["include_kw"] == ["public skate"]
    assert (body["interval_min"], body["lookahead_days"], body["enabled"]) == (360, 60, True)
    assert body["target_calendar_id"] is None
    assert body["last_status"] is None
    assert body["feed_url"].startswith("https://calsync.example/feeds/")
    assert body["feed_url"].endswith(".ics")


def test_list_get_patch_delete_source(client, adapter):
    source_id = client.post("/api/sources", json=new_source()).json()["id"]
    assert [s["id"] for s in client.get("/api/sources").json()] == [source_id]

    patched = client.patch(
        f"/api/sources/{source_id}", json={"name": "Rink 2", "exclude_kw": [], "interval_min": 60}
    ).json()
    assert (patched["name"], patched["exclude_kw"], patched["interval_min"]) == ("Rink 2", [], 60)
    assert patched["include_kw"] == ["public skate"]
    assert client.get(f"/api/sources/{source_id}").json() == patched

    assert client.delete(f"/api/sources/{source_id}").status_code == 204
    assert client.get(f"/api/sources/{source_id}").status_code == 404


def test_patch_can_clear_target_calendar(client, adapter):
    source = client.post("/api/sources", json=new_source(target_calendar_id="cal-1")).json()
    assert source["target_calendar_id"] == "cal-1"
    cleared = client.patch(f"/api/sources/{source['id']}", json={"target_calendar_id": None})
    assert cleared.json()["target_calendar_id"] is None


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        ({"adapter_id": "nope"}, "adapter_id"),
        ({"params": {}}, "params.url"),
        ({"params": {"url": "ftp://rink.example"}}, "params.url"),
        ({"params": {"url": "https://x.example", "extra": 1}}, "params.extra"),
        ({"interval_min": 5}, "interval_min"),
    ],
)
def test_invalid_source_is_422(client, adapter, overrides, loc):
    response = client.post("/api/sources", json=new_source(**overrides))
    assert response.status_code == 422
    assert loc in [row["loc"] for row in response.json()["detail"]]


def test_lookahead_is_bounded(client, adapter):
    assert client.post("/api/sources", json=new_source(lookahead_days=0)).status_code == 422
    assert client.post("/api/sources", json=new_source(lookahead_days=400)).status_code == 422


def test_unknown_source_is_404(client):
    assert client.get("/api/sources/99").status_code == 404
    assert client.patch("/api/sources/99", json={}).status_code == 404
    assert client.delete("/api/sources/99").status_code == 404


def test_rejected_patch_changes_nothing(client, adapter):
    source = client.post("/api/sources", json=new_source()).json()
    response = client.patch(f"/api/sources/{source['id']}", json={"name": "X", "interval_min": 1})
    assert response.status_code == 422
    assert client.get(f"/api/sources/{source['id']}").json() == source
