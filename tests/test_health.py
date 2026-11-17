from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import load_settings


def test_healthz(required_env):
    client = TestClient(create_app(load_settings()))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
