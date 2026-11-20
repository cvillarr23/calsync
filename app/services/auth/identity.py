from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """Who Google says signed in, plus the refresh token when Google sent one."""

    email: str
    email_verified: bool
    refresh_token: str | None = None
