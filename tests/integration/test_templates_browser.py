"""Browser-level checks for the per-site templates.

Runs tests/browser/check_templates.mjs in a real Chromium via Playwright
(Node). The script serves each template with a hostile data.json and asserts
scraped strings render as text, search/filter interactions keep the original
names, and calendar-date headings are stable across visitor timezones.

Also runs tests/browser/check_fresh_hop.mjs once per Freshies site, against
the site as published (placeholders filled): hostile data renders as text,
tabs, search, the preferred-source badge in light and dark, and phone widths.

Skipped when Node or the Playwright package is unavailable.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from around_the_grounds.config.loader import load_all_sites
from around_the_grounds.main import _site_template_vars, _write_site_output
from around_the_grounds.models import SiteConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tests" / "browser" / "check_templates.mjs"
TEMPLATES = REPO_ROOT / "public_templates"


def _node_env() -> dict:
    env = dict(os.environ)
    try:
        global_root = subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        global_root = ""
    if global_root:
        existing = env.get("NODE_PATH", "")
        env["NODE_PATH"] = (
            f"{global_root}{os.pathsep}{existing}" if existing else global_root
        )
    return env


def _playwright_available() -> bool:
    if shutil.which("node") is None:
        return False
    probe = subprocess.run(
        ["node", "-e", "require('playwright')"],
        capture_output=True,
        env=_node_env(),
    )
    return probe.returncode == 0


@pytest.mark.integration
@pytest.mark.skipif(
    not _playwright_available(), reason="Node + Playwright not available"
)
def test_templates_render_hostile_data_as_text() -> None:
    result = subprocess.run(
        ["node", str(SCRIPT), str(TEMPLATES)],
        capture_output=True,
        text=True,
        env=_node_env(),
        timeout=180,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    for template in ("food-trucks", "music", "kids"):
        assert f"{template}: ok" in result.stdout


FRESH_HOP_SCRIPT = REPO_ROOT / "tests" / "browser" / "check_fresh_hop.mjs"
FRESHIES_SITES = [site for site in load_all_sites() if site.template == "fresh-hop"]
# Tab order on every Freshies page; events.html only for sites with events.
FRESH_HOP_PAGES = [
    "fresh-hops.html",
    "festbier.html",
    "pumpkin.html",
    "winter-beers.html",
    "taprooms.html",
    "events.html",
]


@pytest.mark.integration
@pytest.mark.skipif(
    not _playwright_available(), reason="Node + Playwright not available"
)
@pytest.mark.parametrize("site", FRESHIES_SITES, ids=lambda site: site.key)
def test_fresh_hop_site_in_a_browser(site: SiteConfig, tmp_path: Path) -> None:
    web_data = {
        "events": [],
        "site_key": site.key,
        "site_name": site.name,
        "public_url": site.public_url,
        "template_vars": _site_template_vars(site),
    }
    _write_site_output(tmp_path, TEMPLATES / site.template, web_data)
    expect = {
        "domain": urlsplit(site.public_url).hostname,
        "site_name": site.name,
        "pages": [p for p in FRESH_HOP_PAGES if (tmp_path / p).exists()],
    }
    result = subprocess.run(
        ["node", str(FRESH_HOP_SCRIPT), str(tmp_path), json.dumps(expect)],
        capture_output=True,
        text=True,
        env=_node_env(),
        timeout=180,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "fresh-hop: ok" in result.stdout
