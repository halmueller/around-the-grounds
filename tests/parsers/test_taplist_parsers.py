"""Tests for the selector-driven (html-taplist, craftpeak-wot, digitalpour)
and line-driven (text-taplist) tap-list parsers. Fixtures are live pages
saved on 2026-09-29, stripped of scripts, styles and most attributes."""

import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.html_taplist import (
    CraftpeakWotParser,
    DigitalPourParser,
    HtmlTaplistParser,
    parse_html_taplist,
)
from around_the_grounds.parsers.generic.listing_common import (
    TapEntry,
    build_listings,
    normalize_abv,
)
from around_the_grounds.parsers.generic.text_taplist import (
    TextTaplistParser,
    iter_lines,
    parse_text_taplist,
)
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle
from around_the_grounds.utils.listing_matcher import ListingMatcher

LOGGER = logging.getLogger(__name__)

# Venue configs come from the real site config, so these fixture tests also
# check the published configuration.
_SITE_VENUES = {v.key: v for v in load_site_config("seattle-fall-beers").venues}
CONFIGS: Dict[str, Dict[str, Any]] = {
    name: dict(_SITE_VENUES[key].parser_config or {})
    for name, key in {
        "stoup": "stoup-ballard-taps",
        "reubens": "reubens-ballard-taps",
        "ravenna": "ravenna-taps",
        "flying_lion": "flying-lion-taps",
        "seapine": "seapine-taps",
        "fremont": "fremont-taps",
        "fremont_columbia_city": "fremont-columbia-city-taps",
        "lucky": "lucky-envelope-taps",
        "georgetown": "georgetown-taps",
        "bizarre": "bizarre-taps",
        "obec": "obec-taps",
    }.items()
}


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


def page(html_fixtures_dir: Path, name: str) -> str:
    return (html_fixtures_dir / f"{name}.html").read_text()


def fresh(entries: List[TapEntry]) -> List[TapEntry]:
    matcher = ListingMatcher()
    return [e for e in entries if matcher.matches(e.name, e.style, e.match_text)]


@pytest.mark.parametrize(
    "source_type,parser",
    [
        ("html-taplist", HtmlTaplistParser),
        ("craftpeak-wot", CraftpeakWotParser),
        ("digitalpour", DigitalPourParser),
        ("text-taplist", TextTaplistParser),
    ],
)
def test_source_types_are_registered(source_type: str, parser: type) -> None:
    venue = Venue("some-taproom", "Some Taproom", "https://example.com", source_type)
    assert ParserRegistry.get_parser(venue) is parser


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ABV: | 6.80% | IBU: | Unknown", "6.8%"),  # Stoup
        ("ABV | 6 | % | IBU | 52", "6%"),  # Reuben's
        ("Fresh Hop West Coast IPA, 6.5% ABV. Hops: Fresh Amarillo", "6.5%"),
        ("5.4% ABV 35 IBU", "5.4%"),  # IBU must not be read as ABV
        ("5.9%", "5.9%"),
        ("IBU: 40", None),
        (None, None),
    ],
)
def test_normalize_abv(text: Any, expected: Any) -> None:
    assert normalize_abv(text) == expected


class TestHtmlTaplistConfig:
    def test_item_and_name_are_required(self) -> None:
        with pytest.raises(ValueError, match="item and name"):
            parse_html_taplist("<html></html>", {"item": "li"})

    def test_invalid_section_pattern(self) -> None:
        config = {"item": "li", "name": "b", "exclude_sections": ["("]}
        with pytest.raises(ValueError, match="exclude_sections"):
            parse_html_taplist("<ul><li><b>x</b></li></ul>", config)

    def test_invalid_style_pattern(self) -> None:
        config = {"item": "li", "name": "b", "style_pattern": "("}
        with pytest.raises(ValueError, match="style_pattern"):
            parse_html_taplist("<ul><li><b>x</b></li></ul>", config)

    def test_whole_item_text_is_only_used_when_asked(self) -> None:
        html = "<ul><li><b>Centy</b><p>Fresh Hop IPA</p></li></ul>"
        plain = parse_html_taplist(html, {"item": "li", "name": "b"})
        whole = parse_html_taplist(
            html, {"item": "li", "name": "b", "match_whole_item": True}
        )
        assert fresh(plain) == []
        assert [e.name for e in fresh(whole)] == ["Centy"]
        assert whole[0].match_text == "Centy Fresh Hop IPA"

    def test_items_without_a_name_are_skipped(self) -> None:
        html = "<ul><li><b></b><i>IPA</i></li><li><b>Lush</b></li></ul>"
        entries = parse_html_taplist(html, {"item": "li", "name": "b", "style": "i"})
        assert [e.name for e in entries] == ["Lush"]


class TestCraftpeak:
    @pytest.fixture
    def html(self, html_fixtures_dir: Path) -> str:
        return page(html_fixtures_dir, "craftpeak_cloudburst_ballard")

    def test_on_tap_only(self, html: str) -> None:
        on_tap = parse_html_taplist(html, CraftpeakWotParser.PRESET)
        everything = parse_html_taplist(
            html, {**CraftpeakWotParser.PRESET, "exclude_sections": []}
        )
        assert len(on_tap) == 13
        assert len(everything) == 27  # includes the "To Go" packaged list

    def test_fresh_hops_including_unpublished_beers(self, html: str) -> None:
        entries = fresh(parse_html_taplist(html, CraftpeakWotParser.PRESET))
        assert entries == [
            # Unpublished beer pages: the style stands in for the name.
            TapEntry("Wet Hop IPA"),
            TapEntry("Wet Hop Italian Pilsner"),
            TapEntry("Aqua Seafoam Shame", style="Wet Hop IPA", abv="6.8%"),
            TapEntry("Wet Side Story", style="DDH West Coast Wet Hop DIPA", abv="8%"),
        ]


class TestDigitalPour:
    @pytest.fixture
    def venue(self) -> Venue:
        return Venue(
            "beer-star",
            "Beer Star",
            "https://www.beerstarusa.com/tap-list",
            "digitalpour",
            {"company_id": "590e40cc5e002c09f467f375", "location_id": 1},
        )

    def test_parses_menu(self, html_fixtures_dir: Path) -> None:
        html = page(html_fixtures_dir, "digitalpour_beer_star")
        entries = parse_html_taplist(html, DigitalPourParser.PRESET)

        assert len(entries) == 39
        assert len(fresh(entries)) == 10
        head_start = next(e for e in entries if e.name == "Head Start")
        assert head_start == TapEntry(
            "Head Start", "Snapshot", "Fresh Hop Extra Pale Ale", "5.9%"
        )

    @pytest.mark.asyncio
    async def test_fetches_the_menu_page(
        self, venue: Venue, html_fixtures_dir: Path
    ) -> None:
        url = (
            "https://fbpage.digitalpour.com/"
            "?companyID=590e40cc5e002c09f467f375&locationID=1"
        )
        with aioresponses() as m:
            m.get(
                url, status=200, body=page(html_fixtures_dir, "digitalpour_beer_star")
            )
            async with aiohttp.ClientSession() as session:
                events = await DigitalPourParser(venue).parse(session)

        assert len(events) == 10
        assert all(e.kind == "listing" for e in events)

    @pytest.mark.asyncio
    async def test_missing_ids_raise(self) -> None:
        venue = Venue("x", "X", "https://x.com", "digitalpour", {"company_id": "a"})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="company_id and location_id"):
                await DigitalPourParser(venue).parse(session)


class TestHtmlTaplistVenues:
    def test_stoup(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_stoup"), CONFIGS["stoup"]
        )
        assert len(entries) == 21
        assert [e.abv for e in fresh(entries)] == ["6.8%", "6.3%", "6.9%"]
        assert fresh(entries)[0].name == (
            "Citra Fresh Hop Fiend IPA (2026) - Perrault Farms"
        )

    def test_reubens(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_reubens_ballard"), CONFIGS["reubens"]
        )
        assert len(entries) == 31
        assert [(e.name, e.abv) for e in fresh(entries)][:2] == [
            ("Fresh Hop Crikey™", "6%"),
            ("Sticky Notes: Fresh Hop Extra Pale Ale", "5.4%"),
        ]
        # "Fresh! Raspberry" is on the list but is not a fresh-hop beer.
        assert "Fresh! Raspberry" in [e.name for e in entries]
        assert "Fresh! Raspberry" not in [e.name for e in fresh(entries)]

    def test_ravenna_same_name_different_beers(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_ravenna"), CONFIGS["ravenna"]
        )
        venue = Venue("ravenna", "Ravenna Brewing", "https://x.com")

        events = build_listings(venue, entries, "html", LOGGER)

        amarillo = [e.description for e in events if e.title == "WET SEASON: AMARILLO"]
        assert amarillo == [
            "Fresh Hop West Coast IPA · 6.5%",
            "Fresh Hop Hazy IPA · 6%",
        ]
        assert len(events) == 6

    def test_flying_lion_skips_coming_soon(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_flying_lion"), CONFIGS["flying_lion"]
        )
        assert len(entries) == 20  # 6 more are on the "coming soon" board
        assert fresh(entries)[0] == TapEntry(
            "Ryezomes", style="FRESH HOP Black IPA", abv="6.5%"
        )

    def test_seapine(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_seapine"), CONFIGS["seapine"]
        )
        assert [e.name for e in fresh(entries)] == ["Centy McFreshface Fresh Hop IPA"]

    def test_obec(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_obec"), CONFIGS["obec"]
        )
        assert len(entries) == 11
        assert entries[0].name == "Porter #3"
        assert entries[0].abv == "5.7%"  # from "... ABV 5.7%" in the description
        assert fresh(entries) == []  # no fresh hops on the list today

    @pytest.mark.asyncio
    async def test_parse_fetches_venue_url(self, html_fixtures_dir: Path) -> None:
        url = "https://www.stoupbrewing.com/ontap/"
        venue = Venue("stoup", "Stoup Brewing", url, "html-taplist", CONFIGS["stoup"])
        with aioresponses() as m:
            m.get(url, status=200, body=page(html_fixtures_dir, "taplist_stoup"))
            async with aiohttp.ClientSession() as session:
                events = await HtmlTaplistParser(venue).parse(session)
        assert len(events) == 3
        assert events[0].description == "6.8%"


class TestTextTaplist:
    def test_lines_split_on_breaks_and_blocks(self) -> None:
        html = "<h2>Bar</h2><p>A: IPA<br>B: Pils</p><ul><li>C</li></ul>"
        assert list(iter_lines(html)) == [
            ("h2", "Bar"),
            ("p", "A: IPA"),
            ("p", "B: Pils"),
            ("li", "C"),
        ]

    def test_fremont_main_bar(self, html_fixtures_dir: Path) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_fremont"), CONFIGS["fremont"]
        )
        assert len(entries) == 33
        assert [e.name for e in fresh(entries)] == [
            "Field to Ferment",
            "Fresh Hop Lager",
            "Fresh Hop Lush",
            "Juice Box Hero",
        ]
        assert fresh(entries)[0].style == "Pale Ale Made With Centennial Fresh Hops"

    def test_fremont_columbia_city_strips_footnote_marks(
        self, html_fixtures_dir: Path
    ) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_fremont"),
            CONFIGS["fremont_columbia_city"],
        )
        names = [e.name for e in fresh(entries)]
        assert "Fresh Hop Lager" in names
        assert not any(n.startswith("*") for n in names)

    def test_lucky_envelope(self, html_fixtures_dir: Path) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_lucky_envelope"), CONFIGS["lucky"]
        )
        assert len(entries) == 14
        assert fresh(entries) == [
            TapEntry("Fresh Hop Strata Hazy IPA", abv="6.3%"),
            TapEntry("Fresh Hop Lórien Pilsner", abv="5%"),
        ]

    def test_georgetown_fresh_sheet_only(self, html_fixtures_dir: Path) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_georgetown"), CONFIGS["georgetown"]
        )
        names = [e.name for e in entries]
        assert "Bodhizafa IPA" in names
        assert not any(n.startswith("4oz") for n in names)  # price lines
        assert [e.name for e in fresh(entries)] == ["The Brother's Roy Fresh Hop IPA"]

    def test_bizarre_headings_are_entries(self, html_fixtures_dir: Path) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_bizarre"), CONFIGS["bizarre"]
        )
        assert len(entries) == 12
        assert entries[0] == TapEntry(
            "SKITCH", style="FRESH HOP RICE LAGER", abv="4.2%"
        )
        # Section headings like "GUEST ALCOHOLIC BEVERAGES:" are not beers.
        assert not any("GUEST" in e.name for e in entries)

    def test_bizarre_fresh_hoppy_counts(self, html_fixtures_dir: Path) -> None:
        venue = Venue(
            "bizarre-taps",
            "Bizarre",
            "https://x.com",
            "text-taplist",
            CONFIGS["bizarre"],
        )
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_bizarre"), CONFIGS["bizarre"]
        )
        events = build_listings(venue, entries, "html", LOGGER)
        # "EXTRA FRESH HOPPY TABLE BEER" needs the venue's listing_include.
        assert [e.title for e in events] == ["SKITCH", "GARLANDS", "ZIP ZINGER"]

    def test_headings_are_not_entries_by_default(self) -> None:
        html = "<h2>Fresh Hop A</h2><p>Fresh Hop B</p>"
        config = {"line_pattern": "^(?P<name>.+)$"}
        assert [e.name for e in parse_text_taplist(html, config)] == ["Fresh Hop B"]

    def test_excluded_sections(self) -> None:
        html = "<h2>Main</h2><p>Fresh Hop A</p><h2>Closed</h2><p>Fresh Hop B</p>"
        config = {
            "section_tag": "h2",
            "exclude_sections": ["closed"],
            "line_pattern": "^(?P<name>.+)$",
        }
        assert [e.name for e in parse_text_taplist(html, config)] == ["Fresh Hop A"]

    @pytest.mark.parametrize(
        "config,message",
        [
            ({}, "needs line_pattern"),
            ({"line_pattern": "("}, "Invalid line_pattern"),
            ({"line_pattern": "^(.+)$"}, "name"),
            (
                {"line_pattern": "^(?P<name>.+)$", "include_sections": ["("]},
                "include_sections",
            ),
        ],
    )
    def test_config_errors(self, config: Dict[str, Any], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_text_taplist("<p>x</p>", config)

    @pytest.mark.asyncio
    async def test_parse_fetches_venue_url(self, html_fixtures_dir: Path) -> None:
        url = "https://www.luckyenvelopebrewing.com/currentlyontap"
        venue = Venue(
            "lucky-envelope-taps",
            "Lucky Envelope",
            url,
            "text-taplist",
            CONFIGS["lucky"],
        )
        with aioresponses() as m:
            m.get(
                url, status=200, body=page(html_fixtures_dir, "taplist_lucky_envelope")
            )
            async with aiohttp.ClientSession() as session:
                events = await TextTaplistParser(venue).parse(session)
        assert [e.title for e in events] == [
            "Fresh Hop Strata Hazy IPA",
            "Fresh Hop Lórien Pilsner",
        ]
