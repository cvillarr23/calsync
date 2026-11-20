"""A user writes a definition in the editor, tests it, and saves a source using it."""

from tests.web.conftest import html_yaml


def test_definition_to_source_without_the_repo(client, local_pages):
    text = html_yaml()
    url = f"{local_pages}/list.html"

    trial = client.post("/adapters/test", data={"yaml": text, "param.url": url, "days": "60"})
    assert "Public Skate" in trial.text

    saved = client.post("/adapters", data={"yaml": text}, follow_redirects=False)
    assert saved.status_code == 303

    form = client.get("/sources/new").text
    assert 'value="rec-center"' in form

    created = client.post(
        "/sources/new",
        data={
            "name": "Rink",
            "adapter_id": "rec-center",
            "param.url": url,
            "include_kw": "skate",
            "interval_min": "360",
            "lookahead_days": "60",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    listing = client.get("/").text
    assert "Rink" in listing and "Rec center schedule" in listing
