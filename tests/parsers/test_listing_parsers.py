"""Tests for the tap-list listing parsers. Fixtures are live responses saved
on 2026-09-29 (trimmed of scripts/styles): Untappd embeds for The Beer
Junction, Bale Breaker Seattle and Urban Family; the Untappd venue page for
The Growler Guys; and Chuck's Hop Shop's Greenwood / Central District sheets."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator
from urllib.parse import unquote

import aiohttp
import pytest
from aioresponses import aioresponses
from freezegun import freeze_time

from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.listing_common import TapEntry, build_listings
from around_the_grounds.parsers.generic.sheet_taplist import (
    SheetTaplistParser,
    parse_sheet_rows,
)
from around_the_grounds.parsers.generic.untappd_embed import (
    UntappdEmbedParser,
    decode_embed_html,
    parse_embed_menu,
)
from around_the_grounds.parsers.generic.untappd_venue import (
    UntappdVenueParser,
    parse_venue_menu,
)
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

LOGGER = logging.getLogger(__name__)

EMBED_URL = "https://business.untappd.com/locations/3026/themes/8580/js"
GROWLER_GUYS_URL = "https://untappd.com/v/the-growler-guys-seattle-northeast/5527415"
SHEET_URL = re.compile(
    r"^https://docs\.google\.com/spreadsheets/d/1zzW5XS9[^/]*/gviz/tq"
)

CHUCKS_CONFIG: Dict[str, Any] = {
    "sheet_id": "1zzW5XS9vlHdsW04pb8uXN_BIJ08HWc6XYFqVCu1ZDCo",
    "sheet_name": "GW",
    "header_contains": "Greenwood",
    "columns": {"name": 2, "style": 1, "abv": 9},
    "brewery_separator": ":",
    "skip_prefix": "-",
    "name_remove": r"\s*\(\.?\d[^)]*L\b[^)]*\)\s*$",
}


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


def _read(fixtures_dir: Path, *parts: str) -> str:
    return fixtures_dir.joinpath(*parts).read_text()


def _embed_script(fixtures_dir: Path, name: str) -> str:
    return _read(fixtures_dir, "js", f"untappd_embed_{name}.js")


class TestRegistry:
    @pytest.mark.parametrize(
        "source_type,parser",
        [
            ("untappd-embed", UntappdEmbedParser),
            ("untappd-venue", UntappdVenueParser),
            ("sheet-taplist", SheetTaplistParser),
        ],
    )
    def test_source_types_are_registered(self, source_type: str, parser: type) -> None:
        venue = Venue("some-bar", "Some Bar", "https://example.com", source_type)
        assert ParserRegistry.get_parser(venue) is parser


class TestBuildListings:
    @freeze_time("2026-09-30 03:00:00")  # 8 PM Sept 29 Pacific
    def test_builds_listing_events(self) -> None:
        venue = Venue("bar", "Bar", "https://example.com")
        entries = [
            TapEntry("Fresh Hop IPA", "Stoup Brewing", "IPA - American", "6.5%"),
            TapEntry("Oktoberfest", "Stoup Brewing", "Märzen", "5.8%"),
        ]

        events = build_listings(venue, entries, "untappd", LOGGER)

        assert [(e.title, e.category) for e in events] == [
            ("Fresh Hop IPA", "fresh-hop"),
            ("Oktoberfest", "festbier"),
        ]
        event = events[0]
        assert event.kind == "listing"
        assert event.description == "Stoup Brewing · IPA - American · 6.5%"
        assert event.extraction_method == "untappd"
        # Site-local day at midnight, so output is stable within the day.
        assert event.date == datetime(2026, 9, 29)

    @freeze_time("2026-09-30 03:00:00")
    def test_timezone_comes_from_parser_config(self) -> None:
        venue = Venue("bar", "Bar", "https://x.com", parser_config={"timezone": "UTC"})
        events = build_listings(venue, [TapEntry("Fresh Hop IPA")], "html", LOGGER)
        assert events[0].date == datetime(2026, 9, 30)

    def test_deduplicates_by_name_and_brewery(self) -> None:
        venue = Venue("bar", "Bar", "https://example.com")
        entries = [
            TapEntry("Fresh Hop IPA", "Stoup"),
            TapEntry("fresh hop ipa", "STOUP"),
            TapEntry("Fresh Hop IPA", "Reuben's"),
        ]

        events = build_listings(venue, entries, "sheet", LOGGER)

        assert [e.description for e in events] == ["Stoup", "Reuben's"]

    def test_style_counts_toward_matching(self) -> None:
        venue = Venue("bar", "Bar", "https://example.com")
        entries = [TapEntry("Aqua Seafoam Shame", "Cloudburst", "Fresh Hop Hazy IPA")]
        assert len(build_listings(venue, entries, "untappd", LOGGER)) == 1

    def test_venue_config_extends_matching(self) -> None:
        venue = Venue(
            "fremont",
            "Fremont",
            "https://example.com",
            parser_config={"listing_include": ["cowiche"]},
        )
        events = build_listings(venue, [TapEntry("Hazy Cowiche")], "html", LOGGER)
        assert [e.title for e in events] == ["Hazy Cowiche"]


class TestUntappdEmbedDecoding:
    def test_decodes_menu_html(self, fixtures_dir: Path) -> None:
        html = decode_embed_html(_embed_script(fixtures_dir, "beer_junction"))
        assert html.lstrip().startswith("<")
        assert "Aqua Seafoam Shame" in html
        assert '\\"' not in html  # JavaScript escapes are gone

    def test_decodes_javascript_only_escapes(self) -> None:
        script = 'x.innerHTML = "<span>\\$4.50 it\\\'s</span>\\n";'
        assert decode_embed_html(script) == "<span>$4.50 it's</span>\n"

    def test_script_without_menu_raises(self) -> None:
        with pytest.raises(ValueError, match="no menu HTML"):
            decode_embed_html("function EmbedMenu() {}")


class TestUntappdEmbedMenu:
    def test_standard_theme_with_brewery(self, fixtures_dir: Path) -> None:
        html = decode_embed_html(_embed_script(fixtures_dir, "beer_junction"))
        entries = parse_embed_menu(html)

        assert len(entries) == 50
        aqua = next(e for e in entries if e.name == "Aqua Seafoam Shame")
        assert aqua == TapEntry(
            "Aqua Seafoam Shame", "Cloudburst Brewing", "Fresh Hop Hazy IPA", "6.8%"
        )
        # Tap numbers ("9.") are not part of the name.
        assert not any(re.match(r"^\d+\.", e.name) for e in entries)

    def test_brewery_own_menu_without_brewery_field(self, fixtures_dir: Path) -> None:
        html = decode_embed_html(_embed_script(fixtures_dir, "bale_breaker"))
        entries = parse_embed_menu(html)

        assert len(entries) == 24
        slicker = next(e for e in entries if e.name.startswith("Citra Slicker"))
        assert slicker.brewery is None
        assert slicker.abv == "6.2%"
        # The hop list in the style slot loses its "---" prefix.
        assert slicker.style is not None and slicker.style.startswith("Citra®")

    def test_table_theme(self, fixtures_dir: Path) -> None:
        html = decode_embed_html(_embed_script(fixtures_dir, "urban_family"))
        entries = parse_embed_menu(html)

        assert len(entries) == 20
        assert entries[0] == TapEntry("Looming Specter", abv="5.5%")

    def test_empty_menu(self) -> None:
        assert parse_embed_menu("<div class='ut-menu'></div>") == []


class TestUntappdEmbedParser:
    @pytest.fixture
    def venue(self) -> Venue:
        return Venue(
            "beer-junction",
            "The Beer Junction",
            "https://www.thebeerjunction.com/tap-list",
            "untappd-embed",
            {"location_id": 3026, "theme_id": 8580},
        )

    @pytest.mark.asyncio
    async def test_parse_returns_fresh_hop_listings(
        self, venue: Venue, fixtures_dir: Path
    ) -> None:
        with aioresponses() as m:
            m.get(
                EMBED_URL, status=200, body=_embed_script(fixtures_dir, "beer_junction")
            )
            async with aiohttp.ClientSession() as session:
                events = await UntappdEmbedParser(venue).parse(session)

        fresh_hops = [e for e in events if e.category == "fresh-hop"]
        assert len(fresh_hops) == 7
        assert all(e.kind == "listing" for e in events)
        assert [e.title for e in events if e.category == "festbier"] == [
            "Bobtoberfest",
            "Oktoberfest Marzen",
            "Festbier",
        ]
        assert fresh_hops[0].title == "Aqua Seafoam Shame"
        assert fresh_hops[0].description == (
            "Cloudburst Brewing · Fresh Hop Hazy IPA · 6.8%"
        )

    @pytest.mark.asyncio
    async def test_missing_ids_raise(self) -> None:
        venue = Venue("bar", "Bar", "https://x.com", "untappd-embed", {})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="location_id and theme_id"):
                await UntappdEmbedParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_http_error_raises(self, venue: Venue) -> None:
        with aioresponses() as m:
            m.get(EMBED_URL, status=404)
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="404"):
                    await UntappdEmbedParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_cloudflare_challenge_is_named(self, venue: Venue) -> None:
        with aioresponses() as m:
            m.get(
                EMBED_URL,
                status=403,
                body="<title>Just a moment...</title>",
                headers={"cf-mitigated": "challenge"},
            )
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="Cloudflare bot challenge"):
                    await UntappdEmbedParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_network_error_raises(self, venue: Venue) -> None:
        with aioresponses() as m:
            m.get(EMBED_URL, exception=aiohttp.ClientConnectionError("boom"))
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="Network error"):
                    await UntappdEmbedParser(venue).parse(session)


class TestUntappdVenue:
    @pytest.fixture
    def html(self, fixtures_dir: Path) -> str:
        return _read(fixtures_dir, "html", "untappd_venue_growler_guys.html")

    def test_parses_menu_items(self, html: str) -> None:
        entries = parse_venue_menu(html)

        assert len(entries) == 52
        kolsch = entries[[e.name for e in entries].index("Fresh Hop Zoigl-Kölsch")]
        assert kolsch == TapEntry(
            "Fresh Hop Zoigl-Kölsch", "Zoiglhaus Brewing Company", "Kölsch", "4.9%"
        )

    def test_item_without_abv(self, html: str) -> None:
        root_beer = next(e for e in parse_venue_menu(html) if e.name == "Root Beer")
        assert root_beer.abv is None

    def test_page_without_published_menu(self) -> None:
        assert parse_venue_menu("<html><body><h1>Chuck's</h1></body></html>") == []

    @pytest.mark.asyncio
    async def test_parse_returns_fresh_hop_listings(self, html: str) -> None:
        venue = Venue(
            "growler-guys", "The Growler Guys", GROWLER_GUYS_URL, "untappd-venue"
        )
        with aioresponses() as m:
            m.get(GROWLER_GUYS_URL, status=200, body=html)
            async with aiohttp.ClientSession() as session:
                events = await UntappdVenueParser(venue).parse(session)

        fresh_hops = [e.title for e in events if e.category == "fresh-hop"]
        assert len(fresh_hops) == 10
        assert "Green Rush Fresh Hop IPA (2026)" in fresh_hops
        festbiers = [e.title for e in events if e.category == "festbier"]
        assert festbiers == ["Festbier", "Octorok"]  # Octorok matches by style


class TestSheetTaplist:
    @pytest.fixture
    def gw_csv(self, csv_fixtures_dir: Path) -> str:
        return (csv_fixtures_dir / "chucks_taplist_gw.csv").read_text()

    def test_splits_brewery_and_strips_markers(self, gw_csv: str) -> None:
        entries = parse_sheet_rows(gw_csv, CHUCKS_CONFIG)

        assert len(entries) == 50
        aqua = next(e for e in entries if e.name.startswith("Aqua Seafoam"))
        assert aqua == TapEntry(
            "Aqua Seafoam Shame - Wet Hop Hazy IPA (Strata)",
            "Cloudburst",
            "IPA/Pale",
            "6.8%",
        )
        assert not any("🌿" in e.name for e in entries)

    def test_skips_kicked_kegs(self, csv_fixtures_dir: Path) -> None:
        cd_csv = (csv_fixtures_dir / "chucks_taplist_cd.csv").read_text()
        config = dict(CHUCKS_CONFIG, header_contains="Central District")

        names = [e.name for e in parse_sheet_rows(cd_csv, config)]

        assert len(names) == 48
        assert not any("Skitch" in n for n in names)

    def test_wrong_tab_is_detected(self, gw_csv: str) -> None:
        config = dict(CHUCKS_CONFIG, header_contains="Seward Park")
        with pytest.raises(ValueError, match="Seward Park"):
            parse_sheet_rows(gw_csv, config)

    def test_invalid_name_remove_raises(self, gw_csv: str) -> None:
        with pytest.raises(ValueError, match="name_remove"):
            parse_sheet_rows(gw_csv, dict(CHUCKS_CONFIG, name_remove="("))

    def test_name_column_is_required(self, gw_csv: str) -> None:
        with pytest.raises(ValueError, match="columns.name"):
            parse_sheet_rows(gw_csv, {"columns": {"style": 1}})

    def test_without_separator_keeps_full_name(self) -> None:
        csv_text = "Beer\n🌿Stoup: Fresh Hop Fiend🌿\n\n"
        entries = parse_sheet_rows(csv_text, {"columns": {"name": 0}})
        assert entries == [TapEntry("Stoup: Fresh Hop Fiend")]

    def test_short_rows_are_tolerated(self) -> None:
        csv_text = "Tap,Beer,ABV\n1,Fresh Hop IPA\n2\n"
        config = {"columns": {"name": 1, "abv": 2}}
        assert parse_sheet_rows(csv_text, config) == [TapEntry("Fresh Hop IPA")]

    @pytest.mark.asyncio
    async def test_parse_requests_the_named_tab(self, gw_csv: str) -> None:
        venue = Venue(
            "chucks-greenwood-taps",
            "Chuck's Hop Shop Greenwood",
            "https://www.chuckshopshop.com/taplistgw",
            "sheet-taplist",
            CHUCKS_CONFIG,
        )
        with aioresponses() as m:
            m.get(SHEET_URL, status=200, body=gw_csv)
            async with aiohttp.ClientSession() as session:
                events = await SheetTaplistParser(venue).parse(session)
            (_, url), _ = next(iter(m.requests.items()))

        assert url.query["sheet"] == "GW"
        assert unquote(url.query["tqx"]) == "out:csv"
        fresh_hops = [e for e in events if e.category == "fresh-hop"]
        assert len(fresh_hops) == 15
        assert fresh_hops[0].description == "Cloudburst · IPA/Pale · 6.8%"
        # Serving sizes are cut from names by name_remove.
        assert [e.title for e in events if e.category == "festbier"] == [
            "Spider Dance - Festbier",
            "Behind The Rows - Festbier Lager",
        ]

    @pytest.mark.asyncio
    async def test_missing_sheet_config_raises(self) -> None:
        venue = Venue("x", "X", "https://x.com", "sheet-taplist", {"sheet_id": "abc"})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="sheet_id and sheet_name"):
                await SheetTaplistParser(venue).parse(session)
