import logging

import pytest
import yaml
from pydantic import ValidationError

from app.adapters.registry import AdapterRegistry
from app.db.engine import init_db, make_engine
from app.db.models import AdapterDef, User
from app.services.definition_store import DefinitionStore, load_row
from tests.adapters.conftest import HTML_DEF
from tests.support import PYTHON_DEF


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "data")
    sessions = init_db(engine)
    with sessions.begin() as db:
        db.add(User(id=1, email="a@example.com"))
        db.add(User(id=2, email="b@example.com"))
    yield sessions
    engine.dispose()


def add_row(sessions, data):
    with sessions.begin() as db:
        db.add(AdapterDef(id=data["id"], user_id=1, yaml=yaml.safe_dump(data), version=1))


def test_stored_definitions_feed_the_registry(sessions):
    add_row(sessions, HTML_DEF)
    registry = AdapterRegistry()
    registry.add_source(DefinitionStore(sessions).definitions)
    assert registry.get("rec-center", 1).name == "Rec center schedule"
    assert not registry.is_builtin("rec-center")


def test_stored_python_kind_is_rejected(sessions, caplog):
    add_row(sessions, PYTHON_DEF)
    add_row(sessions, HTML_DEF)
    with caplog.at_level(logging.WARNING):
        definitions = DefinitionStore(sessions).definitions(1)

    assert [d.id for d in definitions] == ["rec-center"]
    assert "sneaky" in caplog.text
    with sessions() as db, pytest.raises(ValidationError, match="built-in adapters"):
        load_row(db.get(AdapterDef, "sneaky"))


def test_unparseable_row_is_skipped(sessions):
    with sessions.begin() as db:
        db.add(AdapterDef(id="broken", user_id=1, yaml="id: [unclosed", version=1))
    assert DefinitionStore(sessions).definitions(1) == []


def test_other_users_definitions_are_hidden(sessions):
    add_row(sessions, HTML_DEF)
    assert DefinitionStore(sessions).definitions(2) == []
