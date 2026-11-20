"""calsync events as Google Calendar event bodies, and the tag that marks them as ours."""

from datetime import UTC, datetime
from typing import Any

from app.db.models import Event

TAG_SOURCE = "calsync_source"
TAG_UID = "calsync_uid"


def event_body(event: Event) -> dict[str, Any]:
    """Every field calsync owns; `None` clears a field when the body is used for a patch."""
    return {
        "summary": event.title,
        "location": event.location,
        "description": _description(event),
        "start": _when(event.start_utc),
        "end": _when(event.end_utc or event.start_utc),
        "extendedProperties": {"private": tag(event.source_id, event.uid)},
    }


def tag(source_id: int, uid: str) -> dict[str, str]:
    return {TAG_SOURCE: str(source_id), TAG_UID: uid}


def is_ours(remote: dict[str, Any], source_id: int, uid: str) -> bool:
    """A live Google event carrying exactly this source's tag for this uid."""
    if remote.get("status") == "cancelled":
        return False
    private = remote.get("extendedProperties", {}).get("private", {})
    return private.get(TAG_SOURCE) == str(source_id) and private.get(TAG_UID) == uid


def _when(value: datetime) -> dict[str, str]:
    return {"dateTime": value.astimezone(UTC).isoformat(), "timeZone": "UTC"}


def _description(event: Event) -> str | None:
    parts = [part for part in (event.description, event.url) if part]
    return "\n\n".join(parts) or None
