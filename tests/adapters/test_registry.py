import pytest
import yaml

from app.adapters.registry import (
    PYTHON_ADAPTERS,
    AdapterRegistry,
    RegistryError,
    python_adapter,
)
from app.adapters.schema import parse_definition


def write(path, name, data):
    (path / name).write_text(yaml.safe_dump(data))


def test_repo_ships_no_builtins():
    assert AdapterRegistry.with_builtins().all() == []


def test_missing_dir_is_empty(tmp_path):
    assert AdapterRegistry.with_builtins(tmp_path / "nope").all() == []


def test_loads_yaml_files(tmp_path, uw_ems, html_def):
    write(tmp_path, "uw.yaml", uw_ems)
    write(tmp_path, "rec.yml", html_def)
    (tmp_path / "notes.txt").write_text("ignored")
    registry = AdapterRegistry.with_builtins(tmp_path)
    assert sorted(d.id for d in registry.all()) == ["rec-center", "uw-ems"]
    assert registry.is_builtin("uw-ems")


def test_bad_file_names_file_and_field(tmp_path, uw_ems):
    uw_ems["steps"][0]["http"]["urll"] = "x"
    write(tmp_path, "broken.yaml", uw_ems)
    with pytest.raises(RegistryError, match=r"broken\.yaml: steps\.0\.http\.urll"):
        AdapterRegistry.with_builtins(tmp_path)


def test_invalid_yaml(tmp_path):
    (tmp_path / "bad.yaml").write_text("id: [unclosed")
    with pytest.raises(RegistryError, match="bad.yaml: invalid YAML"):
        AdapterRegistry.with_builtins(tmp_path)


def test_duplicate_ids_rejected(tmp_path, uw_ems):
    write(tmp_path, "a.yaml", uw_ems)
    write(tmp_path, "b.yaml", uw_ems)
    with pytest.raises(RegistryError, match="b.yaml: duplicate adapter id 'uw-ems'"):
        AdapterRegistry.with_builtins(tmp_path)


def test_user_definitions_come_from_sources(tmp_path, uw_ems, html_def):
    write(tmp_path, "uw.yaml", uw_ems)
    registry = AdapterRegistry.with_builtins(tmp_path)
    shadow = parse_definition({**html_def, "id": "uw-ems"})
    mine = parse_definition(html_def)
    registry.add_source(lambda: [shadow, mine])
    assert registry.get("rec-center") is mine
    assert registry.get("uw-ems").kind == "pipeline"
    assert [d.id for d in registry.all()] == ["uw-ems", "rec-center"]
    assert registry.get("missing") is None


def sample_adapter():
    return []


PYTHON_DEF = {"id": "odd", "version": 1, "name": "Odd", "kind": "python"}


def test_python_entrypoint_must_be_registered(tmp_path):
    write(tmp_path, "odd.yaml", {**PYTHON_DEF, "entrypoint": "nowhere:run"})
    with pytest.raises(RegistryError, match="'nowhere:run' is not registered"):
        AdapterRegistry.with_builtins(tmp_path)


def test_registered_python_adapter_loads(tmp_path, monkeypatch):
    monkeypatch.setattr("app.adapters.registry.PYTHON_ADAPTERS", dict(PYTHON_ADAPTERS))
    python_adapter(sample_adapter)
    entrypoint = "tests.adapters.test_registry:sample_adapter"
    write(tmp_path, "odd.yaml", {**PYTHON_DEF, "entrypoint": entrypoint})
    assert AdapterRegistry.with_builtins(tmp_path).get("odd").entrypoint == entrypoint
