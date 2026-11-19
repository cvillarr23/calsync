"""Running a pipeline definition, directly or as the sync core's engine for the pipeline kind."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.adapters.fetch import FetchError, FetchLimits, FetchSession, PageCache
from app.adapters.mappers import FieldFailure, Window, map_item
from app.adapters.pipeline.params import resolve_params
from app.adapters.pipeline.read import jsonpath_reader
from app.adapters.pipeline.result import ItemProblem, PipelineResult
from app.adapters.pipeline.steps import collect_items
from app.adapters.schema import AdapterDefinition, PipelineDefinition


async def run_pipeline(
    definition: PipelineDefinition,
    params: Mapping[str, Any],
    window: Window,
    *,
    session: FetchSession,
) -> PipelineResult:
    """Run the steps and map every item, keeping the first event for each uid.

    A failing step raises `StepError`. A field that can't be read is reported in
    `problems` and only drops its own item.
    """
    resolved = resolve_params(definition, params)
    items = await collect_items(definition.steps, resolved, session=session, window=window)
    return _mapped(definition, items, window)


class PipelineEngine:
    """The `AdapterRunner` engine for the pipeline kind, bound to the instance's fetch limits."""

    def __init__(self, limits: FetchLimits, cache: PageCache | None = None) -> None:
        self._limits = limits
        self._cache = cache

    async def __call__(
        self,
        definition: AdapterDefinition,
        params: Mapping[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> list[ScrapedEvent]:
        if not isinstance(definition, PipelineDefinition):
            raise AdapterRunError(f"the pipeline engine can't run a {definition.kind} definition")
        window = Window.between(window_start, window_end)
        async with FetchSession(self._limits, cache=self._cache) as session:
            try:
                result = await run_pipeline(definition, params, window, session=session)
            except FetchError as err:
                raise AdapterRunError(str(err)) from err
        _fail_if_nothing_read(result)
        return [e for e in result.events if _in_window(e, window_start, window_end)]


def _mapped(definition: PipelineDefinition, items: list[Any], window: Window) -> PipelineResult:
    result, seen = PipelineResult(), set()
    for index, item in enumerate(items):
        try:
            event = map_item(definition.map, jsonpath_reader(item), window, definition.uid)
        except FieldFailure as failure:
            result.problems.append(ItemProblem(index, failure.field, failure.msg))
            continue
        if event is not None and event.uid not in seen:
            seen.add(event.uid)
            result.events.append(event)
    result.events.sort(key=lambda event: event.start_utc)
    return result


def _fail_if_nothing_read(result: PipelineResult) -> None:
    """Every item failed: report the first reason instead of syncing an empty calendar."""
    if result.problems and not result.events:
        more = len(result.problems) - 1
        suffix = f" (and {more} more)" if more else ""
        raise AdapterRunError(f"no event could be read: {result.problems[0]}{suffix}")


def _in_window(event: ScrapedEvent, window_start: datetime, window_end: datetime) -> bool:
    """Pages often reach past the window; the sync core treats what it gets as the window's."""
    return (event.end_utc or event.start_utc) >= window_start and event.start_utc <= window_end
