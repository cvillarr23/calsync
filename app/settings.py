"""Runtime configuration, read from environment variables only."""

import base64
import binascii
from pathlib import Path
from typing import Annotated, Any

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIB = 1024 * 1024


def _env(name: str, default: Any = ..., **kwargs: Any) -> Any:
    """Bind a field to its exact environment variable name, so errors name the variable."""
    return Field(default, validation_alias=name, **kwargs)


class SettingsError(RuntimeError):
    """Raised when the environment is missing or has invalid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    base_url: AnyHttpUrl = _env("CALSYNC_BASE_URL")
    google_client_id: str = _env("GOOGLE_CLIENT_ID", min_length=1)
    google_client_secret: SecretStr = _env("GOOGLE_CLIENT_SECRET", min_length=1)
    session_secret: SecretStr = _env("CALSYNC_SESSION_SECRET", min_length=1)
    token_enc_key: SecretStr = _env("CALSYNC_TOKEN_ENC_KEY", min_length=1)

    data_dir: Path = _env("CALSYNC_DATA_DIR", Path("/data"))
    allowed_emails: Annotated[list[str], NoDecode] = _env("CALSYNC_ALLOWED_EMAILS", [])
    min_interval_min: int = _env("CALSYNC_MIN_INTERVAL_MIN", 30, ge=1)
    fetch_timeout_s: float = _env("CALSYNC_FETCH_TIMEOUT_S", 15.0, gt=0)
    fetch_max_pages: int = _env("CALSYNC_FETCH_MAX_PAGES", 20, ge=1)
    fetch_max_bytes: int = _env("CALSYNC_FETCH_MAX_BYTES", 2 * MIB, ge=1)
    fetch_allow_private: bool = _env("CALSYNC_FETCH_ALLOW_PRIVATE", False)
    trust_proxy_headers: bool = _env("CALSYNC_TRUST_PROXY_HEADERS", False)

    @field_validator("token_enc_key")
    @classmethod
    def _fernet_key(cls, value: SecretStr) -> SecretStr:
        try:
            raw = base64.urlsafe_b64decode(value.get_secret_value().encode())
        except (binascii.Error, ValueError):
            raw = b""
        if len(raw) != 32:
            raise ValueError("must be a Fernet key: 32 bytes, url-safe base64 encoded")
        return value

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: Any) -> Any:
        """Accept a comma-separated string; normalise to lowercase without blanks."""
        if isinstance(value, str):
            value = value.split(",")
        return [item.strip().lower() for item in value if item.strip()]


def load_settings() -> Settings:
    """Build settings from the environment, failing with every bad variable named."""
    try:
        return Settings()
    except ValidationError as err:
        raise SettingsError(_describe(err)) from None


def _describe(err: ValidationError) -> str:
    missing = _missing_vars(err)
    invalid = [f"{e['loc'][0]}: {e['msg']}" for e in err.errors() if e["type"] != "missing"]
    lines = ["Invalid calsync configuration."]
    if missing:
        lines.append("Missing required environment variables: " + ", ".join(missing))
    lines.extend(f"Invalid value for {item}" for item in invalid)
    return "\n".join(lines)


def _missing_vars(err: ValidationError) -> list[str]:
    return [str(e["loc"][0]) for e in err.errors() if e["type"] == "missing"]
