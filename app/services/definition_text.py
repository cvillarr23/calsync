"""Turning adapter definition text (YAML or JSON) into data, and data back into YAML."""

import json
from typing import Any

import yaml


class DefinitionTextError(ValueError):
    """A definition body isn't valid YAML or JSON, or isn't a mapping."""


def load_yaml(text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise DefinitionTextError(f"invalid YAML: {err}") from None
    if not isinstance(data, dict):
        raise DefinitionTextError("a definition must be a YAML mapping")
    return data


def load_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise DefinitionTextError(f"invalid JSON: {err}") from None
    if not isinstance(data, dict):
        raise DefinitionTextError("a definition must be a JSON object")
    return data


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
