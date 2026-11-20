"""Finding the line a validation error's field path points at, in the YAML the user wrote."""

import yaml
from yaml.nodes import MappingNode, Node, SequenceNode


def line_for(text: str, loc: str) -> int | None:
    """The 1-based line of `loc` (e.g. `steps.3.http.url`), or of its nearest existing parent.

    Missing fields have no line of their own, so the error points at the mapping
    that should hold them. Returns None when the text isn't YAML.
    """
    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return None
    if node is None:
        return None
    for part in loc.split(".") if loc else []:
        child = _child(node, part)
        if child is None:
            break
        node = child
    return node.start_mark.line + 1


def _child(node: Node, part: str) -> Node | None:
    if isinstance(node, MappingNode):
        return next((value for key, value in node.value if key.value == part), None)
    if isinstance(node, SequenceNode) and part.isdigit() and int(part) < len(node.value):
        return node.value[int(part)]
    return None
