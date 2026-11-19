from typing import Any

from app.db.models import Source
from app.schemas.source import SourceOut, SourcePatch
from app.services.feeds import feed_url
from app.settings import Settings

_COLUMN_FOR = {"params": "params_json"}
"""API field names that differ from their column names."""

_NULLABLE = {"target_calendar_id"}
"""Fields a client may clear by sending null; null means "unchanged" for the rest."""


def source_columns(body: SourcePatch, fields: set[str]) -> dict[str, Any]:
    """The column values to write for the given fields of a create or patch body."""
    return {
        _COLUMN_FOR.get(name, name): getattr(body, name)
        for name in fields
        if getattr(body, name) is not None or name in _NULLABLE
    }


def source_out(settings: Settings, source: Source) -> SourceOut:
    return SourceOut(
        id=source.id,
        name=source.name,
        adapter_id=source.adapter_id,
        params=source.params_json,
        include_kw=source.include_kw,
        exclude_kw=source.exclude_kw,
        interval_min=source.interval_min,
        lookahead_days=source.lookahead_days,
        target_calendar_id=source.target_calendar_id,
        enabled=source.enabled,
        feed_url=feed_url(settings, source.feed_token),
        last_run_at=source.last_run_at,
        last_status=source.last_status,
        last_error=source.last_error,
    )
