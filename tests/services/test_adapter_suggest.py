from app.adapters.schema import parse_definition
from app.services.adapter_suggest import suggest_adapters
from tests.adapters.conftest import HTML_DEF


def definition(id_, hosts):
    return parse_definition({**HTML_DEF, "id": id_, "match_hosts": hosts})


DEFS = [definition("ems", ["ems.example.edu"]), definition("any-club", ["*.clubs.example"])]


def test_exact_and_subdomain_hosts_match():
    assert [d.id for d in suggest_adapters(DEFS, "https://ems.example.edu/x")] == ["ems"]
    assert [d.id for d in suggest_adapters(DEFS, "https://WWW.EMS.example.edu")] == ["ems"]
    assert [d.id for d in suggest_adapters(DEFS, "https://chess.clubs.example/")] == ["any-club"]


def test_lookalike_hosts_and_junk_do_not_match():
    assert suggest_adapters(DEFS, "https://notems.example.edu/") == []
    assert suggest_adapters(DEFS, "not a url") == []
