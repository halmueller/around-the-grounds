"""Tests for the Canva design tap-list parser. The fixture is Old Stove
Brewing's Pike Place draft list (saved 2026-09-30), trimmed to the design
data the parser reads."""

import logging
from pathlib import Path
from typing import Iterator

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.canva import (
    BROWSER_HEADERS,
    CanvaParser,
    decode_design,
    parse_design,
)
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

LOGGER = logging.getLogger(__name__)
VENUE = next(
    v
    for v in load_site_config("seattle-freshies").venues
    if v.key == "old-stove-pike-place-taps"
)


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


@pytest.fixture
def html(html_fixtures_dir: Path) -> str:
    return (html_fixtures_dir / "canva_old_stove_pike_place.html").read_text()


def test_registered() -> None:
    assert ParserRegistry.get_parser(VENUE) is CanvaParser


def test_pike_place_beers_with_abv_and_description(html: str) -> None:
    entries = parse_design(decode_design(html))
    beers = [e for e in entries if e.abv]

    assert len(beers) == 19
    timeless = next(e for e in beers if e.name == "Timeless Lager")
    assert timeless.abv == "4.6%"
    # The description sits between name and ABV line; "16oz" is not a name.
    assert "Our deliciously crispy" in (timeless.description or "")
    names = {e.name for e in beers}
    assert "16oz" not in names and "Whiskey" not in names


def test_note_between_beers_is_its_own_entry(html: str) -> None:
    entries = parse_design(decode_design(html))
    streaker = next(e for e in entries if e.name == "Streaker Citra Pale Ale")
    # The fresh-hop note is not taken into Streaker's card.
    assert "fresh hop" not in (streaker.description or "")
    assert any(
        e.name.startswith("Ask your server about our fresh hop") for e in entries
    )


def test_pike_place_listings(html: str) -> None:
    events = build_listings(VENUE, parse_design(decode_design(html)), "canva", LOGGER)
    assert [(e.category, e.title) for e in events] == [
        ("festbier", "Festbier"),
        ("festbier", "Smoked Marzen"),
        (
            "fresh-hop",
            "Ask your server about our fresh hop beers! "
            "Strata, Citra, Mosaic, and Dolcita",
        ),
    ]


def test_ship_canal_layout_with_style_under_abv(html_fixtures_dir: Path) -> None:
    # A different design: the style sits under the ABV line, and a style can
    # come before its name in the document.
    html = (html_fixtures_dir / "canva_old_stove_ship_canal.html").read_text()
    entries = parse_design(decode_design(html))
    by_name = {e.name: e for e in entries if e.abv}

    assert by_name["OkStoverFest"].style == "Festbier"
    assert by_name["Fresh Hop Citra"].style == "Fresh Hop Hazy Pale Ale"
    # Section headings ("DRAFT POURS") are not names.
    assert by_name["Belgian Blonde"].style == "Wheat Beer"
    assert "DRAFT POURS" not in by_name

    venue = next(
        v
        for v in load_site_config("seattle-freshies").venues
        if v.key == "old-stove-ship-canal-taps"
    )
    events = build_listings(venue, entries, "canva", LOGGER)
    assert [(e.category, e.title, e.description) for e in events] == [
        ("fresh-hop", "Fresh hop strata", "Fresh Hop West Coast IPA · 7.7%"),
        ("festbier", "OkStoverFest", "Festbier · 6.2%"),
        ("fresh-hop", "Fresh Hop Citra", "Fresh Hop Hazy Pale Ale · 6%"),
        ("festbier", "The Claw!", "Cherrywood Smoked Marzen · 5.6%"),
        ("festbier", "BEST DAY Oktoberfest", None),  # non-alcoholic, no ABV line
    ]


def test_blocked_page_raises() -> None:
    with pytest.raises(ValueError, match="no design data"):
        decode_design("<html><title>Unsupported client – Canva</title></html>")


@pytest.mark.asyncio
async def test_fetches_design_url_with_browser_user_agent(html: str) -> None:
    design_url = VENUE.parser_config["design_url"]
    with aioresponses() as m:
        m.get(design_url, status=200, body=html)
        async with aiohttp.ClientSession(
            headers={"User-Agent": "Around-the-Grounds Event Scraper"}
        ) as session:
            events = await CanvaParser(VENUE).parse(session)
        [call] = next(iter(m.requests.values()))

    assert call.kwargs["headers"]["User-Agent"] == BROWSER_HEADERS["User-Agent"]
    assert len(events) == 3


@pytest.mark.asyncio
async def test_falls_back_to_venue_url() -> None:
    venue = Venue("x", "X", "https://www.canva.com/design/a/b/view", "canva", {})
    with aioresponses() as m:
        m.get(venue.url, status=200, body="<html>Unsupported client</html>")
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="no design data"):
                await CanvaParser(venue).parse(session)
