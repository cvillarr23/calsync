from app.adapters.schema import parse_definition
from app.services.preview import ScrapeCache
from tests.adapters.conftest import HTML_DEF


def test_entries_expire_and_keys_follow_inputs():
    now = [0.0]
    cache = ScrapeCache(ttl_s=10, clock=lambda: now[0])
    definition = parse_definition(HTML_DEF)
    key = ScrapeCache.key(definition, {"url": "https://a.example"}, 30)
    cache.put(key, [])
    assert cache.get(key) == []
    assert cache.get(ScrapeCache.key(definition, {"url": "https://b.example"}, 30)) is None
    assert cache.get(ScrapeCache.key(definition, {"url": "https://a.example"}, 31)) is None
    now[0] = 11
    assert cache.get(key) is None
