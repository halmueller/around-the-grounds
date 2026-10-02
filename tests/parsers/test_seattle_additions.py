"""Tests for the venues added on 2026-10-01 (pages and API responses saved
that day): the Menu Tools and TapHunter parsers, html-taplist's
``source_url`` / ``json_html_key`` options, and the venue configs that use
existing parsers."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Event, Venue
from around_the_grounds.parsers.generic.html_taplist import (
    HtmlTaplistParser,
    TapHunterParser,
)
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.generic.menu_tools import (
    API_URL,
    MenuToolsParser,
    parse_menu_tools,
)
from around_the_grounds.parsers.generic.sheet_taplist import parse_sheet_rows
from around_the_grounds.parsers.generic.text_taplist import parse_text_taplist
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

LOGGER = logging.getLogger(__name__)
VENUES = {v.key: v for v in load_site_config("seattle-freshies").venues}
Listing = List[Any]


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


def summary(events: List[Event]) -> List[Listing]:
    return [[e.title, e.category, e.description] for e in events]


@pytest.mark.parametrize(
    "source_type,parser",
    [("menu-tools", MenuToolsParser), ("taphunter", TapHunterParser)],
)
def test_source_types_are_registered(source_type: str, parser: type) -> None:
    venue = Venue("some-taproom", "Some Taproom", "https://example.com", source_type)
    assert ParserRegistry.get_parser(venue) is parser


class TestMenuTools:
    VENUE = VENUES["burke-gilman-taps"]
    URL = API_URL.format(display_path="bgbc/my-location/main-menu")

    @pytest.fixture
    def payload(self, fixtures_dir: Path) -> Dict[str, Any]:
        data: Dict[str, Any] = json.loads(
            (fixtures_dir / "json" / "menu_tools_burke_gilman.json").read_text()
        )
        return data

    def test_items_from_every_section(self, payload: Dict[str, Any]) -> None:
        entries = parse_menu_tools(payload)
        first = entries[0]
        assert (first.name, first.brewery, first.style, first.abv) == (
            "Semiquincentennial",
            None,
            "American Pale Ale",
            "4.8%",
        )
        guest = next(e for e in entries if e.name == "Skyfinder")
        assert (guest.brewery, guest.style) == ("Single Hill", "FH Hazy IPA")

    def test_unavailable_and_unnamed_items_are_skipped(self) -> None:
        payload = {
            "sections": [
                {
                    "items": [
                        {"name": "Kicked Fresh Hop", "available": False},
                        {"name": " ", "available": True},
                        {"name": "Fresh Hop IPA", "available": True, "abv": 6},
                    ]
                }
            ]
        }
        entries = parse_menu_tools(payload)
        assert [(e.name, e.abv) for e in entries] == [("Fresh Hop IPA", "6%")]

    @pytest.mark.asyncio
    async def test_parse_reads_the_display_api(self, payload: Dict[str, Any]) -> None:
        with aioresponses() as m:
            m.get(self.URL, status=200, payload=payload)
            async with aiohttp.ClientSession() as session:
                events = await MenuToolsParser(self.VENUE).parse(session)
        assert summary(events)[0] == [
            "Festbier",
            "festbier",
            "Bavarian Festbier · 5.8%",
        ]
        assert "Fresh Hop Fiend Simcoe Italian Pils" in [e.title for e in events]

    @pytest.mark.asyncio
    async def test_missing_display_path_raises(self) -> None:
        venue = Venue("x-taps", "X", "https://example.com", "menu-tools", {})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="needs display_path"):
                await MenuToolsParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self) -> None:
        with aioresponses() as m:
            m.get(self.URL, status=200, body="<html>Menu unavailable</html>")
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="Invalid JSON from Menu Tools"):
                    await MenuToolsParser(self.VENUE).parse(session)


class TestTapHunter:
    VENUE = VENUES["good-society-west-seattle-taps"]
    URL = TapHunterParser.WIDGET_URL.format(
        location="4908654823079936", menu="5330337463664640"
    )

    @pytest.mark.asyncio
    async def test_parse_decodes_the_widget_script(self, fixtures_dir: Path) -> None:
        script = (fixtures_dir / "js" / "taphunter_good_society.js").read_text()
        with aioresponses() as m:
            m.get(self.URL, status=200, body=script)
            async with aiohttp.ClientSession() as session:
                events = await TapHunterParser(self.VENUE).parse(session)
        assert summary(events) == [
            ["All Points West - Fresh Hop", "fresh-hop", "IPA - Fresh Hop · 6.4%"],
            ["C+C Hop Factory", "fresh-hop", "IPA - Fresh Hop · 6.5%"],
            ["Green Envy", "fresh-hop", "Fresh Hop IPA · 5.3%"],
            ["Festbier", "festbier", "Festbier · 5.9%"],
        ]

    @pytest.mark.asyncio
    async def test_script_without_menu_raises(self) -> None:
        with aioresponses() as m:
            m.get(self.URL, status=200, body="(function () {})();")
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="no menu HTML"):
                    await TapHunterParser(self.VENUE).parse(session)

    @pytest.mark.asyncio
    async def test_missing_ids_raise(self) -> None:
        venue = Venue("x-taps", "X", "https://example.com", "taphunter", {})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="needs location_id and menu_id"):
                await TapHunterParser(venue).parse(session)


class TestHtmlTaplistSources:
    @pytest.mark.asyncio
    async def test_json_wrapped_html_from_source_url(self, fixtures_dir: Path) -> None:
        """The Good Society (Queen Anne): a Sippo embed's JSON API."""
        venue = VENUES["good-society-queen-anne-taps"]
        body = (fixtures_dir / "json" / "sippo_good_society.json").read_text()
        with aioresponses() as m:
            m.get("https://app.sippo.io/api/embed/0qj45", status=200, body=body)
            async with aiohttp.ClientSession() as session:
                events = await HtmlTaplistParser(venue).parse(session)
        assert summary(events) == [
            ["FRESH HOP: All Points West", "fresh-hop", "Fresh Hop IPA · 6.4%"],
            ["FRESH HOP: C + C Hop Factory", "fresh-hop", "Fresh Hop IPA · 6.5%"],
            ["Festbier", "festbier", "Festbier · 5.9%"],
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body,message",
        [
            ("<html>down</html>", "no 'html' HTML in response"),
            ('{"status": "failure"}', "no 'html' HTML in response"),
            ('{"html": 5}', "is not HTML"),
        ],
    )
    async def test_bad_json_wrapper_raises(self, body: str, message: str) -> None:
        venue = VENUES["good-society-queen-anne-taps"]
        with aioresponses() as m:
            m.get("https://app.sippo.io/api/embed/0qj45", status=200, body=body)
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match=message):
                    await HtmlTaplistParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_uber_tavern_table_from_source_url(
        self, html_fixtures_dir: Path
    ) -> None:
        venue = VENUES["uber-tavern-taps"]
        body = (html_fixtures_dir / "taplist_uber.html").read_text()
        with aioresponses() as m:
            m.get(
                re.compile(r"^https://www\.uberbier\.com/menu/menuPage\.php"),
                status=200,
                body=body,
            )
            async with aiohttp.ClientSession() as session:
                events = await HtmlTaplistParser(venue).parse(session)
        assert summary(events) == [
            [
                "Festbier Oktoberfest Style Lager",
                "festbier",
                "Dru Bru Snoqualmie Pass, WA · 5.6%",
            ]
        ]


class TestConfiguredVenues:
    def test_jellyfish_numbered_headings(self, html_fixtures_dir: Path) -> None:
        venue = VENUES["jellyfish-taps"]
        entries = parse_text_taplist(
            (html_fixtures_dir / "taplist_jellyfish.html").read_text(),
            venue.parser_config or {},
        )
        names = [e.name for e in entries]
        assert names[4] == "Medusa Oktoberfest"
        assert len(names) == 14  # tap 14 is empty; bottles are unnumbered
        events = build_listings(venue, entries, "html", LOGGER)
        assert summary(events) == [
            ["Medusa Oktoberfest", "festbier", None],
            ["Fresh Nooky Fresh Hop IPA", "fresh-hop", None],
        ]

    def test_trailbend_drafts_sheet(self, csv_fixtures_dir: Path) -> None:
        venue = VENUES["trailbend-taps"]
        entries = parse_sheet_rows(
            (csv_fixtures_dir / "trailbend_drafts.csv").read_text(),
            venue.parser_config or {},
        )
        assert (entries[0].name, entries[0].abv) == ("Bizarre Italian Pils", "4.90%")
        events = build_listings(venue, entries, "sheet", LOGGER)
        assert [e.title for e in events] == [
            "Cloudburst Fresh Hop Strata IPA",
            "pFriem Fresh Hop Pale",
        ]

    @pytest.mark.parametrize(
        "key", ["elysian-capitol-hill-taps", "elysian-fields-taps", "ghostfish-taps"]
    )
    def test_untappd_embed_venues_have_ids(self, key: str) -> None:
        config = VENUES[key].parser_config or {}
        assert VENUES[key].source_type == "untappd-embed"
        assert isinstance(config["location_id"], int)
        assert isinstance(config["theme_id"], int)
