from pathlib import Path

import pytest

from app.settings import SettingsError, load_settings
from tests.conftest import REQUIRED_ENV


def test_loads_with_required_vars(required_env):
    settings = load_settings()
    assert str(settings.base_url) == "https://calsync.example/"
    assert settings.google_client_secret.get_secret_value() == "placeholder-client-secret"


def test_defaults(required_env):
    settings = load_settings()
    assert settings.data_dir == Path("/data")
    assert settings.allowed_emails == []
    assert settings.min_interval_min == 30
    assert settings.fetch_timeout_s == 15
    assert settings.fetch_max_pages == 20
    assert settings.fetch_max_bytes == 2 * 1024 * 1024
    assert settings.fetch_allow_private is False
    assert settings.trust_proxy_headers is False


@pytest.mark.parametrize("name", sorted(REQUIRED_ENV))
def test_missing_required_var_is_named(required_env, name):
    required_env.delenv(name)
    with pytest.raises(SettingsError, match=name):
        load_settings()


def test_all_missing_vars_listed(clean_env):
    with pytest.raises(SettingsError) as exc:
        load_settings()
    for name in REQUIRED_ENV:
        assert name in str(exc.value)


def test_invalid_value_is_named(required_env):
    required_env.setenv("CALSYNC_FETCH_MAX_PAGES", "lots")
    with pytest.raises(SettingsError, match="CALSYNC_FETCH_MAX_PAGES"):
        load_settings()


def test_allowed_emails_parsed(required_env):
    required_env.setenv("CALSYNC_ALLOWED_EMAILS", " A@example.com, ,b@example.org ")
    assert load_settings().allowed_emails == ["a@example.com", "b@example.org"]


@pytest.mark.parametrize("key", ["your-fernet-key", "c2hvcnQ="])
def test_token_key_must_be_a_fernet_key(required_env, key):
    required_env.setenv("CALSYNC_TOKEN_ENC_KEY", key)
    with pytest.raises(SettingsError, match="CALSYNC_TOKEN_ENC_KEY") as err:
        load_settings()
    assert "Fernet.generate_key()" in str(err.value)


def test_redirect_uri_has_no_double_slash(required_env):
    assert load_settings().redirect_uri == "https://calsync.example/auth/callback"
