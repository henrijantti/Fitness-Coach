import json
import pathlib
import re
import shutil
import subprocess

import pytest

from kunto import render

KUNTO = pathlib.Path(__file__).resolve().parents[1] / "kunto"
TEMPLATE = (KUNTO / "template.html").read_text(encoding="utf-8")
DATA_RE = re.compile(r'<script id="kunto-data" type="application/json">(.*?)</script>', re.S)


def embedded(page: str) -> dict:
    m = DATA_RE.search(page)
    assert m, "data block not found"
    return json.loads(m.group(1))


def test_render_injects_json_that_parses_back():
    model = {"a": 1, "b": ["x", None, 2.5], "c": {"d": "Mon 28 Sep"}}
    page = render.render("<p>x</p><script id=\"kunto-data\" type=\"application/json\">__KUNTO_DATA__</script>", model)
    assert embedded(page) == model


def test_render_cannot_break_out_of_the_script_element():
    evil = "</script><script>alert(1)</script><!-- & \u2028"
    page = render.render(TEMPLATE, {"overview": {}, "training": {"title": evil}})
    assert page.count("</script>") == TEMPLATE.count("</script>")
    assert "<script>alert(1)" not in page
    assert embedded(page)["training"]["title"] == evil


def test_render_needs_exactly_one_placeholder():
    with pytest.raises(render.TemplateError):
        render.render("<p>no slot</p>", {})
    with pytest.raises(render.TemplateError):
        render.render("__KUNTO_DATA__ __KUNTO_DATA__", {})


def test_em_dashes_are_scrubbed_and_nan_refused():
    assert render.scrub_dashes({"a": ["x \u2014 y", 3], "b": "\u2014"}) == {"a": ["x - y", 3], "b": "-"}
    assert "\u2014" not in render.to_script_json({"t": "Race \u2014"})
    with pytest.raises(ValueError):
        render.to_script_json({"v": float("nan")})


def test_medical_text_never_reaches_the_page():
    assert render.medical_hits("<p>Easy run, HR ≤145</p>") == []
    assert render.medical_hits(TEMPLATE) == []
    with pytest.raises(render.MedicalTextError, match="medication"):
        render.render(TEMPLATE, {"overview": {}, "training": {"title": "Medication day 4: keep it easy"}})


def test_private_terms_come_from_an_untracked_file(tmp_path, monkeypatch):
    """The deployment's own terms live in kunto/private-terms.txt (gitignored); comments and blanks are skipped."""
    f = tmp_path / "private-terms.txt"
    f.write_text("# one term per line\nSecret-Drug\n\n  cycle week \n", encoding="utf-8")
    monkeypatch.setattr(render, "PRIVATE_TERMS", f)
    assert render._private_terms() == ("secret-drug", "cycle week")
    monkeypatch.setattr(render, "PRIVATE_TERMS", tmp_path / "missing.txt")
    assert render._private_terms() == ()


# ---------- the real template ----------

def test_template_is_built_on_the_design_system():
    """The page carries kunto/design-system verbatim: the look and the behaviour change there, and page-only
    layout goes in the template's own last <style> block."""
    ds = KUNTO / "design-system" / "components"
    assert (ds / "bundle.css").read_text(encoding="utf-8").strip() in TEMPLATE
    js = (ds / "bundle.js").read_text(encoding="utf-8").strip()
    assert js.split("\n", 1)[1] in TEMPLATE                    # all but the file's own header comment
    for token in ("--primary: #5a5ad6", "family=Manrope", ':root:not([data-theme="light"])', ':root[data-theme="dark"]'):
        assert token in TEMPLATE, token


def test_template_is_an_artifact_fragment():
    """The artifact host wraps the page in its own document (charset, viewport), so the template brings no
    doctype, <html>, <head> or <body> and opens with its <title>."""
    assert TEMPLATE.startswith("<title>Kunto Dashboard</title>")
    assert not re.search(r"<!doctype|<(html|head|body)\b", TEMPLATE, re.I)


def test_template_loads_nothing_but_the_font_and_sends_nothing():
    """Health data rides on this page: the only outside address is Google Fonts (Manrope), and no code can
    fetch or post."""
    hosts = set(re.findall(r"https?://([^/\"'\s)]+)", TEMPLATE))
    assert hosts == {"fonts.googleapis.com", "fonts.gstatic.com", "www.w3.org"}      # w3.org = the SVG namespace
    assert not re.search(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts|eval)\b|new Function|"
                         r"new Image|@import|\ssrc\s*=", TEMPLATE)


def test_template_tabs_are_overview_training_and_gym():
    nav = re.search(r'<ul class="ca-nav">.*?</ul>', TEMPLATE, re.S).group(0)
    assert re.findall(r'<span class="ca-nav__text">(\w+)</span>', nav) == ["Overview", "Training", "Gym"]
    assert re.findall(r'data-tab="(\w+)"', nav) == re.findall(r'id="tab-(\w+)"', TEMPLATE) == ["overview", "training", "gym"]
    views = re.search(r'id="g-views">.*?</div>', TEMPLATE, re.S).group(0)
    assert re.findall(r'data-value="(\w+)"', views) == ["log", "calendar", "exercise"]      # the Gym tab's view chooser
    assert "Sample data" not in TEMPLATE and 'id="q"' not in TEMPLATE
    assert TEMPLATE.count(render.PLACEHOLDER) == 1


def test_template_has_no_em_dash():
    assert "\u2014" not in TEMPLATE


def test_hidden_is_only_toggled_on_html_elements():
    """An <svg> has no .hidden property: assigning it does nothing, so the empty gauge stayed on screen above
    "No readiness today". SVG elements are hidden with setAttribute('hidden', '') instead."""
    toggled = set(re.findall(r"\$\('([\w-]+)'\)\.hidden\s*=", TEMPLATE))
    svg_ids = set(re.findall(r'<svg[^>]*\bid="([\w-]+)"', TEMPLATE))
    assert "gauge" in svg_ids and toggled and not toggled & svg_ids
    assert "$('gauge').setAttribute('hidden', '')" in TEMPLATE


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_template_script_parses(tmp_path):
    scripts = re.findall(r"<script>(.*?)</script>", TEMPLATE, re.S)
    assert len(scripts) == 2                                   # the design system's engine, then the page
    for i, source in enumerate(scripts):
        js = tmp_path / f"kunto{i}.js"
        js.write_text(source, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
