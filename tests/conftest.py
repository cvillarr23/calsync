import pytest

REQUIRED_ENV = {
    "CALSYNC_BASE_URL": "https://calsync.example",
    "GOOGLE_CLIENT_ID": "placeholder-client-id",
    "GOOGLE_CLIENT_SECRET": "placeholder-client-secret",
    "CALSYNC_SESSION_SECRET": "placeholder-session-secret",
    "CALSYNC_TOKEN_ENC_KEY": "placeholder-token-key",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Remove any CALSYNC_/GOOGLE_ variables inherited from the developer's shell."""
    import os

    for name in list(os.environ):
        if name.startswith(("CALSYNC_", "GOOGLE_")):
            monkeypatch.delenv(name)
    return monkeypatch


@pytest.fixture
def required_env(clean_env):
    for name, value in REQUIRED_ENV.items():
        clean_env.setenv(name, value)
    return clean_env
