"""The pourwall parser: tap lists from Pourwall's public GraphQL endpoint
(5th Line; taps cut down from 2026-10-13)."""

import json
import logging
from typing import Any, Dict, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.generic.pourwall import (
    GRAPHQL_URL,
    PourwallParser,
    parse_pourwall_taps,
)
from around_the_grounds.parsers.registry import ParserRegistry

LOGGER = logging.getLogger(__name__)
LOCATION = "613b681edda9c1000831588a"


def _tap(number: Any, status: str, name: Any, style: str, abv: Any) -> Dict[str, Any]:
    return {
        "name": number,
        "status": status,
        "beverage": {
            "name": name,
            "style": style,
            "abv": abv,
            "description": "",
            "source": {"name": ""},
        },
    }


TAPS: List[Dict[str, Any]] = [
    _tap(9, "ACTIVE", "Grublager", "German Fest Bier", 6.8),
    _tap(2, "ACTIVE", "Filthy Mitts", "Pale Ale", 5.3),
    _tap(6, "ACTIVE", "Happy Accidents", "Fresh Hop Pale Ale", 5.2),
    _tap(20, "ON_DECK", "Next Shift", "Fresh Hop IPA", 6.5),
    _tap(16, "ACTIVE", "Root Beer", "House made for the kids and adults!", 0),
    _tap(17, "ACTIVE", " Ask About Our", " Wine Selection", 0),
    _tap(21, "ACTIVE", None, "Fresh Hop IPA", 6),
]
PAYLOAD = {"data": {"taps": TAPS}}


def _venue(**config: Any) -> Venue:
    return Venue("bar-taps", "A Bar", "https://bar.example", "pourwall", config)


def test_registered() -> None:
    assert ParserRegistry.get_parser(_venue()) is PourwallParser
    assert PourwallParser.PRODUCES_LISTINGS


def test_active_taps_in_tap_order() -> None:
    entries = parse_pourwall_taps(PAYLOAD)
    assert [(e.name, e.style, e.abv) for e in entries] == [
        ("Filthy Mitts", "Pale Ale", "5.3%"),
        ("Happy Accidents", "Fresh Hop Pale Ale", "5.2%"),
        ("Grublager", "German Fest Bier", "6.8%"),
        ("Root Beer", "House made for the kids and adults!", None),
        ("Ask About Our", "Wine Selection", None),
    ]
    # An empty brewery name is no brewery.
    assert all(e.brewery is None for e in entries)


def test_on_deck_taps_are_not_pouring() -> None:
    assert "Next Shift" not in [e.name for e in parse_pourwall_taps(PAYLOAD)]


def test_listings() -> None:
    events = build_listings(_venue(), parse_pourwall_taps(PAYLOAD), "pourwall", LOGGER)
    assert [[e.title, e.category] for e in events] == [
        ["Happy Accidents", "fresh-hop"],
        ["Grublager", "festbier"],
    ]


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"errors": [{"message": "did not match any locations"}]}, "API error"),
        ({"data": None}, "no taps"),
        ({"data": {"taps": None}}, "no taps"),
        ([], "Unexpected"),
    ],
)
def test_bad_payloads_raise(payload: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_pourwall_taps(payload)


def test_fifth_line_is_configured() -> None:
    venues = {v.key: v for v in load_site_config("yakima-freshies").venues}
    venue = venues["fifth-line-taps"]
    assert venue.source_type == "pourwall"
    assert (venue.parser_config or {})["location_id"] == LOCATION


@pytest.mark.asyncio
async def test_parse_posts_the_embed_query() -> None:
    parser = PourwallParser(_venue(location_id=LOCATION))
    with aioresponses() as mocked:
        mocked.post(GRAPHQL_URL, body=json.dumps(PAYLOAD))
        async with aiohttp.ClientSession() as session:
            events = await parser.parse(session)
        (call,) = [c for calls in mocked.requests.values() for c in calls]

    assert [e.title for e in events] == ["Happy Accidents", "Grublager"]
    assert all(e.kind == "listing" for e in events)
    assert call.kwargs["json"]["variables"] == {
        "location": LOCATION,
        "statuses": ["ACTIVE", "ON_DECK"],
    }


@pytest.mark.asyncio
async def test_missing_location_id_raises() -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError, match="location_id"):
            await PourwallParser(_venue()).parse(session)


@pytest.mark.asyncio
async def test_invalid_json_raises() -> None:
    parser = PourwallParser(_venue(location_id=LOCATION))
    with aioresponses() as mocked:
        mocked.post(GRAPHQL_URL, body="<html>down</html>")
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="invalid JSON"):
                await parser.parse(session)
