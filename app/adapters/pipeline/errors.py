"""Errors a pipeline run raises; each says where in the definition it went wrong."""

from app.adapters.events import AdapterRunError

# TODO: reuse app/adapters/html/extract.py so pipelines can select with css too.
CSS_UNSUPPORTED = "css is not supported in pipeline definitions yet"


class ParamError(AdapterRunError):
    """The source's params don't fit the definition."""


class StepError(AdapterRunError):
    """A pipeline step failed. The message names the step's index and kind."""

    def __init__(self, index: int, kind: str, message: str) -> None:
        super().__init__(f"step {index} ({kind}): {message}")
        self.index = index
        self.kind = kind
