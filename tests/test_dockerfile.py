import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_base_image_matches_locked_playwright():
    """Playwright's browser builds are tied to its package version, so the two must agree."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    image_version = re.search(r"^ARG PLAYWRIGHT_VERSION=(\S+)$", dockerfile, re.M).group(1)
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = next(p["version"] for p in lock["package"] if p["name"] == "playwright")
    assert image_version == locked
