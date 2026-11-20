from app.api.csrf import HEADER
from tests.adapters.conftest import HTML_DEF


def test_api_post_without_token_is_forbidden(client):
    del client.headers[HEADER]
    response = client.post("/api/adapters", json=HTML_DEF)
    assert response.status_code == 403


def test_api_post_with_wrong_token_is_forbidden(client):
    response = client.post("/api/adapters", json=HTML_DEF, headers={HEADER: "nope"})
    assert response.status_code == 403


def test_text_plain_cross_site_post_is_forbidden(client):
    """A cross-site form can send text/plain JSON-looking bodies; it can't send the header."""
    del client.headers[HEADER]
    response = client.post(
        "/api/adapters", content='{"id": "x"}', headers={"content-type": "text/plain"}
    )
    assert response.status_code == 403


def test_form_post_accepts_the_hidden_field(client):
    token = client.headers.pop(HEADER)
    response = client.post(
        "/sources/new", data={"csrf_token": token, "name": ""}, follow_redirects=False
    )
    assert response.status_code == 422


def test_form_post_without_token_is_forbidden(client):
    del client.headers[HEADER]
    assert client.post("/sources/new", data={"name": "x"}).status_code == 403


def test_logout_needs_the_token(client):
    del client.headers[HEADER]
    assert client.post("/auth/logout").status_code == 403
