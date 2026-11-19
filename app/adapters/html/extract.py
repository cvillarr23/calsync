"""Selecting items from HTML with selectolax and reading their fields."""

from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.adapters.html.page import HtmlPage
from app.adapters.html.result import FieldProblem, RunResult
from app.adapters.mapping import FieldFailure, Reader, Window, map_item
from app.adapters.schema import FieldSpec, HtmlDefinition


def extract(definition: HtmlDefinition, pages: list[HtmlPage], window: Window) -> RunResult:
    """Map every item on every page, keeping the first event for each uid."""
    result, seen = RunResult(), set()
    for page in pages:
        tree = LexborHTMLParser(page.html)
        contexts = _ContextIndex(tree)
        for index, node in enumerate(tree.css(definition.item)):
            read = _reader(node, page.url, contexts)
            try:
                event = map_item(definition.map, read, window, definition.uid)
            except FieldFailure as failure:
                result.problems.append(FieldProblem(page.url, index, failure.field, failure.msg))
                continue
            if event is not None and event.uid not in seen:
                seen.add(event.uid)
                result.events.append(event)
    return result


class _ContextIndex:
    """Finds `from_context` matches: the last match that starts before the item.

    In document order, an element's ancestors and everything before it come
    first, so this is the nearest ancestor or preceding element, such as the date
    header above a cell in a week grid.
    """

    def __init__(self, tree: LexborHTMLParser) -> None:
        self._tree = tree
        self._order = {node.mem_id: n for n, node in enumerate(_all_elements(tree))}
        self._matches: dict[str, list[tuple[int, LexborNode]]] = {}

    def before(self, node: LexborNode, selector: str) -> LexborNode | None:
        position = self._order[node.mem_id]
        found = None
        for order, match in self._ordered_matches(selector):
            if order >= position:
                break
            found = match
        return found

    def _ordered_matches(self, selector: str) -> list[tuple[int, LexborNode]]:
        if selector not in self._matches:
            matches = [(self._order[m.mem_id], m) for m in self._tree.css(selector)]
            self._matches[selector] = sorted(matches, key=lambda pair: pair[0])
        return self._matches[selector]


def _all_elements(tree: LexborHTMLParser) -> list[LexborNode]:
    root = tree.root
    return [] if root is None else list(root.traverse(include_text=False))


def _reader(node: LexborNode, page_url: str, contexts: _ContextIndex) -> Reader:
    """Reads fields from one item node: `selector` inside it, or `from_context` before it."""

    def read(spec: FieldSpec, name: str) -> str | None:
        found = _field_node(node, spec, contexts)
        if found is None:
            return None
        value = found.attributes.get(spec.attr) if spec.attr else _text(found)
        return urljoin(page_url, value) if name == "url" and value else value

    return read


def _field_node(node: LexborNode, spec: FieldSpec, contexts: _ContextIndex) -> LexborNode | None:
    if spec.from_context is not None:
        return contexts.before(node, spec.from_context)
    return node.css_first(spec.selector or "")


def _text(node: LexborNode) -> str:
    """The node's text with runs of whitespace collapsed to single spaces."""
    return " ".join(node.text(deep=True, separator=" ").split())
