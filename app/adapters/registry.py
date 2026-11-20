"""Where adapter definitions come from: built-in YAML files, user definitions and python adapters.

Built-ins load read-only from `adapters/*.yaml` at the repo root. User definitions
live in the database; the store plugs in through `add_source`.
"""

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.adapters.schema import AdapterDefinition, PythonDefinition, error_list, parse_definition

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "adapters"

DefinitionSource = Callable[[int], Iterable[AdapterDefinition]]
"""Returns one user's definitions: `source(user_id)`."""

PYTHON_ADAPTERS: dict[str, Callable[..., Any]] = {}
"""Functions that python-kind definitions may name, keyed by `module:function`."""


def python_adapter(func: Callable[..., Any]) -> Callable[..., Any]:
    """Register a function as a python-kind adapter entrypoint."""
    PYTHON_ADAPTERS[f"{func.__module__}:{func.__qualname__}"] = func
    return func


class RegistryError(RuntimeError):
    """A built-in definition file is invalid or clashes with another."""


class AdapterRegistry:
    def __init__(self) -> None:
        self._builtins: dict[str, AdapterDefinition] = {}
        self._sources: list[DefinitionSource] = []

    @classmethod
    def with_builtins(cls, path: Path = BUILTIN_DIR) -> "AdapterRegistry":
        registry = cls()
        registry.load_builtin_dir(path)
        return registry

    def load_builtin_dir(self, path: Path) -> None:
        """Load every `*.yaml` / `*.yml` file; a missing directory means no built-ins."""
        for file in _definition_files(path):
            self._add_builtin(file, _load_file(file))

    def add_source(self, source: DefinitionSource) -> None:
        """Add a provider of non-built-in definitions, such as the user definition store."""
        self._sources.append(source)

    def get(self, adapter_id: str, user_id: int | None = None) -> AdapterDefinition | None:
        """Look up a built-in, or one of `user_id`'s definitions; built-ins win on a clash.

        Without a user, only built-ins are visible.
        """
        if adapter_id in self._builtins:
            return self._builtins[adapter_id]
        return next((d for d in self._from_sources(user_id) if d.id == adapter_id), None)

    def all(self, user_id: int | None = None) -> list[AdapterDefinition]:
        """The built-ins plus `user_id`'s own definitions."""
        user = [d for d in self._from_sources(user_id) if d.id not in self._builtins]
        return [*self._builtins.values(), *user]

    def is_builtin(self, adapter_id: str) -> bool:
        return adapter_id in self._builtins

    def _add_builtin(self, file: Path, definition: AdapterDefinition) -> None:
        if definition.id in self._builtins:
            raise RegistryError(f"{file.name}: duplicate adapter id {definition.id!r}")
        self._builtins[definition.id] = definition

    def _from_sources(self, user_id: int | None) -> Iterator[AdapterDefinition]:
        if user_id is None:
            return
        for source in self._sources:
            yield from source(user_id)


def _definition_files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.suffix in {".yaml", ".yml"})


def _load_file(file: Path) -> AdapterDefinition:
    try:
        definition = parse_definition(yaml.safe_load(file.read_text()), builtin=True)
    except yaml.YAMLError as err:
        raise RegistryError(f"{file.name}: invalid YAML: {err}") from None
    except ValidationError as err:
        raise RegistryError(f"{file.name}: {_describe(err)}") from None
    _check_entrypoint(file, definition)
    return definition


def _check_entrypoint(file: Path, definition: AdapterDefinition) -> None:
    if isinstance(definition, PythonDefinition) and definition.entrypoint not in PYTHON_ADAPTERS:
        raise RegistryError(f"{file.name}: entrypoint {definition.entrypoint!r} is not registered")


def _describe(err: ValidationError) -> str:
    return "; ".join(f"{row['loc'] or '(root)'}: {row['msg']}" for row in error_list(err))
