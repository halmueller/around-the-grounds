"""Render the Freshies sites' raster images.

Per site, into public_templates/_overlays/<site key>/ (copied over the shared
template when the site is written):
    og-image.png          1200x630 Open Graph card, from og-card.html with the
                          site's name and domain filled in

Shared, into public_templates/fresh-hop/:
    favicon-32.png        32x32, from favicon.svg (the template's own copy)
    apple-touch-icon.png  180x180, square corners (iOS rounds them itself)
    favicon.ico           16/32/48, for browsers and crawlers that ask for it

Run from the repo root, for every site on the fresh-hop template or only the
site keys given:
    uvx --with playwright==1.55.0 --with pillow python deploy/images/render.py
    uvx --with playwright==1.55.0 --with pillow python deploy/images/render.py \\
        portland-freshies
(first time: uvx --with playwright==1.55.0 playwright install chromium)
"""

import html
import io
import json
import sys
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TEMPLATE_NAME = "fresh-hop"
TEMPLATE = REPO / "public_templates" / TEMPLATE_NAME
OVERLAYS = REPO / "public_templates" / "_overlays"
SITES = REPO / "around_the_grounds" / "config" / "sites"
ICON_BG = "#4f7a28"  # matches .bg in favicon.svg

# Shrink the site name until it fits on one line of the card.
FIT_NAME = """() => {
    const h1 = document.querySelector('h1');
    const style = getComputedStyle(document.body);
    const room = document.body.clientWidth
        - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    let size = parseFloat(getComputedStyle(h1).fontSize);
    while (h1.scrollWidth > room && size > 40) {
        size -= 2;
        h1.style.fontSize = size + 'px';
    }
}"""


def site_keys(requested: List[str]) -> List[str]:
    if requested:
        return requested
    keys = []
    for path in sorted(SITES.glob("*.json")):
        if json.loads(path.read_text()).get("template") == TEMPLATE_NAME:
            keys.append(path.stem)
    return keys


def render_card(page: Page, key: str) -> Path:
    site = json.loads((SITES / f"{key}.json").read_text())
    domain = urlparse(site.get("public_url", "")).netloc
    if not domain:
        raise SystemExit(f"{key}: public_url is not set, so the card has no domain")
    card = (HERE / "og-card.html").read_text()
    card = card.replace("{{site_name}}", html.escape(site["name"]))
    card = card.replace("{{domain}}", html.escape(domain))
    page.set_viewport_size({"width": 1200, "height": 630})
    page.set_content(card)
    page.evaluate(FIT_NAME)
    out = OVERLAYS / key / "og-image.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))
    return out


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


written = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    for key in site_keys(sys.argv[1:]):
        written.append(render_card(page, key))

    (TEMPLATE / "favicon-32.png").write_bytes(render_icon(page, 32))
    (TEMPLATE / "apple-touch-icon.png").write_bytes(render_icon(page, 180, square=True))
    # Render the ICO's largest size and let Pillow scale down for the rest.
    big = Image.open(io.BytesIO(render_icon(page, 48)))
    big.save(TEMPLATE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    browser.close()

for name in ("favicon-32.png", "apple-touch-icon.png", "favicon.ico"):
    written.append(TEMPLATE / name)
for path in written:
    print(f"wrote {path}")
