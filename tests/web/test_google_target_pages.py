"""The target-calendar dropdown, Sync now pushing to Google, and the reconnect prompt."""

from tests.web.conftest import source_form

TARGET = "skate#rink@group.calendar.google.com"


def create(client, **overrides):
    response = client.post("/sources/new", data=source_form(**overrides), follow_redirects=False)
    assert response.status_code == 303, response.text
    return client.get("/api/sources").json()[-1]


def test_form_offers_the_users_calendars(client, adapter):
    page = client.get("/sources/new")
    assert "None (.ics feed only)" in page.text
    assert "Me (primary)" in page.text
    assert f'value="{TARGET}"' in page.text


def test_saving_a_target_and_clearing_it(client, adapter):
    source = create(client, target_calendar_id=TARGET)
    assert source["target_calendar_id"] == TARGET
    page = client.get(f"/sources/{source['id']}")
    assert f'value="{TARGET}" selected' in page.text

    response = client.post(
        f"/sources/{source['id']}", data=source_form(target_calendar_id=""), follow_redirects=False
    )
    assert response.status_code == 303
    assert client.get(f"/api/sources/{source['id']}").json()["target_calendar_id"] is None


def test_sync_now_pushes_matched_events_to_google(client, adapter, runner, calendar):
    source = create(client, target_calendar_id=TARGET)
    row = client.post(f"/sources/{source['id']}/sync")
    assert "status-ok" in row.text
    assert [event["summary"] for event in calendar.tagged(TARGET).values()] == ["Public Skate"]

    calendar.writes.clear()
    client.post(f"/sources/{source['id']}/sync")
    assert calendar.writes == []


def test_revoked_grant_shows_reconnect(client, adapter, runner, calendar):
    source = create(client, target_calendar_id=TARGET)
    calendar.grant_revoked = True
    row = client.post(f"/sources/{source['id']}/sync")
    assert "status-error" in row.text
    assert 'href="/auth/login?consent=true"' in row.text

    page = client.get(f"/sources/{source['id']}")
    assert "Reconnect Google" in page.text
    assert f'value="{TARGET}" selected' in page.text  # kept though it can't be listed


def test_api_lists_calendars(client, calendar):
    response = client.get("/api/calendars")
    assert response.status_code == 200
    assert response.json() == [
        {"id": "primary@example.com", "summary": "Me", "primary": True},
        {"id": TARGET, "summary": "Skating", "primary": False},
    ]


def test_api_calendars_conflict_when_google_needs_reconnecting(client, calendar):
    calendar.grant_revoked = True
    response = client.get("/api/calendars")
    assert response.status_code == 409
    assert "reconnect Google" in response.json()["detail"]
