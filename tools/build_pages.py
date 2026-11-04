"""build_pages.py: the GitHub Pages site. The landing page (site/) at the root and the Kunto dashboard,
built from the synthetic sample data, at /demo.

    python tools/build_pages.py [--out _site]

Kunto's page is a fragment (its live host adds the document head), so the demo is wrapped in a full HTML
document, topped with a bar that says it is a demo, and frozen as a snapshot dated SAMPLE_TODAY, the last
day of the sample data. Its web font is swapped for the self-hosted copy in site/fonts/, so the site makes no
third-party requests. site/ is copied whole (img/, fonts/). tools/shoot_pages.py re-takes all the pictures.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from kunto import build_kunto          # noqa: E402

SAMPLE_TODAY = "2026-11-04"
SITE = ROOT / "site"
REPO_URL = "https://github.com/henrijantti/Fitness-Coach"
SITE_URL = "https://henrijantti.github.io/Fitness-Coach/"
DEMO_TITLE = "Kunto demo: a fictional athlete's season"
DEMO_TEXT = "The Kunto training dashboard running on synthetic sample data: recovery, the season plan and the gym log."
GOOGLE_FONTS = re.compile(r'<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\n?')
HEAD = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'<title>{DEMO_TITLE}</title>\n'
        f'<meta name="description" content="{DEMO_TEXT}">\n'
        f'<link rel="canonical" href="{SITE_URL}demo/">\n'
        '<meta property="og:type" content="website">\n<meta property="og:site_name" content="Kunto">\n'
        f'<meta property="og:title" content="{DEMO_TITLE}">\n<meta property="og:description" content="{DEMO_TEXT}">\n'
        f'<meta property="og:image" content="{SITE_URL}og.png">\n'
        '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
        f'<meta property="og:url" content="{SITE_URL}demo/">\n<meta name="twitter:card" content="summary_large_image">\n'
        '<link rel="icon" href="../favicon.svg" type="image/svg+xml">\n'
        '<link rel="apple-touch-icon" href="../apple-touch-icon.png">\n'
        '<link rel="preload" href="../fonts/manrope-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
        '<link rel="stylesheet" href="../fonts/manrope.css">\n'
        '<style>body{margin:0}.demo-bar{position:sticky;top:0;z-index:1000;display:flex;flex-wrap:wrap;gap:6px 14px;'
        'align-items:center;justify-content:center;padding:9px 16px;background:#191b2b;color:#fff;text-align:center;'
        'font:600 13px/1.4 Manrope,system-ui,-apple-system,"Segoe UI",sans-serif}.demo-bar b{background:#5a5ad6;'
        'border-radius:999px;padding:2px 9px;font-size:11px;letter-spacing:.04em}.demo-bar a{color:#c9c9ff;'
        'text-decoration:none}.demo-bar a:hover{text-decoration:underline}</style>\n</head>\n<body>\n'
        '<div class="demo-bar" role="note"><b>DEMO</b><span>Synthetic data for a fictional athlete.</span>'
        f'<a href="../">About Kunto</a><a href="{REPO_URL}">Source on GitHub</a></div>\n')
TAIL = "\n</body>\n</html>\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the GitHub Pages site.")
    ap.add_argument("--out", default=str(ROOT / "_site"))
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    demo = out / "demo"
    fragment = demo / "fragment.html"
    code = build_kunto.main(["--root", str(ROOT), "--today", SAMPLE_TODAY, "--demo", "--out", str(fragment)])
    if code:
        return code
    body = GOOGLE_FONTS.sub("", fragment.read_text(encoding="utf-8"))
    (demo / "index.html").write_text(HEAD + body + TAIL, encoding="utf-8")
    fragment.unlink()
    shutil.copytree(SITE, out, dirs_exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {out}: landing page and demo/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
