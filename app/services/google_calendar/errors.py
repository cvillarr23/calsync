class CalendarApiError(RuntimeError):
    """Google Calendar refused a request, or stayed unavailable through every retry."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GoogleReconnectNeeded(RuntimeError):
    """calsync holds no usable refresh token: it was revoked, expired or never stored."""

    def __init__(self) -> None:
        super().__init__(
            "Google access was revoked or has expired; reconnect Google to resume syncing"
        )
