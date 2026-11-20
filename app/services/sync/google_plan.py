"""What a Google push must change: the matched set diffed against `google_map`."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.db.models import Event, GoogleMap


@dataclass
class GooglePlan:
    """Writes for one push. `forget` rows are dropped from the map without calling Google."""

    inserts: list[Event] = field(default_factory=list)
    patches: list[tuple[GoogleMap, Event]] = field(default_factory=list)
    deletes: list[GoogleMap] = field(default_factory=list)
    forget: list[GoogleMap] = field(default_factory=list)

    @property
    def calls_google(self) -> bool:
        return bool(self.inserts or self.patches or self.deletes)


def plan_push(
    target: str | None,
    mapped: Mapping[str, GoogleMap],
    matched: Sequence[Event],
    now: datetime,
) -> GooglePlan:
    """Insert new matches, patch changed ones, delete future events that are gone.

    With no target every mapped event counts as gone, so clearing the target cleans up.
    """
    wanted = {event.uid: event for event in matched} if target else {}
    plan = GooglePlan()
    for uid, event in wanted.items():
        _plan_wanted(plan, target, mapped.get(uid), event)
    for uid, row in mapped.items():
        if not _still_wanted(row, target, wanted, uid):
            _plan_unwanted(plan, row, now)
    return plan


def _plan_wanted(plan: GooglePlan, target: str | None, row: GoogleMap | None, event: Event) -> None:
    """A row for another calendar is deleted there first (see `_plan_unwanted`), then re-added."""
    if row is None or row.calendar_id != target:
        plan.inserts.append(event)
    elif row.content_hash != event.content_hash:
        plan.patches.append((row, event))


def _still_wanted(
    row: GoogleMap, target: str | None, wanted: Mapping[str, Event], uid: str
) -> bool:
    return uid in wanted and row.calendar_id == target


def _plan_unwanted(plan: GooglePlan, row: GoogleMap, now: datetime) -> None:
    """Only future events are deleted. Past ones, and rows too old to say, are just forgotten."""
    if _deletable(row, now):
        plan.deletes.append(row)
    else:
        plan.forget.append(row)


def _deletable(row: GoogleMap, now: datetime) -> bool:
    return row.calendar_id is not None and row.start_utc is not None and row.start_utc >= now
