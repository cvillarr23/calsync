"""`python -m app.adapters.pipeline def.yaml key=value ...`: run a definition, print events."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.adapters.fetch import FetchLimits, FetchSession
from app.adapters.mappers import Window
from app.adapters.pipeline.errors import ParamError
from app.adapters.pipeline.result import PipelineResult
from app.adapters.pipeline.run import run_pipeline
from app.adapters.schema import PipelineDefinition, error_list, parse_definition

DEFAULT_DAYS = 60


def main(argv: Sequence[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except (AdapterRunError, OSError, yaml.YAMLError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(_events_json(result.events) if args.json else _events_table(result.events))
    for problem in result.problems:
        print(f"skipped {problem}", file=sys.stderr)
    return 0


def _arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.adapters.pipeline", description="Run a pipeline adapter definition."
    )
    parser.add_argument("definition", type=Path, help="YAML or JSON definition file")
    parser.add_argument("params", nargs="*", metavar="key=value", help="definition params")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="lookahead window")
    parser.add_argument("--start", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--allow-private", action="store_true", help="allow fetching private network addresses"
    )
    return parser


async def _run(args: argparse.Namespace) -> PipelineResult:
    definition = _load_definition(args.definition)
    params = _param_pairs(args.params)
    async with FetchSession(FetchLimits(allow_private=args.allow_private)) as session:
        return await run_pipeline(definition, params, _window(args), session=session)


def _window(args: argparse.Namespace) -> Window:
    """`--days` dates from `--start` (today by default), the first and last included."""
    start = args.start or date.today()
    return Window(start=start, end=start + timedelta(days=max(args.days, 1) - 1))


def _load_definition(path: Path) -> PipelineDefinition:
    try:
        definition = parse_definition(yaml.safe_load(path.read_text()), builtin=True)
    except ValidationError as err:
        problems = "; ".join(f"{row['loc'] or '(root)'}: {row['msg']}" for row in error_list(err))
        raise AdapterRunError(f"invalid definition: {problems}") from None
    if not isinstance(definition, PipelineDefinition):
        raise AdapterRunError(f"{path} is a {definition.kind} definition; this runs pipelines")
    return definition


def _param_pairs(pairs: Sequence[str]) -> dict[str, str]:
    malformed = [pair for pair in pairs if "=" not in pair]
    if malformed:
        raise ParamError(f"params must be key=value, got: {', '.join(malformed)}")
    return dict(pair.split("=", 1) for pair in pairs)


def _events_json(events: Sequence[ScrapedEvent]) -> str:
    return json.dumps([asdict(event) for event in events], indent=2, default=str)


def _events_table(events: Sequence[ScrapedEvent]) -> str:
    rows = [("start (UTC)", "end (UTC)", "title", "location")]
    rows += [_table_row(event) for event in events]
    widths = [max(len(row[col]) for row in rows) for col in range(len(rows[0]))]
    lines = ["  ".join(_padded(row, widths)).rstrip() for row in rows]
    return "\n".join([*lines, f"{len(events)} event(s)"])


def _padded(row: Sequence[str], widths: Sequence[int]) -> list[str]:
    return [cell.ljust(width) for cell, width in zip(row, widths, strict=True)]


def _table_row(event: ScrapedEvent) -> tuple[str, str, str, str]:
    end = f"{event.end_utc:%Y-%m-%d %H:%M}" if event.end_utc else ""
    return f"{event.start_utc:%Y-%m-%d %H:%M}", end, event.title, event.location or ""
