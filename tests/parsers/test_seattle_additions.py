"""Tests for the venues added on 2026-10-01 (pages and API responses saved
that day; Ridgecrest's sheet and the Maize & Barley and TeKu Tavern Square
Online categories on 2026-10-10): the Menu Tools, TapHunter, and Square Online parsers,
html-taplist's ``source_url`` / ``json_html_key`` options, and the venue
configs that use existing parsers."""

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
    parse_html_taplist,
)
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.generic.menu_tools import (
    API_URL,
    MenuToolsParser,
    parse_menu_tools,
)
from around_the_grounds.parsers.generic.sheet_taplist import (
    SheetTaplistParser,
    parse_sheet_rows,
)
from around_the_grounds.parsers.generic.square_online import API_URL as SQUARE_API_URL
from around_the_grounds.parsers.generic.square_online import (
    SquareOnlineParser,
    parse_square_online,
)
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
    [
        ("menu-tools", MenuToolsParser),
        ("taphunter", TapHunterParser),
        ("square-online", SquareOnlineParser),
    ],
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
        # A guest beer whose only fresh-hop marker is its "FH Hazy IPA" style.
        assert ["Skyfinder", "fresh-hop", "Single Hill · FH Hazy IPA · 6.8%"] in (
            summary(events)
        )

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


class TestSquareOnline:
    VENUE = VENUES["maize-and-barley-taps"]
    URL = re.compile(
        re.escape(
            SQUARE_API_URL.format(user_id="125835288", site_id="507456299749329449")
        )
        + r"\?.*"
    )

    @pytest.fixture
    def payload(self, fixtures_dir: Path) -> Dict[str, Any]:
        data: Dict[str, Any] = json.loads(
            (fixtures_dir / "json" / "square_online_maize_barley.json").read_text()
        )
        return data

    def test_every_item_without_a_name_pattern(self, payload: Dict[str, Any]) -> None:
        entries = parse_square_online(payload)
        assert len(entries) == 17
        assert "TASTER" in [e.name for e in entries]

    def test_out_of_stock_and_unnamed_items_are_skipped(self) -> None:
        payload = {
            "data": [
                {"name": "Kicked Fresh Hop", "badges": {"out_of_stock": True}},
                {"name": " "},
                "junk",
                {"name": "Fresh Hop IPA", "short_description": "<p>Yakima; 6%</p>"},
            ]
        }
        entries = parse_square_online(payload)
        assert [(e.name, e.abv) for e in entries] == [("Fresh Hop IPA", "6%")]

    @pytest.mark.asyncio
    async def test_parse_keeps_numbered_draft_lines(
        self, payload: Dict[str, Any]
    ) -> None:
        with aioresponses() as m:
            m.get(self.URL, status=200, payload=payload)
            async with aiohttp.ClientSession() as session:
                events = await SquareOnlineParser(self.VENUE).parse(session)
            ((call,),) = m.requests.values()
        params = call.kwargs["params"]
        assert params["categories[]"] == "3IQ72W2FVUNOOR3CY6EV5AYG"
        assert params["location"] == "4BVH25KR5VSFN"
        assert sorted(summary(events)) == [
            [
                "EXCESSIVE CELEBRATIONS FESTBIER",
                "festbier",
                "OTHERLANDS · 5.6%",
            ],
            [
                "GREEN RUSH FRESH HOP IPA",
                "fresh-hop",
                "BALE BREAKER/ RUSSIAN RIVER · 6.9%",
            ],
            [
                "KETTLE & CAST FRESH HOP HAZY PALE",
                "fresh-hop",
                "BURIAL/VARIETAL · 4.8%",
            ],
            [
                "MOONSHAKE PUMPKIN OAT STOUT",
                "pumpkin",
                "BIZARRE · 5.5%",
            ],
            [
                "MR. GOLDEN SUN FRESH HOP HAZY Hazy IPA",
                "fresh-hop",
                "HUMAN PEOPLE · 6.7%",
            ],
            [
                "SIMCOE ARCHITECT FRESH HOP WC IPA",
                "fresh-hop",
                "FORT GEORGE/ GHOST TOWN · 6.66%",
            ],
            ["TIME LAPSE FH WC IPA", "fresh-hop", "KINGS & DAUGHTERS · 7.1%"],
        ]

    def test_teku_emoji_tags_match_but_are_not_shown(self, fixtures_dir: Path) -> None:
        venue = VENUES["teku-taps"]
        config = venue.parser_config or {}
        payload = json.loads(
            (fixtures_dir / "json" / "square_online_teku.json").read_text()
        )
        entries = parse_square_online(payload, re.compile(config["name_pattern"]))
        events = build_listings(venue, entries, "square-online", LOGGER)
        assert sorted(summary(events)) == [
            ["Bizarre Fresh Hop Skitch", "fresh-hop", None],
            ["Cloudburst Wet Side Story", "fresh-hop", None],
            ["Fort George Topaz", "pumpkin", None],
            ["Four Generals Rauch Märzen", "festbier", None],
            ["Grains Of Wrath Gerstenwolf", "festbier", None],
            ["Great Notion Fresh Hop Northleft", "fresh-hop", None],
            ["Ilk Dripping Wet Hops", "fresh-hop", None],
            ["Ilk Fresh Hop Strata Pale", "fresh-hop", None],
            ["Lucky Envelope Pumpkin Emoji", "pumpkin", None],
            ["Otherlands Excessive Celebrations", "festbier", None],
            ["Reuben's FH Party On (Can Pour)", "fresh-hop", None],
            ["Stoup Fresh Hop Fiend (Thora)", "fresh-hop", None],
        ]

    @pytest.mark.asyncio
    async def test_follows_pages(self) -> None:
        def page(name: str) -> Dict[str, Any]:
            return {
                "data": [{"name": f"01. {name} - X"}],
                "meta": {"pagination": {"total_pages": 2}},
            }

        with aioresponses() as m:
            m.get(self.URL, status=200, payload=page("Fresh Hop One"))
            m.get(self.URL, status=200, payload=page("Fresh Hop Two"))
            async with aiohttp.ClientSession() as session:
                events = await SquareOnlineParser(self.VENUE).parse(session)
        assert [e.title for e in events] == ["Fresh Hop One", "Fresh Hop Two"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "config,message",
        [
            ({"user_id": "1", "site_id": "2"}, "needs user_id, site_id"),
            (
                {
                    "user_id": "1",
                    "site_id": "2",
                    "category_id": "C",
                    "name_pattern": "(",
                },
                "Invalid name_pattern",
            ),
            (
                {
                    "user_id": "1",
                    "site_id": "2",
                    "category_id": "C",
                    "name_pattern": "x",
                },
                "needs a",
            ),
        ],
    )
    async def test_bad_config_raises(
        self, config: Dict[str, Any], message: str
    ) -> None:
        venue = Venue("x-taps", "X", "https://example.com", "square-online", config)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match=message):
                await SquareOnlineParser(venue).parse(session)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body,message",
        [
            ("<html>Not found</html>", "Invalid JSON from Square Online"),
            ('{"error": "nope"}', "Unexpected Square Online response"),
        ],
    )
    async def test_bad_response_raises(self, body: str, message: str) -> None:
        with aioresponses() as m:
            m.get(self.URL, status=200, body=body)
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match=message):
                    await SquareOnlineParser(self.VENUE).parse(session)


class TestPublishedSheet:
    VENUE = VENUES["beer-authority-taps"]

    @pytest.fixture
    def csv_text(self, csv_fixtures_dir: Path) -> str:
        return (csv_fixtures_dir / "beer_authority_taplist.csv").read_text()

    def test_no_header_row_brewery_column_and_bare_abv(self, csv_text: str) -> None:
        entries = parse_sheet_rows(csv_text, self.VENUE.parser_config or {})
        assert len(entries) == 13
        first = entries[0]
        assert (first.name, first.brewery, first.abv) == (
            "Dry Nitro Stout",
            "Ferment",
            "4.5%",
        )

    @pytest.mark.asyncio
    async def test_parse_reads_csv_url(self, csv_text: str) -> None:
        url = (self.VENUE.parser_config or {})["csv_url"]
        with aioresponses() as m:
            m.get(url, status=200, body=csv_text)
            async with aiohttp.ClientSession() as session:
                events = await SheetTaplistParser(self.VENUE).parse(session)
        assert summary(events) == [
            ["Animal Cookies Fresh Hop Hazy IPA", "fresh-hop", "Block 15 · 7%"],
            ["Wet Season Citra FH Hazy IPA", "fresh-hop", "Ravenna · 6.8%"],
            ["Bug Hazy FH IPA", "fresh-hop", "Human People · 7%"],
            ["Wet Season Centennial FH Hazy IPA", "fresh-hop", "Ravenna · 6.3%"],
            ["Wet Season Amarillo FH WC IPA", "fresh-hop", "Ravenna · 6.5%"],
        ]

    @pytest.mark.asyncio
    async def test_needs_sheet_or_csv_url(self) -> None:
        venue = Venue("x-taps", "X", "https://example.com", "sheet-taplist", {})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="or csv_url"):
                await SheetTaplistParser(venue).parse(session)


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

    def test_ridgecrest_abv_inside_the_beer_cell(self, csv_fixtures_dir: Path) -> None:
        venue = VENUES["ridgecrest-taps"]
        entries = parse_sheet_rows(
            (csv_fixtures_dir / "ridgecrest_taplist.csv").read_text(),
            venue.parser_config or {},
        )
        # Section rows ("LIGHTER") have no beer cell; "GLUTEN FREE" has "in cans".
        assert len(entries) == 28
        by_name = {e.name: e for e in entries}
        first = entries[0]
        assert (first.name, first.brewery, first.style, first.abv) == (
            "Trident's Up! American Lager",
            "Triceratops Brewing",
            None,
            "4.8%",
        )
        # "Cranberry Spice | 6.1% | 10": a separator before the ABV too.
        assert by_name["Cranberry Spice"].abv == "6.1%"
        # Canned beers are listed without an ABV.
        assert by_name["Kickstep IPA"].abv is None
        events = build_listings(venue, entries, "sheet", LOGGER)
        assert summary(events) == [
            ["Charivari Festbier", "festbier", "E9 Brewing · 5.7%"],
            ["Fake Train FH Pale", "fresh-hop", "Bizarre Brewing · 5.2%"],
            ["Petrichor FH NW IPA", "fresh-hop", "Human People Brewing · 6.8%"],
            ["Easy Being Green FH Hazy IPA", "fresh-hop", "Matchless Brewing · 6.4%"],
            ["FH Hoprissian IPA", "fresh-hop", "Loowit Brewing · 6.4%"],
            ["Moonshake Pumpkin Oat Stout", "pumpkin", "Bizarre Brewing · 5.5%"],
        ]

    def test_abv_column_wins_over_the_name_cell(self) -> None:
        entries = parse_sheet_rows(
            "h,h\nBig 10% Stout,7.2\n", {"columns": {"name": 0, "abv": 1}}
        )
        assert (entries[0].name, entries[0].abv) == ("Big 10% Stout", "7.2%")

    def test_outer_planet_tap_cards(self, html_fixtures_dir: Path) -> None:
        venue = VENUES["outer-planet-taps"]
        entries = parse_html_taplist(
            (html_fixtures_dir / "taplist_outer_planet.html").read_text(),
            venue.parser_config or {},
        )
        assert len(entries) == 11
        assert (entries[0].name, entries[0].style, entries[0].abv) == (
            "Atmosphere on Titan",
            "IPA",
            "7.5%",
        )
        events = build_listings(venue, entries, "html", LOGGER)
        assert summary(events) == [
            ["Orion Wears Lederhosen Festbier", "festbier", "Lager · 5.6%"]
        ]

    @pytest.mark.parametrize(
        "key",
        [
            "edway-taps",
            "elysian-capitol-hill-taps",
            "elysian-fields-taps",
            "ghostfish-taps",
        ],
    )
    def test_untappd_embed_venues_have_ids(self, key: str) -> None:
        config = VENUES[key].parser_config or {}
        assert VENUES[key].source_type == "untappd-embed"
        assert isinstance(config["location_id"], int)
        assert isinstance(config["theme_id"], int)
