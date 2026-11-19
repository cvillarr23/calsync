import json

from app.adapters.pipeline.cli import main
from tests.adapters.pipeline.fake_api import DEFINITION


def cli(fake_api, *extra):
    port = fake_api.rsplit(":", 1)[1]
    page_url = f"page_url=http://127.0.0.1:{port}/calendar"
    args = [str(DEFINITION), page_url, "--start", "2026-12-01", "--days", "21", "--allow-private"]
    return main([*args, *extra])


def test_prints_a_table(fake_api, capsys):
    assert cli(fake_api) == 0
    out = capsys.readouterr().out
    assert "2026-12-02 18:00  2026-12-02 19:30  Public Skate" in out
    assert out.strip().endswith("3 event(s)")


def test_prints_json(fake_api, capsys):
    assert cli(fake_api, "--json") == 0
    events = json.loads(capsys.readouterr().out)
    assert [e["title"] for e in events] == ["Public Skate", "Stick & Puck", "Figure Skating"]
    assert events[0]["start_utc"] == "2026-12-02 18:00:00+00:00"


def test_reports_errors(fake_api, capsys):
    port = fake_api.rsplit(":", 1)[1]
    assert main([str(DEFINITION), f"page_url=http://127.0.0.1:{port}/calendar"]) == 1
    assert "step 0 (http)" in capsys.readouterr().err
