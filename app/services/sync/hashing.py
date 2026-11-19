import hashlib
import json

from app.adapters.events import ScrapedEvent


def content_hash(event: ScrapedEvent) -> str:
    """A stable hash of everything a calendar shows, so unchanged events can be skipped."""
    fields = {
        "title": event.title,
        "start": event.start_utc.isoformat(),
        "end": event.end_utc.isoformat() if event.end_utc else None,
        "location": event.location,
        "description": event.description,
        "url": event.url,
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
