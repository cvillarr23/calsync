from app.services.yaml_lines import line_for

TEXT = """\
# comment
id: x
steps:
  - http:
      url: "{{u}}"
  - items:
      jsonpath: "$["
map:
  title: {selector: h3}
"""


def test_nested_paths():
    assert line_for(TEXT, "steps.0.http.url") == 5
    assert line_for(TEXT, "steps.1.items.jsonpath") == 7
    assert line_for(TEXT, "map.title.selector") == 9


def test_missing_field_points_at_its_parent():
    assert line_for(TEXT, "map.start") == 9
    assert line_for(TEXT, "steps.9") == 4


def test_root_and_bad_yaml():
    assert line_for(TEXT, "") == 2
    assert line_for("id: [unclosed", "id") is None
