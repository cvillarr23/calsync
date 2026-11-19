"""Container entry point: run calsync under uvicorn, configured from the environment.

Run with: python -m app.serve
"""

import sys
from typing import Any

import uvicorn

from app.main import create_app
from app.settings import Settings, SettingsError, load_settings

HOST = "0.0.0.0"
PORT = 8000


def main() -> None:
    settings = _settings_or_exit()
    uvicorn.run(create_app(settings), host=HOST, port=PORT, **_proxy_options(settings))


def _settings_or_exit() -> Settings:
    """Print configuration errors as plain text; a traceback would bury the variable names."""
    try:
        return load_settings()
    except SettingsError as err:
        print(err, file=sys.stderr)
        raise SystemExit(1) from None


def _proxy_options(settings: Settings) -> dict[str, Any]:
    """Trust X-Forwarded-* from any peer only when the operator opts in.

    uvicorn's default allow-list is 127.0.0.1, which never matches a proxy outside the
    container, so trusting the proxy means allowing every peer. That is only safe when
    calsync is reachable solely through the proxy.
    """
    if settings.trust_proxy_headers:
        return {"proxy_headers": True, "forwarded_allow_ips": "*"}
    return {"proxy_headers": False}


if __name__ == "__main__":
    main()
