import pytest

from app.services.error_hints import definition_hint, run_hint


@pytest.mark.parametrize(
    "msg, phrase",
    [
        ("items must be the last step", "Steps run top to bottom"),
        ("paginate repeats the steps after it, so an http step must follow it", "Steps run"),
        ("invalid JSONPath: Parse error", "JSONPath starts"),
        ("invalid CSS selector 'li['", "CSS selector"),
        ("regex needs a capture group; the first group is extracted", "capture group"),
        ("unknown variable(s): nope", "earlier steps"),
    ],
)
def test_definition_hints(msg, phrase):
    assert phrase in definition_hint(msg).text


@pytest.mark.parametrize(
    "error, phrase",
    [
        ("the adapter returned no events, so nothing was removed; check", "kept the stored"),
        ("no event could be read: item 0: start: matched nothing", "required field"),
        ("step 3 (http): POST failed with 500", "numbered from 0"),
        ("rink.local resolves to non-public address 10.0.0.2", "CALSYNC_FETCH_ALLOW_PRIVATE"),
    ],
)
def test_run_hints(error, phrase):
    assert phrase in run_hint(error).text


def test_unknown_messages_have_no_hint():
    assert definition_hint("field required") is None
    assert run_hint(None) is None
    assert run_hint("something else") is None


def test_hint_links_to_the_docs():
    assert definition_hint("items must be the last step").url.endswith(
        "adapters/pipeline/#step-order"
    )
