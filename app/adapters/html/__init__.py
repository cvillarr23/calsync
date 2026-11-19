"""The `html` adapter kind: fetch pages, select items with CSS, map them to events.

Both fetch modes end in the same place: selectolax parses the HTML, whether it was
served directly (static) or rendered by headless Chromium. Headless mode only
supplies the HTML.
"""

from app.adapters.html.page import HtmlPage
from app.adapters.html.result import FieldProblem, RunResult
from app.adapters.html.run import HtmlEngine, run_html

__all__ = ["FieldProblem", "HtmlEngine", "HtmlPage", "RunResult", "run_html"]
