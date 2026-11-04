"""The GitHub Pages site: the landing page at the root, the dashboard demo at /demo."""
import json
import re
from html.parser import HTMLParser

from tools import build_pages


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])


def local_refs(page: str) -> list[str]:
    p = Refs()
    p.feed(page)
    return [r.split("#")[0] for r in p.refs if not r.startswith(("http", "#", "mailto:")) and r.split("#")[0]]


def test_pages_site_has_the_landing_page_and_the_demo(tmp_path):
    assert build_pages.main(["--out", str(tmp_path)]) == 0
    demo = (tmp_path / "demo" / "index.html").read_text(encoding="utf-8")
    assert demo.startswith("<!doctype html>") and '<meta charset="utf-8">' in demo and demo.rstrip().endswith("</html>")
    model = json.loads(re.search(r'<script id="kunto-data" type="application/json">(.*?)</script>', demo, re.S).group(1))
    assert model["meta"] == {**model["meta"], "today": build_pages.SAMPLE_TODAY, "demo": True}
    assert 'href="../"' in demo and "Synthetic data" in demo
    assert not (tmp_path / "demo" / "fragment.html").exists() and (tmp_path / ".nojekyll").exists()


def test_every_local_link_on_the_site_resolves(tmp_path):
    assert build_pages.main(["--out", str(tmp_path)]) == 0
    for page in (tmp_path / "index.html", tmp_path / "demo" / "index.html"):
        for ref in local_refs(page.read_text(encoding="utf-8")):
            target = (page.parent / ref).resolve()
            assert (target / "index.html" if ref.endswith("/") else target).exists(), f"{page.name}: {ref}"


def test_landing_page_carries_no_real_training_numbers():
    page = (build_pages.SITE / "index.html").read_text(encoding="utf-8")
    assert "synthetic" in page.lower()
    assert not re.search(r"\b\d+(\.\d+)? ?kg\b|\bbpm\b|\bms\b", page)
