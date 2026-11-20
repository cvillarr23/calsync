"""**Test with params** in the adapter editor: run an unsaved definition and show every row.

The engines raise when no item can be read, which is right for syncing but hides
the per-field reasons. This calls the kind's run function directly, so the
editor gets the events and every field problem side by side.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.adapters.fetch import FetchError, FetchLimits, FetchSession, PageCache
from app.adapters.html.run import run_html
from app.adapters.mappers import Window
from app.adapters.pipeline.run import run_pipeline
from app.adapters.schema import AdapterDefinition, HtmlDefinition, PipelineDefinition
from app.services.sync.scrape import params_with_defaults


@dataclass(frozen=True)
class FieldRow:
    """One item that was left out: where it was, which field failed, and why."""

    where: str
    field: str
    msg: str


@dataclass
class DefinitionTrial:
    events: list[ScrapedEvent] = field(default_factory=list)
    problems: list[FieldRow] = field(default_factory=list)
    error: str | None = None


async def try_definition(
    definition: AdapterDefinition,
    params: dict[str, Any],
    now: datetime,
    days: int,
    *,
    limits: FetchLimits,
    cache: PageCache | None = None,
    **fetch_options: Any,
) -> DefinitionTrial:
    """Run the definition over `days` from `now`. `fetch_options` reach the fetch session
    (tests pass a guard and resolver for their local page server)."""
    window = Window.between(now, now + timedelta(days=max(days, 1) - 1))
    resolved = params_with_defaults(definition, params)
    try:
        return await _run(definition, resolved, window, limits, cache, fetch_options)
    except (AdapterRunError, FetchError) as err:
        return DefinitionTrial(error=str(err) or type(err).__name__)


async def _run(
    definition: AdapterDefinition,
    params: dict[str, Any],
    window: Window,
    limits: FetchLimits,
    cache: PageCache | None,
    fetch_options: dict[str, Any],
) -> DefinitionTrial:
    if isinstance(definition, PipelineDefinition):
        async with FetchSession(limits, cache=cache, **fetch_options) as session:
            result = await run_pipeline(definition, params, window, session=session)
        rows = [FieldRow(f"item {p.item}", p.field, p.msg) for p in result.problems]
        return DefinitionTrial(result.events, rows)
    if isinstance(definition, HtmlDefinition):
        result = await run_html(
            definition, params, window, limits=limits, cache=cache, **fetch_options
        )
        rows = [FieldRow(f"{p.page} item {p.item}", p.field, p.msg) for p in result.problems]
        return DefinitionTrial(result.events, rows)
    return DefinitionTrial(error=f"{definition.kind} adapters can't be tested in the editor")
