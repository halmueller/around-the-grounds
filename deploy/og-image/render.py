"""Render the Open Graph card for Seattle Freshies.

Run from the repo root:
    uvx --with playwright==1.55.0 python deploy/og-image/render.py
(first time: uvx --with playwright==1.55.0 playwright install chromium)
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "public_templates" / "fresh-hop" / "og-image.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.goto((HERE / "seattle-freshies.html").as_uri())
    page.screenshot(path=str(OUT))
    browser.close()
print(f"wrote {OUT}")
