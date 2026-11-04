"""build_pages.py: the GitHub Pages site. The landing page (site/) at the root and the Kunto dashboard,
built from the synthetic sample data, at /demo.

    python tools/build_pages.py [--out _site]

Kunto's page is a fragment (its live host adds the document head), so the demo is wrapped in a full HTML
document, topped with a bar that says it is a demo, and frozen as a snapshot dated SAMPLE_TODAY, the last
day of the sample data. The README's screenshots double as the landing page's images (img/).
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from kunto import build_kunto          # noqa: E402

SAMPLE_TODAY = "2026-11-04"
SITE = ROOT / "site"
SHOTS = ROOT / "docs" / "screenshots"
REPO_URL = "https://github.com/henrijantti/Fitness-Coach"
HEAD = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="description" content="The Kunto dashboard running on synthetic sample data.">\n'
        '<link rel="icon" href="../favicon.svg" type="image/svg+xml">\n'
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
    (demo / "index.html").write_text(HEAD + fragment.read_text(encoding="utf-8") + TAIL, encoding="utf-8")
    fragment.unlink()
    for f in SITE.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    (out / "img").mkdir(exist_ok=True)
    for f in SHOTS.glob("*.png"):
        shutil.copy2(f, out / "img" / f.name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {out}: landing page and demo/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
