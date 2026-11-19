"""The `pipeline` adapter kind: http → extract → paginate → items → map.

Steps run in order over the source's params and a current document
(`steps.py`); `paginate` repeats the steps after it once per date in the
window. Each item is read with JSONPath (`read.py`) and mapped to an event by
the shared `app.adapters.mappers`. `python -m app.adapters.pipeline` runs a
definition file.
"""

from app.adapters.pipeline.errors import ParamError, StepError
from app.adapters.pipeline.params import resolve_params
from app.adapters.pipeline.result import ItemProblem, PipelineResult
from app.adapters.pipeline.run import PipelineEngine, run_pipeline

__all__ = [
    "ItemProblem",
    "ParamError",
    "PipelineEngine",
    "PipelineResult",
    "StepError",
    "resolve_params",
    "run_pipeline",
]
