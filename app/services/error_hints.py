"""Plain-language help for the errors users meet while writing definitions and running sources.

Messages come from definition validation (`app.adapters.schema`), from runs
(`AdapterRunError`, `FetchError`) and from the sync core's empty-run guard. Each
hint says what usually causes the error and links to the docs page that explains it.
"""

import re
from dataclasses import dataclass

DOCS = "https://cvillarr23.github.io/calsync/"


@dataclass(frozen=True)
class Hint:
    text: str
    doc: str

    @property
    def url(self) -> str:
        return DOCS + self.doc


_STEP_ORDER = Hint(
    "Steps run top to bottom. A typical pipeline is http → extract → paginate → http → "
    "extract → items: items comes last, and paginate sits before the request it repeats.",
    "adapters/pipeline/#step-order",
)
_JSONPATH = Hint(
    "JSONPath starts at the document root: $.d, $.MonthlyBookingResults[*], "
    "$.events[?(@.status != 'cancelled')]. Check the brackets and quotes.",
    "adapters/pipeline/#extract",
)
_CSS = Hint(
    "Use a CSS selector such as .event, li.booking h3 or time[datetime]. "
    "XPath and pseudo-elements like ::text aren't supported; use attr to read an attribute.",
    "adapters/html/",
)
_CAPTURE = Hint(
    "An extract regex keeps its first capture group, so wrap the part you want in (...).",
    "adapters/pipeline/#extract",
)
_VARIABLE = Hint(
    "A template can use the definition's params and the variables earlier steps saved with "
    "as:. A step can't read a variable that a later step saves.",
    "adapters/concepts/#templates",
)
_EMPTY_RUN = Hint(
    "calsync kept the stored events: a run that finds nothing usually means an error page or "
    "a site redesign, not an empty schedule. Open the adapter and use Test with params to see "
    "what the site returns now.",
    "feeds/",
)
_NOTHING_READ = Hint(
    "Every item was found but a required field (title, start or date) couldn't be read from "
    "any of them. Test with params lists the field and reason for each item.",
    "adapters/concepts/#the-field-map",
)
_STEP_FAILED = Hint(
    "A pipeline step failed while running. Steps are numbered from 0 in the order they're "
    "written; Test with params shows the same error against the live site.",
    "adapters/pipeline/#errors",
)
_BLOCKED = Hint(
    "calsync refuses to fetch private and loopback addresses. Set CALSYNC_FETCH_ALLOW_PRIVATE "
    "only if the calendar really is on your own network.",
    "configuration/",
)
_RECONNECT = Hint(
    "Google stopped accepting calsync's access, for example after you removed it from your "
    "Google account. Use Reconnect Google to sign in again; the next sync picks up from there.",
    "google-calendar/#reconnecting-google",
)
_CALENDAR = Hint(
    "Google Calendar refused the change. Check that the target calendar still exists and that "
    "you can add events to it, or pick another one on the source form.",
    "google-calendar/",
)

_DEFINITION_HINTS: list[tuple[re.Pattern[str], Hint]] = [
    (
        re.compile(
            r"items must be the last step|paginate repeats|exactly one items step|"
            r"at most one paginate step"
        ),
        _STEP_ORDER,
    ),
    (re.compile(r"invalid JSONPath"), _JSONPATH),
    (re.compile(r"invalid CSS selector"), _CSS),
    (re.compile(r"capture group"), _CAPTURE),
    (re.compile(r"unknown variable"), _VARIABLE),
]
_RUN_HINTS: list[tuple[re.Pattern[str], Hint]] = [
    (re.compile(r"returned no events"), _EMPTY_RUN),
    (re.compile(r"no event could be read"), _NOTHING_READ),
    (re.compile(r"^step \d+ \("), _STEP_FAILED),
    (re.compile(r"non-public address|unix sockets"), _BLOCKED),
    (re.compile(r"reconnect Google"), _RECONNECT),
    (re.compile(r"Google Calendar answered|target calendar"), _CALENDAR),
]


def definition_hint(msg: str) -> Hint | None:
    """Help for one validation error message, if it's one users commonly hit."""
    return _first(_DEFINITION_HINTS, msg)


def run_hint(error: str | None) -> Hint | None:
    """Help for a run's error, as shown on the sources list and in Test with params."""
    return _first(_RUN_HINTS, error) if error else None


def _first(table: list[tuple[re.Pattern[str], Hint]], msg: str) -> Hint | None:
    return next((hint for pattern, hint in table if pattern.search(msg)), None)
