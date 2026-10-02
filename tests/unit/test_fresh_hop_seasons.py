"""Out-of-season messages on the Seattle Freshies list pages.

Runs the template's app.js in Node against a stub DOM (no browser), so it is
skipped only where Node is missing.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "public_templates" / "fresh-hop"
SCRIPT = REPO_ROOT / "tests" / "browser" / "render_fresh_hop.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node not available"
)

VENUES = [
    {"key": "brewery", "name": "A Brewery", "url": "https://a.example", "type": None},
    {"key": "shop", "name": "A Shop", "url": "https://s.example", "type": "taproom"},
]


def _listing(category: str, venue: str = "brewery") -> Dict[str, Any]:
    return {
        "kind": "listing",
        "category": category,
        "venue_key": venue,
        "venue": venue,
        "title": f"A {category} beer",
    }


def _render(page: str, month: int, listings: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = {
        "updated": f"2026-{month:02d}-15T20:00:00+00:00",
        "timezone": "America/Los_Angeles",
        "events": listings,
        "listing_venues": VENUES,
        "failed_venues": [],
    }
    result = subprocess.run(
        ["node", str(SCRIPT), str(TEMPLATE / "app.js"), page, json.dumps(data)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    rendered: Dict[str, Any] = json.loads(result.stdout)
    return rendered


@pytest.mark.parametrize(
    "page, message, in_months",
    [
        ("freshhop", "Fresh hops are out of season.", [8, 9, 10]),
        ("festbier", "Festbiers are out of season.", [9, 10]),
        ("pumpkin", "Pumpkin beers are out of season.", [9, 10, 11]),
    ],
)
def test_empty_list_says_out_of_season_only_outside_its_months(
    page: str, message: str, in_months: List[int]
) -> None:
    for month in range(1, 13):
        rendered = _render(page, month, [])
        if month in in_months:
            assert "on tap right now" in rendered["listings"], month
            assert message not in rendered["listings"], month
            assert rendered["quiet"] and "A Brewery" in rendered["quiet"], month
        else:
            assert message in rendered["listings"], month
            # Naming every place as "checked, nothing on" is noise off season.
            assert rendered["quiet"] is None, month


def test_out_of_season_message_links_the_lists_with_beers() -> None:
    listings = [
        _listing("pumpkin"),
        _listing("pumpkin"),
        _listing("festbier", venue="shop"),
    ]
    rendered = _render("freshhop", 12, listings)["listings"]
    assert "Fresh hops are out of season." in rendered
    assert re.findall(r'<a href="([^"]+)">([^<]+)</a> \((\d+)\)', rendered) == [
        ("pumpkin.html", "Pumpkin", "2"),
        ("taprooms.html", "Taprooms", "1"),
    ]


def test_out_of_season_message_stands_alone_when_nothing_is_pouring() -> None:
    rendered = _render("freshhop", 12, [])["listings"]
    assert "Fresh hops are out of season." in rendered
    assert "Pouring now" not in rendered and "<a " not in rendered


def test_beers_show_even_out_of_season() -> None:
    rendered = _render("freshhop", 12, [_listing("fresh-hop")])
    assert "A fresh-hop beer" in rendered["listings"]
    assert "out of season" not in rendered["listings"]
    assert "1 fresh-hop beer" in rendered["summary"]


def test_month_is_read_in_site_time() -> None:
    # 2026-11-01 03:00 UTC is still October 31 in Seattle: in season.
    data_month_edge = {
        "updated": "2026-11-01T03:00:00+00:00",
        "timezone": "America/Los_Angeles",
        "events": [],
        "listing_venues": VENUES,
    }
    result = subprocess.run(
        [
            "node",
            str(SCRIPT),
            str(TEMPLATE / "app.js"),
            "freshhop",
            json.dumps(data_month_edge),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "on tap right now" in json.loads(result.stdout)["listings"]


def test_taprooms_and_events_never_say_out_of_season() -> None:
    assert "out of season" not in _render("taprooms", 3, [])["listings"]
    assert "out of season" not in _render("events", 3, [])["listings"]


@pytest.mark.parametrize(
    "page, sentence",
    [
        ("fresh-hops.html", "Fresh-hop season runs from late August through October."),
        ("festbier.html", "Festbier season runs from September through October."),
        ("pumpkin.html", "Pumpkin beer season runs from September through November."),
    ],
)
def test_pages_state_their_season_in_static_html(page: str, sentence: str) -> None:
    # Crawlers that do not run the script still get real text off season.
    tagline: Optional[re.Match] = re.search(
        r'<p class="tagline">(.*?)</p>', (TEMPLATE / page).read_text()
    )
    assert tagline and sentence in tagline.group(1)
