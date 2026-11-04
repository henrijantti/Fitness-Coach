"""shoot_pages.py: re-take every picture the landing page, the README and the share card use, from a built site.

    python tools/build_pages.py --out _site
    python tools/shoot_pages.py [--site _site] [--chromium PATH]

A developer tool, not part of the Pages build: it needs `pip install playwright pillow` and a Chromium
(`--chromium` points at one when Playwright's own download is missing). Run it after the sample data, the
plan or the dashboard's look changes, then commit what it writes:

    site/img/*.webp            the landing page's hero and feature crops, light and dark
    docs/screenshots/*.png     the README's three phone shots (also the landing page's fallback img/)
    site/og.png                the 1200×630 share image, from tools/og.html
    site/apple-touch-icon.png  the 180×180 home-screen icon, from site/favicon.svg
"""
from __future__ import annotations

import argparse
import io
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HIDE_BAR = ".demo-bar{display:none!important}"


def _webp(png: bytes, out: pathlib.Path, width: int) -> None:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(out, "WEBP", quality=80)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Re-take the landing page, README and share-card pictures.")
    ap.add_argument("--site", default=str(ROOT / "_site"))
    ap.add_argument("--chromium", help="a Chromium executable, when Playwright's own is not installed")
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright
    site = pathlib.Path(a.site).resolve()
    demo = (site / "demo" / "index.html").as_uri()
    img = ROOT / "site" / "img"
    img.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": a.chromium} if a.chromium else {}))
        for scheme in ("light", "dark"):
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=2, color_scheme=scheme)
            page = ctx.new_page()
            page.goto(demo, wait_until="networkidle")
            page.add_style_tag(content=HIDE_BAR)
            page.wait_for_timeout(400)
            _webp(page.screenshot(), img / f"desk-overview-{scheme}.webp", 1600)
            _webp(page.locator("#ready-card").screenshot(), img / f"f-ready-{scheme}.webp", 1100)
            page.click('.ca-nav__item[data-tab="training"]')
            page.wait_for_timeout(300)
            box = page.locator("#tp-week").bounding_box()
            _webp(page.screenshot(clip={**box, "height": 560}), img / f"f-week-{scheme}.webp", 1100)
            page.click('.ca-nav__item[data-tab="gym"]')
            page.wait_for_timeout(300)
            box = page.locator("section.ca-card:visible").first.bounding_box()
            _webp(page.screenshot(clip={**box, "height": 560}), img / f"f-gym-{scheme}.webp", 1100)
            ctx.close()
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme=scheme,
                                      is_mobile=True, has_touch=True)
            page = ctx.new_page()
            page.goto(demo, wait_until="networkidle")
            page.add_style_tag(content=HIDE_BAR)
            page.wait_for_timeout(400)
            _webp(page.screenshot(), img / f"phone-overview-{scheme}.webp", 600)
            if scheme == "light":
                for tab in ("overview", "training", "gym"):
                    page.click(f'[data-tab="{tab}"] >> visible=true')
                    page.wait_for_timeout(300)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(ROOT / "docs" / "screenshots" / f"phone-{tab}.png"))
            ctx.close()
        # the share card and the touch icon render inside the built site, so their relative paths resolve
        shutil.copy2(ROOT / "tools" / "og.html", site / "_og.html")
        shutil.copytree(img, site / "img", dirs_exist_ok=True)
        try:
            ctx = browser.new_context(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
            page = ctx.new_page()
            page.goto((site / "_og.html").as_uri(), wait_until="networkidle")
            page.wait_for_timeout(300)
            page.screenshot(path=str(ROOT / "site" / "og.png"))
            page.set_viewport_size({"width": 180, "height": 180})
            page.set_content('<body style="margin:0;background:#ffffff;display:grid;place-items:center;height:180px">'
                             f'<img src="{(site / "favicon.svg").as_uri()}" width="132" height="132"></body>')
            page.wait_for_timeout(200)
            page.screenshot(path=str(ROOT / "site" / "apple-touch-icon.png"))
            ctx.close()
        finally:
            (site / "_og.html").unlink(missing_ok=True)
        browser.close()
    print("wrote site/img/, docs/screenshots/, site/og.png and site/apple-touch-icon.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
