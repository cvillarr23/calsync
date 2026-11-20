from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

MAX_LOOKAHEAD_DAYS = 366

Name = Annotated[str, Field(min_length=1)]


class SourcePatch(BaseModel):
    """Fields a client may change; on create, `name` and `adapter_id` are required."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    adapter_id: str | None = None
    params: dict[str, Any] | None = None
    include_kw: list[str] | None = None
    exclude_kw: list[str] | None = None
    interval_min: int | None = None
    lookahead_days: Annotated[int, Field(ge=1, le=MAX_LOOKAHEAD_DAYS)] | None = None
    target_calendar_id: str | None = None
    enabled: bool | None = None


class SourceCreate(SourcePatch):
    name: Name
    adapter_id: str


class SourceOut(BaseModel):
    id: int
    name: str
    adapter_id: str
    params: dict[str, Any]
    include_kw: list[str]
    exclude_kw: list[str]
    interval_min: int
    lookahead_days: int
    target_calendar_id: str | None
    enabled: bool
    feed_url: str
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    consecutive_failures: int
    next_run_at: datetime | None
