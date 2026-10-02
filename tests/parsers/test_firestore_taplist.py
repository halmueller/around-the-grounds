"""Tests for the Firestore tap-list parser (Project 9 Brewing; query response
saved 2026-10-02)."""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.firestore_taplist import (
    API_URL,
    DEFAULT_FIELDS,
    FirestoreTaplistParser,
    build_query,
    parse_firestore_taplist,
)
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

VENUE = {v.key: v for v in load_site_config("seattle-freshies").venues}[
    "project-9-taps"
]
URL = API_URL.format(project="project9brewing")


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


@pytest.fixture
def rows(fixtures_dir: Path) -> List[Any]:
    path = fixtures_dir / "json" / "firestore_project9.json"
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def doc(**fields: Dict[str, Any]) -> Dict[str, Any]:
    return {"document": {"fields": fields}}


def test_source_type_is_registered() -> None:
    assert ParserRegistry.get_parser(VENUE) is FirestoreTaplistParser


def test_query_asks_for_unarchived_beers() -> None:
    query = build_query("beers", DEFAULT_FIELDS)["structuredQuery"]
    assert query["from"] == [{"collectionId": "beers"}]
    assert query["where"]["fieldFilter"]["field"] == {"fieldPath": "isArchived"}
    assert {"fieldPath": "tapNumber"} in query["select"]["fields"]


def test_project_9_tap_list(rows: List[Any]) -> None:
    entries = parse_firestore_taplist(rows, DEFAULT_FIELDS)
    assert len(entries) == 16
    # In tap order; the sold-out barrel-aged stout has no tap and is left off.
    assert (entries[0].name, entries[0].style, entries[0].abv) == (
        "Regal Beast",
        "Czech Dark Lager",
        "5.2%",
    )
    assert "LIGHTS OUT - 2025 BARREL AGED" not in [e.name for e in entries]
    fresh = next(e for e in entries if e.name == "Fresh Pathfinder")
    assert fresh.description and fresh.description.endswith(
        "Coleman Farms, 2026 Best of Craft Bronze!"
    )


def test_skips_archived_sold_out_and_untapped() -> None:
    name = {"stringValue": "Fresh Hop IPA"}
    tap = {"integerValue": "3"}
    rows = [
        {"readTime": "2026-10-02T00:00:00Z"},
        doc(name=name, tapNumber=tap, isArchived={"booleanValue": True}),
        doc(name=name, tapNumber=tap, soldOutTime={"timestampValue": "2026-09-04"}),
        doc(name=name),
        doc(name=name, tapNumber={"integerValue": "0"}),
        doc(name=name, tapNumber=tap, soldOutTime={"nullValue": None}),
    ]
    entries = parse_firestore_taplist(rows, DEFAULT_FIELDS)
    assert [(e.name, e.abv) for e in entries] == [("Fresh Hop IPA", None)]


def test_field_names_can_be_overridden() -> None:
    names = dict(DEFAULT_FIELDS, name="title", tap="", brewery="maker")
    rows = [doc(title={"stringValue": "Festbier"}, maker={"stringValue": "Guest"})]
    entries = parse_firestore_taplist(rows, names)
    assert [(e.name, e.brewery) for e in entries] == [("Festbier", "Guest")]


@pytest.mark.asyncio
async def test_parse_keeps_the_seasonal_beers(rows: List[Any]) -> None:
    with aioresponses() as m:
        m.post(URL, status=200, payload=rows)
        async with aiohttp.ClientSession() as session:
            events = await FirestoreTaplistParser(VENUE).parse(session)
    assert [[e.title, e.category, e.description] for e in events] == [
        ["Fresh Pathfinder", "fresh-hop", "PNW Pils · 5.5%"],
        ["FRESH CITRA", "fresh-hop", "Fresh Hop WC IPA · 7.1%"],
        ["Herr Hopfen", "festbier", "Oktoberfest · 5.4%"],
    ]


@pytest.mark.asyncio
async def test_missing_project_raises() -> None:
    venue = Venue("x-taps", "X", "https://example.com", "firestore-taplist", {})
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError, match="needs project"):
            await FirestoreTaplistParser(venue).parse(session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,message",
    [
        ("<html>Not found</html>", "Invalid JSON from Firestore"),
        ('[{"error": {"code": 403, "status": "PERMISSION_DENIED"}}]', "Unexpected"),
        ('{"error": {"code": 400}}', "Unexpected"),
    ],
)
async def test_bad_responses_raise(body: str, message: str) -> None:
    with aioresponses() as m:
        m.post(URL, status=200, body=body)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match=message):
                await FirestoreTaplistParser(VENUE).parse(session)
