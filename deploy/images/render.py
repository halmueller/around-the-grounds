"""Render Seattle Freshies' raster images into public_templates/fresh-hop/.

    og-image.png          1200x630 Open Graph card, from seattle-freshies.html
    favicon-32.png        32x32, from favicon.svg (the template's own copy)
    apple-touch-icon.png  180x180, square corners (iOS rounds them itself)
    favicon.ico           16/32/48, for browsers and crawlers that ask for it

Run from the repo root:
    uvx --with playwright==1.55.0 --with pillow python deploy/images/render.py
(first time: uvx --with playwright==1.55.0 playwright install chromium)
"""

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parents[1] / "public_templates" / "fresh-hop"
ICON_BG = "#4f7a28"  # matches .bg in favicon.svg


def render_icon(page: Page, size: int, square: bool = False) -> bytes:
    svg = (TEMPLATE / "favicon.svg").read_text()
    background = ICON_BG if square else "transparent"
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(
        f'<html><body style="margin:0;background:{background}">'
        f'<div style="width:{size}px;height:{size}px">{svg}</div></body></html>'
    )
    page.eval_on_selector("svg", "el => { el.style.width = el.style.height = '100%' }")
    return page.screenshot(omit_background=not square)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.goto((HERE / "seattle-freshies.html").as_uri())
    page.screenshot(path=str(TEMPLATE / "og-image.png"))

    (TEMPLATE / "favicon-32.png").write_bytes(render_icon(page, 32))
    (TEMPLATE / "apple-touch-icon.png").write_bytes(render_icon(page, 180, square=True))
    # Render the ICO's largest size and let Pillow scale down for the rest.
    big = Image.open(io.BytesIO(render_icon(page, 48)))
    big.save(TEMPLATE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    browser.close()

for name in ("og-image.png", "favicon-32.png", "apple-touch-icon.png", "favicon.ico"):
    print(f"wrote {TEMPLATE / name}")
