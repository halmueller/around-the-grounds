"""Tests for the selector-driven (html-taplist, craftpeak-wot, digitalpour),
line-driven (text-taplist) and Bevwerk API (bevwerk) tap-list parsers.
Fixtures are live pages saved on 2026-09-29, stripped of scripts, styles and
most attributes; the Bevwerk response is trimmed to the fields read."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.bevwerk import (
    GRAPHQL_URL,
    BevwerkParser,
    parse_bevwerk_menu,
)
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
_SITE_VENUES = {v.key: v for v in load_site_config("seattle-freshies").venues}
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
        "growler_guys": "growler-guys-taps",
        "stoup_capitol_hill": "stoup-capitol-hill-taps",
        "old_stove_gardens": "old-stove-gardens-taps",
        "die_bierstube": "die-bierstube-taps",
        "big_time": "big-time-taps",
        "machine_house": "machine-house-taps",
        "ladd_and_lass": "ladd-and-lass-taps",
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
        ("bevwerk", BevwerkParser),
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

        assert len([e for e in events if e.category == "fresh-hop"]) == 10
        assert all(e.kind == "listing" for e in events)
        assert [e.title for e in events if e.category == "festbier"] == [
            "Oktoberfest",
            "Flocktoberfest",
        ]

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
        assert len([e for e in events if e.category == "fresh-hop"]) == 6
        # The Dunkel counts as a festbier.
        assert [e.title for e in events if e.category == "festbier"] == [
            "Midnight in Bavaria"
        ]

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
        # Cans To Go repeats the draft list with prices; it is skipped.
        assert not any("$" in e.name for e in entries)
        venue = _SITE_VENUES["seapine-taps"]
        events = build_listings(venue, entries, "html", LOGGER)
        # A Helles, listed as a festbier by the venue's festbier_include.
        assert [e.title for e in events if e.category == "festbier"] == [
            "Munich Mist Helles Lager"
        ]

    def test_obec(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_obec"), CONFIGS["obec"]
        )
        assert len(entries) == 11
        assert entries[0].name == "Porter #3"
        assert entries[0].abv == "5.7%"  # from "... ABV 5.7%" in the description
        assert fresh(entries) == []  # no fresh hops on the list today

    def test_stoup_location_page(self, html_fixtures_dir: Path) -> None:
        # Capitol Hill and Kenmore share this layout (Ballard's differs).
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_stoup_capitol_hill"),
            CONFIGS["stoup_capitol_hill"],
        )
        assert len(entries) == 24
        assert [(e.name, e.abv) for e in fresh(entries)] == [
            ("Citra Fresh Hop Fiend IPA (2026) - Perrault Farms", "6.8%"),
            ("Simcoe Fresh Hop Fiend 2026 (Perrault Farms)", "6.7%"),
            ("Dolcita Fresh Hop Fiend Hazy IPA-Perrault Farms", "6.3%"),
        ]

    def test_squarespace_menu_draft_tab_only(self, html_fixtures_dir: Path) -> None:
        # Die Bierstube and its Prost! sister pubs share this layout.
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_die_bierstube"), CONFIGS["die_bierstube"]
        )
        # 15 drafts; bottles, cocktails, and wine are later tabs.
        assert len(entries) == 15
        assert "Aecht Rauchbier Märzen ,5L" not in [e.name for e in entries]
        venue = _SITE_VENUES["die-bierstube-taps"]
        events = build_listings(venue, entries, "html", LOGGER)
        assert [e.title for e in events if e.category == "festbier"] == [
            "Hacker-Pschorr Munich Dunkel",
            "Hacker-Pschorr Oktoberfest",
            "Hofbräu Oktoberfest",
        ]

    def test_big_time_menu_blocks_and_name_pattern(
        self, html_fixtures_dir: Path
    ) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_big_time"), CONFIGS["big_time"]
        )
        # Every menu block is read: beer, cider/seltzer, wine, liquor, NA.
        assert len(entries) == 31
        by_name = {e.name: e for e in entries}
        # ABV and IBU are trimmed from the name, before or after the ABV.
        assert by_name["Prime Time"].abv == "5.4%"
        assert by_name["Hoponessa IPA"].abv == "6%"
        # A name the pattern doesn't fit is kept whole.
        assert "Pinot Noir - CA" in by_name
        venue = _SITE_VENUES["big-time-taps"]
        events = build_listings(venue, entries, "html", LOGGER)
        assert [(e.category, e.title, e.description) for e in events] == [
            ("fresh-hop", "Citra Pants Fresh Hop", "6.6%"),
        ]

    def test_name_pattern_needs_name_group(self) -> None:
        with pytest.raises(ValueError, match="name_pattern needs"):
            parse_html_taplist(
                "<div class=b>X</div>",
                {"item": ".b", "name": ".b", "name_pattern": "^(.+)$"},
            )

    def test_invalid_name_pattern(self) -> None:
        with pytest.raises(ValueError, match="Invalid name_pattern"):
            parse_html_taplist(
                "<div class=b>X</div>",
                {"item": ".b", "name": ".b", "name_pattern": "(?P<name>"},
            )

    def test_old_stove_wix_menu(self, html_fixtures_dir: Path) -> None:
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_old_stove_gardens"),
            CONFIGS["old_stove_gardens"],
        )
        by_name = {e.name: e for e in entries}
        # The style comes after IBU in the description line.
        assert by_name["STRATA FRESH HOP"] == TapEntry(
            "STRATA FRESH HOP", style="West Coast IPA", abv="7.7%"
        )
        assert by_name["THE CLAW"].style == "Smoked Märzen"
        venue = _SITE_VENUES["old-stove-gardens-taps"]
        events = build_listings(venue, entries, "html", LOGGER)
        assert [(e.category, e.title) for e in events] == [
            ("festbier", "FESTBIER"),
            ("festbier", "THE CLAW"),
            ("fresh-hop", "STRATA FRESH HOP"),
        ]

    def test_growler_guys(self, html_fixtures_dir: Path) -> None:
        config = CONFIGS["growler_guys"]
        entries = parse_html_taplist(
            page(html_fixtures_dir, "taplist_growler_guys"), config
        )
        assert len(entries) == 60
        assert entries[0] == TapEntry("Root Beer", "Diamond Knot", "Root Beer")
        green_rush = next(e for e in entries if e.name.startswith("Green Rush"))
        assert green_rush == TapEntry(
            "Green Rush Fresh Hop IPA (2026)",
            "Bale Breaker / Russian River",
            "Fresh Hop",
            "6.9%",
        )
        venue = Venue("growler-guys-taps", "The Growler Guys", "https://x.com")
        venue.parser_config = config
        events = build_listings(venue, entries, "html", LOGGER)
        titles = [e.title for e in events if e.category == "fresh-hop"]
        assert len(titles) == 21
        # Named only by the venue's listing_include patterns.
        assert "Wet Season '26 --Tettnang" in titles
        assert "Fresh Pine (Fresh Amarillo Hopped)" in titles
        assert [e.title for e in events if e.category == "festbier"] == [
            "Festbier",
            "Oktorok -- Marzen Lager",
        ]

    @pytest.mark.asyncio
    async def test_parse_fetches_venue_url(self, html_fixtures_dir: Path) -> None:
        url = "https://www.stoupbrewing.com/ontap/"
        venue = Venue("stoup", "Stoup Brewing", url, "html-taplist", CONFIGS["stoup"])
        with aioresponses() as m:
            m.get(url, status=200, body=page(html_fixtures_dir, "taplist_stoup"))
            async with aiohttp.ClientSession() as session:
                events = await HtmlTaplistParser(venue).parse(session)
        assert [e.category for e in events] == ["fresh-hop"] * 3 + ["festbier"]
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
        assert [e.title for e in events if e.category == "fresh-hop"] == [
            "SKITCH",
            "GARLANDS",
            "ZIP ZINGER",
        ]
        assert [e.title for e in events if e.category == "festbier"] == [
            "BEHIND THE ROWS"
        ]

    def test_machine_house_now_on_tap_only(self, html_fixtures_dir: Path) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_machine_house"), CONFIGS["machine_house"]
        )
        # Cask, draft, and guest taps; cans and bottles are later sections.
        assert len(entries) == 11
        assert entries[0] == TapEntry("Dark Mild", abv="3.7%")  # status tag dropped
        assert entries[-1].name == "Yonder Cider [cans]"  # trailing dash dropped
        assert "Totally Fuggled" not in [e.name for e in entries]

    def test_ladd_and_lass_numbered_taps(self, html_fixtures_dir: Path) -> None:
        entries = parse_text_taplist(
            page(html_fixtures_dir, "taplist_ladd_and_lass"), CONFIGS["ladd_and_lass"]
        )
        assert len(entries) == 13
        assert [e.name for e in fresh(entries)] == [
            "Fresh Hop Howdy, Friend",
            "Fresh Hop Cloud Sipper",
        ]

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
        assert [(e.title, e.category) for e in events] == [
            ("Fresh Hop Strata Hazy IPA", "fresh-hop"),
            ("Ground Provisions Harvest Lager", "festbier"),
            ("Fresh Hop Lórien Pilsner", "fresh-hop"),
        ]


class TestBevwerk:
    @pytest.fixture
    def payload(self, fixtures_dir: Path) -> Dict[str, Any]:
        data: Dict[str, Any] = json.loads(
            (fixtures_dir / "json" / "bevwerk_watershed.json").read_text()
        )
        return data

    @pytest.fixture
    def venue(self) -> Venue:
        return Venue(
            "watershed-taps",
            "Watershed Pub & Kitchen",
            "https://watershedpub.com/lets-drink",
            "bevwerk",
            {"taplist_id": "3670c864-6020-4ec6-9088-53bd97020edd"},
        )

    def test_parses_menu(self, payload: Dict[str, Any]) -> None:
        entries = parse_bevwerk_menu(payload)
        assert len(entries) == 21
        assert entries[0] == TapEntry("Czech Plz Czech Pilsner", "Odd Otter", abv="5%")
        assert [e.name for e in fresh(entries)] == [
            "Fresh Hop Festbier Lager",
            "One Thousand Deaths Centennial Wet Hop IPA",
            "Fresh Digs Fresh Hop West Coast IPA",
            "Bug Fresh Hop Hazy IPA",
            "Aqua Seafoam Shame Wet Hop IPA",
            "Ryezomes Fresh Hop Black IPA",
        ]

    def test_only_taps_pouring_now(self, payload: Dict[str, Any]) -> None:
        taps = payload["data"]["menu_data"][0]["data"]["taplist_by_pk"]["taps"]
        taps[0]["on_tap_item"]["status"] = "ON_DECK"
        taps[1]["on_tap_item"]["inventory_type"]["menu_category"]["is_up_next"] = True
        taps[2]["on_tap_item"] = None  # empty tap
        names = [e.name for e in parse_bevwerk_menu(payload)]
        assert len(names) == 18
        assert "Czech Plz Czech Pilsner" not in names

    def test_display_name_and_abv_formats(self) -> None:
        tap = {
            "on_tap_item": {
                "status": "ON_TAP",
                "inventory_type": {
                    "product": {
                        "title": "Long Title",
                        "display_name": " Short ",
                        "abv": "6.5%",
                        "style": "IPA",
                        "producer": {"title": "Brewery Co.", "display_name": ""},
                    }
                },
            }
        }
        payload = {
            "data": {"menu_data": [{"data": {"taplist_by_pk": {"taps": [tap]}}}]}
        }
        assert parse_bevwerk_menu(payload) == [
            TapEntry("Short", "Brewery Co.", "IPA", "6.5%")
        ]

    @pytest.mark.parametrize(
        "payload,message",
        [
            ({"errors": [{"message": "bad uuid"}]}, "API error"),
            ({"data": {}}, "no menu_data"),
            ({"data": {"menu_data": []}}, "no menu for this taplist_id"),
        ],
    )
    def test_bad_responses(self, payload: Dict[str, Any], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_bevwerk_menu(payload)

    @pytest.mark.asyncio
    async def test_posts_the_taplist_query(
        self, venue: Venue, payload: Dict[str, Any]
    ) -> None:
        with aioresponses() as m:
            m.post(GRAPHQL_URL, status=200, payload=payload)
            async with aiohttp.ClientSession() as session:
                events = await BevwerkParser(venue).parse(session)
            ((_, _), [call]) = next(iter(m.requests.items()))
            body = call.kwargs["json"]

        assert body["variables"] == {"taplist_id": venue.parser_config["taplist_id"]}
        assert "menu_data" in body["query"]
        assert all(e.kind == "listing" for e in events)
        assert len([e for e in events if e.category == "fresh-hop"]) == 6
        assert [e.title for e in events if e.category == "festbier"] == [
            "Fresh Hop Festbier Lager",
            "Excessive Celebrations Festbier Lager",
            "Munsterfest Oktoberfest Märzen Lager",
        ]

    @pytest.mark.asyncio
    async def test_invalid_json(self, venue: Venue) -> None:
        with aioresponses() as m:
            m.post(GRAPHQL_URL, status=200, body="<html>oops</html>")
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="invalid JSON"):
                    await BevwerkParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_missing_taplist_id(self) -> None:
        venue = Venue("x", "X", "https://x.com", "bevwerk", {})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="needs taplist_id"):
                await BevwerkParser(venue).parse(session)
