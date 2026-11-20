from datetime import datetime, timedelta

import pytest

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.db.base import utcnow
from tests.adapters.conftest import HTML_DEF
from tests.support import FakeRunner


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


def test_sync_now_runs_the_source_and_reschedules_it(client, adapter):
    skate = ScrapedEvent("skate-1", "Public Skate", utcnow() + timedelta(days=1))
    client.app.state.scheduler.runs.runner = FakeRunner([skate])
    source_id = client.post("/api/sources", json=new_source()).json()["id"]

    response = client.post(f"/api/sources/{source_id}/sync")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "ok",
        "error": None,
        "fetched": 1,
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "removed": 0,
        "matched": 1,
    }
    source = client.get(f"/api/sources/{source_id}").json()
    assert (source["last_status"], source["consecutive_failures"]) == ("ok", 0)
    last_run = datetime.fromisoformat(source["last_run_at"])
    assert datetime.fromisoformat(source["next_run_at"]) == last_run + timedelta(minutes=360)


def test_sync_now_reports_failures(client, adapter):
    client.app.state.scheduler.runs.runner = FakeRunner(error=AdapterRunError("site down"))
    source_id = client.post("/api/sources", json=new_source()).json()["id"]

    assert client.post(f"/api/sources/{source_id}/sync").json()["error"] == "site down"
    source = client.get(f"/api/sources/{source_id}").json()
    assert (source["last_status"], source["consecutive_failures"]) == ("error", 1)


def test_sync_now_of_a_missing_source_is_404(client):
    assert client.post("/api/sources/99/sync").status_code == 404


def test_sync_now_while_syncing_is_409(client, adapter):
    source_id = client.post("/api/sources", json=new_source()).json()["id"]
    lock = client.app.state.scheduler.runs.lock(source_id)
    client.portal.call(lock.acquire)
    try:
        response = client.post(f"/api/sources/{source_id}/sync")
    finally:
        client.portal.call(lock.release)
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_patching_the_interval_moves_the_next_run(client, adapter):
    scheduler = client.app.state.scheduler
    scheduler.runs.runner = FakeRunner()
    source_id = client.post("/api/sources", json=new_source()).json()["id"]
    client.post(f"/api/sources/{source_id}/sync")
    last_run = datetime.fromisoformat(client.get(f"/api/sources/{source_id}").json()["last_run_at"])

    patched = client.patch(f"/api/sources/{source_id}", json={"interval_min": 60}).json()
    assert datetime.fromisoformat(patched["next_run_at"]) == last_run + timedelta(minutes=60)
    assert scheduler.next_run_at(source_id) == last_run + timedelta(minutes=60)


def test_disabled_sources_have_no_next_run(client, adapter):
    scheduler = client.app.state.scheduler
    source_id = client.post("/api/sources", json=new_source()).json()["id"]
    assert scheduler.next_run_at(source_id) is not None

    patched = client.patch(f"/api/sources/{source_id}", json={"enabled": False}).json()
    assert patched["next_run_at"] is None
    assert scheduler.next_run_at(source_id) is None


def test_deleting_a_source_drops_its_job(client, adapter):
    scheduler = client.app.state.scheduler
    source_id = client.post("/api/sources", json=new_source()).json()["id"]
    client.delete(f"/api/sources/{source_id}")
    assert scheduler.next_run_at(source_id) is None
