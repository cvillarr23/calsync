from app.adapters.schema import AdapterDefinition
from app.db.models import Source
from app.schemas.pages import ProblemRow, SourceRow
from app.services.error_hints import definition_hint, run_hint
from app.services.feeds import feed_url
from app.services.schedule import estimated_next_run
from app.services.source_validation import Problem
from app.services.yaml_lines import line_for
from app.settings import Settings


def source_row(
    settings: Settings, source: Source, definition: AdapterDefinition | None, matched: int
) -> SourceRow:
    return SourceRow(
        id=source.id,
        name=source.name,
        adapter_name=definition.name if definition else f"{source.adapter_id} (missing)",
        enabled=source.enabled,
        status=source.last_status or "never run",
        error=source.last_error,
        hint=run_hint(source.last_error),
        last_run_at=source.last_run_at,
        next_run_at=estimated_next_run(source),
        matched=matched,
        feed_url=feed_url(settings, source.feed_token),
    )


def problem_rows(text: str, problems: list[Problem]) -> list[ProblemRow]:
    return [
        ProblemRow(
            loc=row["loc"] or "(root)",
            msg=row["msg"],
            line=line_for(text, row["loc"]),
            hint=definition_hint(row["msg"]),
        )
        for row in problems
    ]
