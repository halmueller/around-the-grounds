"""The tap-rows parser: live tap lists served as JSON spreadsheet rows
(Roscoe's and Tiny Bubble Room; rows cut down from 2026-10-13)."""

import json
import logging
from typing import Any, Iterator, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.generic.tap_rows import TapRowsParser, parse_tap_rows
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

LOGGER = logging.getLogger(__name__)
VENUES = {v.key: v for v in load_site_config("portland-freshies").venues}
URL = "https://bar.example/api/taplist"

ROSCOES: List[List[str]] = [
    ["", "Roscoe's Beer List", "", "", "", "", "", ""],
    ["", "~ 16 Oz Goblet  *10 Oz Goblet", "", "", "", "$", "       ", ""],
    ["", "", "", "", "", "", "", ""],
    ["1", "F.H. Thunder Blanket", "*", "Astoria, OR", "ABV", "8",
     "Fresh Hop Barrel aged barleywine using Chinook hops.", ""],
    ["", "Fort George", "", "", "12", "", "", ""],
    ["2", "Mic Drop IPA", "", "Portland, OR", "ABV", "7",
     "__IPA.__ Flavors of grapefruit and orange peel.", ""],
    ["", "Breakside", "", "", "7.2", "", "", ""],
    ["3", "F.H, Animal Cookies", "", "Corvallis, OR. ", "ABV", "8", "Hazy IPA.", ""],
    ["", "Block 15", "", "", "?", "", "", ""],
    ["", "Cider", "", "", "", "", "", ""],
    ["4", "Hollow Jack", "", "Corvallis, OR", "ABV", "7",
     "Pumpkin Cider-  Apples and roasted pumpkin.", ""],
    ["5", "Last Tap", "", "", "", "", "", ""],
]  # fmt: skip


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


def _venue(**config: Any) -> Venue:
    return Venue("bar-taps", "A Bar", "https://bar.example", "tap-rows", config)


def test_source_type_is_registered() -> None:
    assert ParserRegistry.get_parser(_venue()) is TapRowsParser
    assert TapRowsParser.PRODUCES_LISTINGS is True


def test_two_rows_per_tap() -> None:
    entries = parse_tap_rows(ROSCOES)

    # The title, the glass key, and the "Cider" label are not taps.
    assert [(e.name, e.brewery, e.style, e.abv) for e in entries] == [
        ("F.H. Thunder Blanket", "Fort George", None, "12%"),
        ("Mic Drop IPA", "Breakside", "IPA", "7.2%"),
        ("F.H, Animal Cookies", "Block 15", None, None),  # ABV given as "?"
        # No second row before the next tap: no brewery, and tap 5 is not it.
        ("Hollow Jack", None, "Pumpkin Cider", None),
        ("Last Tap", None, None, None),
    ]
    assert entries[1].description == "IPA. Flavors of grapefruit and orange peel."
    assert entries[4].description is None


@pytest.mark.parametrize(
    "rows", [[], [[]], [["1"]], [None, "text", 7], [["x", "No Number"]], [["3", ""]]]
)
def test_rows_that_are_not_taps_are_skipped(rows: List[Any]) -> None:
    assert parse_tap_rows(rows) == []


def test_roscoes_fh_names_and_descriptions_match() -> None:
    venue = VENUES["roscoes-taps"]
    events = build_listings(venue, parse_tap_rows(ROSCOES), "tap-rows", LOGGER)

    assert [[e.title, e.category] for e in events] == [
        ["F.H. Thunder Blanket", "fresh-hop"],  # by its description
        ["F.H, Animal Cookies", "fresh-hop"],  # by "F.H," in the name alone
        ["Hollow Jack", "pumpkin"],
    ]


@pytest.mark.parametrize("key", ["roscoes-taps", "tiny-bubble-room-taps"])
def test_configured_venues_point_at_their_own_api(key: str) -> None:
    venue = VENUES[key]
    config = venue.parser_config or {}
    assert venue.source_type == "tap-rows"
    assert config["rows_url"].endswith("/api/taplist")
    assert config["venue_type"] == "taproom"


@pytest.mark.asyncio
async def test_parse_fetches_rows_url() -> None:
    parser = TapRowsParser(_venue(rows_url=URL))
    with aioresponses() as mocked:
        mocked.get(URL, body=json.dumps(ROSCOES))
        async with aiohttp.ClientSession() as session:
            events = await parser.parse(session)

    assert [e.title for e in events] == ["F.H. Thunder Blanket", "Hollow Jack"]
    assert all(e.kind == "listing" for e in events)


@pytest.mark.asyncio
async def test_missing_rows_url_raises() -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError, match="rows_url"):
            await TapRowsParser(_venue()).parse(session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, message",
    [("<html>down</html>", "Invalid JSON"), ('{"rows": []}', "Unexpected tap-rows")],
)
async def test_bad_response_raises(body: str, message: str) -> None:
    parser = TapRowsParser(_venue(rows_url=URL))
    with aioresponses() as mocked:
        mocked.get(URL, body=body)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match=message):
                await parser.parse(session)


@pytest.mark.asyncio
async def test_server_error_raises() -> None:
    parser = TapRowsParser(_venue(rows_url=URL))
    with aioresponses() as mocked:
        mocked.get(URL, status=500)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="HTTP 500"):
                await parser.parse(session)


@pytest.mark.asyncio
async def test_empty_list_is_not_an_error() -> None:
    parser = TapRowsParser(_venue(rows_url=URL))
    with aioresponses() as mocked:
        mocked.get(URL, body="[[]]")
        async with aiohttp.ClientSession() as session:
            assert await parser.parse(session) == []
