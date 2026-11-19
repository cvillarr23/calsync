"""Adapter definition models: the source of truth for YAML/JSON definitions.

`parse_definition` is the entry point. It validates the shape with Pydantic,
then runs cross-field checks (template variables, `uid` fields, kind rules)
and reports every problem as a field-path error, e.g. `steps.3.http.url`.
"""

import re
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError
from selectolax.lexbor import LexborHTMLParser, SelectolaxError

from app.adapters import template

Loc = tuple[str | int, ...]
Problem = tuple[Loc, str, Any]


def _valid_template(text: str) -> str:
    template.parse(text)
    return text


def _compiled(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as err:
        raise ValueError(f"invalid regex: {err}") from None


def _valid_regex(pattern: str) -> str:
    _compiled(pattern)
    return pattern


def _capturing_regex(pattern: str) -> str:
    """Extraction takes the first capture group, so the regex must have one."""
    if _compiled(pattern).groups < 1:
        raise ValueError("regex needs a capture group; the first group is extracted")
    return pattern


def _valid_tz(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {name!r}") from None
    return name


def _valid_selector(selector: str) -> str:
    """Compile the selector now, so a typo fails when the definition is saved, not mid-run."""
    try:
        _SELECTOR_PROBE.css(selector)
    except SelectolaxError:
        raise ValueError(f"invalid CSS selector {selector!r}") from None
    return selector


_SELECTOR_PROBE = LexborHTMLParser("")

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
TemplateStr = Annotated[str, AfterValidator(_valid_template)]
Regex = Annotated[str, AfterValidator(_valid_regex)]
CaptureRegex = Annotated[str, AfterValidator(_capturing_regex)]
TzName = Annotated[str, AfterValidator(_valid_tz)]
Selector = Annotated[str, StringConstraints(min_length=1), AfterValidator(_valid_selector)]
JsonScalar = str | int | float | bool

MapFieldName = Literal["title", "start", "end", "date", "location", "description", "url"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _exactly_one(model: BaseModel, fields: tuple[str, ...]) -> None:
    present = [name for name in fields if getattr(model, name) is not None]
    if len(present) != 1:
        raise ValueError(f"set exactly one of: {', '.join(fields)}")


class Param(_Model):
    """A value the user supplies per source, e.g. the page URL."""

    type: Literal["url", "string", "int"] = "string"
    default: str | int | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _default_matches_type(self) -> "Param":
        if self.default is not None and isinstance(self.default, int) != (self.type == "int"):
            raise ValueError(f"default must be a {self.type}")
        return self


class FieldSpec(_Model):
    """How to read one event field from an item."""

    jsonpath: str | None = None
    selector: Selector | None = None
    from_context: Selector | None = Field(
        None, description="Selector matched against the nearest ancestor or preceding element."
    )
    attr: str | None = None
    regex: Regex | None = None
    strip: bool = False
    tz: TzName | None = None
    format: str | None = None
    time_range_regex: Regex | None = None
    default_duration_min: Annotated[int, Field(ge=1)] | None = None
    equals: JsonScalar | None = Field(None, description="For skip_if: skip items equal to this.")

    @model_validator(mode="after")
    def _one_source(self) -> "FieldSpec":
        _exactly_one(self, ("jsonpath", "selector", "from_context"))
        if self.attr is not None and self.jsonpath is not None:
            raise ValueError("attr only applies to selector or from_context")
        return self


class FieldMap(_Model):
    title: FieldSpec
    start: FieldSpec
    end: FieldSpec | None = None
    date: FieldSpec | None = None
    location: FieldSpec | None = None
    description: FieldSpec | None = None
    url: FieldSpec | None = None
    skip_if: FieldSpec | None = None


class HttpSpec(_Model):
    method: Literal["GET", "POST"] = "GET"
    url: TemplateStr
    headers: dict[str, TemplateStr] = {}
    json_: JsonValue | None = Field(None, alias="json")
    form: dict[str, TemplateStr] | None = None
    follow_redirects: bool = True

    @model_validator(mode="after")
    def _one_body(self) -> "HttpSpec":
        if self.json_ is not None and self.form is not None:
            raise ValueError("set at most one of: json, form")
        for text in template.strings(self.json_):
            _valid_template(text)
        return self


class ExtractSpec(_Model):
    regex: CaptureRegex | None = None
    jsonpath: str | None = None
    css: Selector | None = None
    as_: Identifier | None = Field(
        None, alias="as", description="Variable to save into; omitted, it replaces the document."
    )
    parse: Literal["json"] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "ExtractSpec":
        _exactly_one(self, ("regex", "jsonpath", "css"))
        return self


class PaginateSpec(_Model):
    window: Literal["lookahead"] = "lookahead"
    step_days: Annotated[int, Field(ge=1, le=366)]
    as_: Identifier = Field(alias="as")


class ItemsSpec(_Model):
    jsonpath: str | None = None
    css: Selector | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "ItemsSpec":
        _exactly_one(self, ("jsonpath", "css"))
        return self


STEP_KINDS = ("http", "extract", "paginate", "items")


class Step(_Model):
    """One pipeline step: a mapping with exactly one of http, extract, paginate, items."""

    model_config = ConfigDict(
        json_schema_extra={"minProperties": 1, "maxProperties": 1}, extra="forbid"
    )

    http: HttpSpec | None = None
    extract: ExtractSpec | None = None
    paginate: PaginateSpec | None = None
    items: ItemsSpec | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> "Step":
        _exactly_one(self, STEP_KINDS)
        return self

    @property
    def kind(self) -> str:
        return next(name for name in STEP_KINDS if getattr(self, name) is not None)


def _step_counts(steps: list[Step]) -> list[Step]:
    kinds = [step.kind for step in steps]
    if kinds.count("items") != 1:
        raise ValueError("a pipeline needs exactly one items step")
    if kinds.count("paginate") > 1:
        raise ValueError("a pipeline can have at most one paginate step")
    return steps


class HtmlFetch(_Model):
    url: TemplateStr | None = Field(
        None, description="The page to read; omit it when pagination.mode is url_template."
    )
    mode: Literal["static", "headless"] = "static"
    wait_for: Selector | None = None
    user_agent: str | None = None


class Pagination(_Model):
    mode: Literal["none", "url_template", "click_next"] = "none"
    url_template: TemplateStr | None = Field(None, description="url_template mode; knows {{date}}.")
    step_days: Annotated[int, Field(ge=1, le=366)] | None = None
    selector: Selector | None = Field(None, description="click_next mode: the next button.")
    max_pages: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def _fields_match_mode(self) -> "Pagination":
        required = _PAGINATION_FIELDS[self.mode]
        missing = [name for name in required if getattr(self, name) is None]
        extra = [name for name in _ALL_PAGINATION_FIELDS - set(required) if getattr(self, name)]
        if missing or extra:
            raise ValueError(f"mode {self.mode} takes exactly: {', '.join(required) or 'nothing'}")
        return self


_PAGINATION_FIELDS = {
    "none": (),
    "url_template": ("url_template", "step_days"),
    "click_next": ("selector", "max_pages"),
}
_ALL_PAGINATION_FIELDS = {name for fields in _PAGINATION_FIELDS.values() for name in fields}


class _Definition(_Model):
    id: Slug
    version: Annotated[int, Field(ge=1)]
    name: Annotated[str, StringConstraints(min_length=1)]
    params: dict[Identifier, Param] = {}
    match_hosts: list[str] = []
    uid: list[MapFieldName] | None = Field(
        None, description="Map fields hashed into the event uid."
    )


class PipelineDefinition(_Definition):
    kind: Literal["pipeline"]
    steps: Annotated[list[Step], AfterValidator(_step_counts)]
    map: FieldMap


class HtmlDefinition(_Definition):
    kind: Literal["html"]
    fetch: HtmlFetch
    pagination: Pagination = Pagination()
    item: Selector
    map: FieldMap


class PythonDefinition(_Definition):
    """Built-in only: hands the run to a registered function."""

    kind: Literal["python"]
    entrypoint: Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")]
    map: FieldMap | None = None


AdapterDefinition = Annotated[
    PipelineDefinition | HtmlDefinition | PythonDefinition, Field(discriminator="kind")
]
_KINDS: dict[str, type[_Definition]] = {
    "pipeline": PipelineDefinition,
    "html": HtmlDefinition,
    "python": PythonDefinition,
}
_ADAPTER: TypeAdapter[AdapterDefinition] = TypeAdapter(AdapterDefinition)


def parse_definition(data: Any, *, builtin: bool = False) -> AdapterDefinition:
    """Validate a definition, raising `ValidationError` with field-path locations.

    Only built-in definitions may use the python kind.
    """
    model = _model_for(data)
    definition = model.model_validate(data)
    problems = list(_problems(definition, builtin=builtin))
    if problems:
        raise _validation_error(problems)
    return definition


def definition_json_schema() -> dict[str, Any]:
    """The JSON Schema for adapter definitions, as served at /schema/adapter.json."""
    schema = _ADAPTER.json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "calsync adapter definition",
        **schema,
    }


def error_list(err: ValidationError) -> list[dict[str, str]]:
    """Flatten errors into `{"loc": "steps.3.http.url", "msg": ...}` rows for API and UI."""
    return [{"loc": _dotted(e["loc"]), "msg": e["msg"]} for e in err.errors()]


def _dotted(loc: Loc) -> str:
    return ".".join(str(part) for part in loc)


def _model_for(data: Any) -> type[_Definition]:
    """Pick the model by `kind` up front, so error paths don't carry a union tag."""
    kind = data.get("kind") if isinstance(data, Mapping) else None
    if kind not in _KINDS:
        allowed = ", ".join(_KINDS)
        raise _validation_error([(("kind",), f"kind must be one of: {allowed}", kind)])
    return _KINDS[kind]


def _problems(definition: _Definition, *, builtin: bool) -> Iterator[Problem]:
    if isinstance(definition, PythonDefinition) and not builtin:
        yield ("kind",), "the python kind is only available to built-in adapters", "python"
    yield from _uid_problems(definition)
    if isinstance(definition, PipelineDefinition):
        yield from _pipeline_template_problems(definition)
    if isinstance(definition, HtmlDefinition):
        yield from _html_problems(definition)


def _uid_problems(definition: _Definition) -> Iterator[Problem]:
    field_map = getattr(definition, "map", None)
    for index, name in enumerate(definition.uid or []):
        if field_map is None or getattr(field_map, name) is None:
            yield ("uid", index), f"uid field {name!r} is not in map", name


def _pipeline_template_problems(definition: PipelineDefinition) -> Iterator[Problem]:
    """Each step's templates may read params and variables saved by earlier steps."""
    known = set(definition.params)
    for index, step in enumerate(definition.steps):
        for loc, text in _step_templates(step):
            yield from _template_problem(("steps", index, *loc), text, known)
        known |= _step_outputs(step)


def _step_templates(step: Step) -> Iterator[tuple[Loc, str]]:
    if step.http is None:
        return
    yield ("http", "url"), step.http.url
    for key, value in step.http.headers.items():
        yield ("http", "headers", key), value
    for key, value in (step.http.form or {}).items():
        yield ("http", "form", key), value
    for text in template.strings(step.http.json_):
        yield ("http", "json"), text


def _step_outputs(step: Step) -> set[str]:
    spec = step.extract or step.paginate
    return {spec.as_} if spec is not None and spec.as_ else set()


def _html_problems(definition: HtmlDefinition) -> Iterator[Problem]:
    params = set(definition.params)
    yield from _page_url_problems(definition)
    if definition.fetch.url is not None:
        yield from _template_problem(("fetch", "url"), definition.fetch.url, params)
    if definition.pagination.url_template:
        loc = ("pagination", "url_template")
        yield from _template_problem(loc, definition.pagination.url_template, params | {"date"})
    if definition.fetch.mode != "headless":
        yield from _headless_only_problems(definition)


def _page_url_problems(definition: HtmlDefinition) -> Iterator[Problem]:
    """Each mode has one URL source: url_template builds every page's URL, fetch.url otherwise."""
    templated = definition.pagination.mode == "url_template"
    if templated and definition.fetch.url is not None:
        yield ("fetch", "url"), "omit fetch.url; url_template gives each page's URL", None
    if not templated and definition.fetch.url is None:
        yield ("fetch", "url"), "fetch.url is required unless pagination.mode is url_template", None


def _headless_only_problems(definition: HtmlDefinition) -> Iterator[Problem]:
    if definition.pagination.mode == "click_next":
        yield ("pagination", "mode"), "click_next needs fetch.mode: headless", "click_next"
    if definition.fetch.wait_for is not None:
        yield (
            ("fetch", "wait_for"),
            "wait_for needs fetch.mode: headless",
            definition.fetch.wait_for,
        )


def _template_problem(loc: Loc, text: str, known: set[str]) -> Iterator[Problem]:
    try:
        template.check(text, known)
    except template.TemplateError as err:
        yield loc, str(err), text


def _validation_error(problems: list[Problem]) -> ValidationError:
    line_errors = [
        {
            "type": PydanticCustomError("definition", "{msg}", {"msg": msg}),
            "loc": loc,
            "input": value,
        }
        for loc, msg, value in problems
    ]
    return ValidationError.from_exception_data("AdapterDefinition", line_errors)
