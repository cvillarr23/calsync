import pytest

from app import serve
from app.settings import load_settings


def test_proxy_headers_ignored_by_default(required_env):
    assert serve._proxy_options(load_settings()) == {"proxy_headers": False}


def test_proxy_headers_trusted_when_enabled(required_env):
    required_env.setenv("CALSYNC_TRUST_PROXY_HEADERS", "true")
    options = serve._proxy_options(load_settings())
    assert options == {"proxy_headers": True, "forwarded_allow_ips": "*"}


def test_main_runs_uvicorn_on_port_8000(required_env, monkeypatch):
    calls = {}
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.update(kw))
    serve.main()
    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 8000


def test_main_exits_with_named_variables_on_bad_env(clean_env, capsys):
    with pytest.raises(SystemExit) as exc:
        serve.main()
    assert exc.value.code == 1
    assert "CALSYNC_BASE_URL" in capsys.readouterr().err
