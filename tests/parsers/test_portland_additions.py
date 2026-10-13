"""Tap lists added for the portland-freshies site.

The pages here are cut-down copies of the venues' own markup (2026-10-12).
"""

import logging
from typing import Any, Dict, List

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Event
from around_the_grounds.parsers.generic.html_taplist import parse_html_taplist
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.generic.pdf_taplist import (
    find_pdf_link,
    parse_pdf_taplist,
)
from around_the_grounds.parsers.generic.text_taplist import parse_text_taplist

LOGGER = logging.getLogger(__name__)
VENUES = {v.key: v for v in load_site_config("portland-freshies").venues}


def summary(events: List[Event]) -> List[List[Any]]:
    return [[e.title, e.category, e.description] for e in events]


BRUJOS = """
<div class="sqs-html-content">
<p><a><strong>Gift Cards Available</strong></a></p>
<p><strong>Current Draft List:</strong></p><p></p>
<p><span><strong>Montgomery Park — 4.2%</strong></span></p>
<p>Neighborhood Lager</p><p></p>
<p><span><strong>Faustian Luminary</strong> <strong>— 5.6% </strong></span></p>
<p>Fresh Hopped, Hoppy Pilsner starring Fresh Luminosa hops from Indie Hops</p>
<p></p>
<p><span><strong>FH Populus — 7.5%</strong></span></p>
<p>DDH version of our core-ish Hazy India Pale Ale</p>
<p><span><strong>Where Flowers Burn — 7%</strong></span></p>
<p>DDH West Coast India Pale Ale featuring Centennial from Goschie Farms</p>
<p>A collaborative liquid spell, fresh hopped, with Fidens.</p>
<p><span><strong>Tres Maledicti — 13%</strong></span></p>
<p>Our highest octane QIPA to date.</p>
<p>A three way collaborative liquid spell with Xul and Omnipollo.</p>
<p>Not a fresh hop beer, whatever this third line says.</p>
<p><strong>More Available To-Go Can</strong></p>
</div>
"""

WAYFINDER = """
<h1>OUR BEER</h1>
<p><strong>HELL FREEZES OVER</strong></p>
<p>Our Rice Lager with a Frozen Lemonade Float.</p>
<p>(ABV 5.3%) 0.5L $8</p>
<p><strong>HARVEST MOON - HARVEST LAGER</strong></p>
<p>Harvest time lager not to be mistaken with a fresh hop lager.</p>
<p>(ABV 5.2%) 0.5L $7</p>
<p><strong>GREEN GOBLIN - IPA</strong></p>
<p>Our fresh hop IPA, with Strata straight from the field.</p>
<p>(ABV 6.5%) 0.5L $7.50</p>
<h2>BOILERMAKERS</h2>
<p>Party Time Half Pour &amp; Frozen Amaro $12</p>
<h2>FOOD</h2>
<p><strong>OKTOBERFEST PRETZEL</strong></p>
<p>With fresh hop mustard.</p>
"""


class TestDetailLines:
    def test_brujos_fresh_hops_named_only_in_the_line_below(self) -> None:
        venue = VENUES["brujos-taps"]
        entries = parse_text_taplist(BRUJOS, venue.parser_config or {})

        assert [(e.name, e.abv) for e in entries] == [
            ("Montgomery Park", "4.2%"),
            ("Faustian Luminary", "5.6%"),
            ("FH Populus", "7.5%"),
            ("Where Flowers Burn", "7%"),
            ("Tres Maledicti", "13%"),
        ]
        assert entries[0].description == "Neighborhood Lager"
        # Two lines at most belong to a beer; the third is not read.
        assert entries[4].description == (
            "Our highest octane QIPA to date. "
            "A three way collaborative liquid spell with Xul and Omnipollo."
        )
        events = build_listings(venue, entries, "html", LOGGER)
        assert summary(events) == [
            ["Faustian Luminary", "fresh-hop", "5.6%"],
            ["FH Populus", "fresh-hop", "7.5%"],
            ["Where Flowers Burn", "fresh-hop", "7%"],
        ]

    def test_wayfinder_beer_section_only_and_abv_from_the_detail(self) -> None:
        venue = VENUES["wayfinder-taps"]
        entries = parse_text_taplist(WAYFINDER, venue.parser_config or {})

        # Nothing after the first h2: no boilermakers, no pretzel.
        assert [(e.name, e.style, e.abv) for e in entries] == [
            ("HELL FREEZES OVER", None, "5.3%"),
            ("HARVEST MOON", "HARVEST LAGER", "5.2%"),
            ("GREEN GOBLIN", "IPA", "6.5%"),
        ]
        events = build_listings(venue, entries, "html", LOGGER)
        # Harvest Moon is a harvest lager, and says itself it is no fresh hop.
        assert summary(events) == [
            ["HARVEST MOON", "festbier", "HARVEST LAGER · 5.2%"],
            ["GREEN GOBLIN", "fresh-hop", "IPA · 6.5%"],
        ]

    def test_without_detail_lines_nothing_changes(self) -> None:
        config = {"line_pattern": r"^(?P<name>[^—]+?)\s*—\s*(?P<abv>[\d.]+%)"}
        entries = parse_text_taplist(BRUJOS, config)

        assert len(entries) == 5
        assert all(e.description is None for e in entries)

    def test_detail_stops_at_the_next_beer_and_at_a_section(self) -> None:
        html = (
            "<h2>Draft</h2><p>One — 5%</p><p>Two — 6%</p><p>about two</p>"
            "<h2>Cans</h2><p>not about two</p><p>Three — 7%</p>"
        )
        config = {
            "line_pattern": r"^(?P<name>\w+) — (?P<abv>\d+%)$",
            "section_tag": "h2",
            "detail_lines": 3,
        }
        entries = parse_text_taplist(html, config)

        assert [(e.name, e.description) for e in entries] == [
            ("One", None),
            ("Two", "about two"),
            ("Three", None),
        ]

    def test_detail_lines_follow_heading_entries(self) -> None:
        html = (
            "<h3>Big Beer</h3><p>Fresh hop pale ale, 5.5%</p><h3>Other</h3>"
            "<h3>not a beer</h3><p>nor about one</p>"
        )
        config = {
            "line_pattern": r"^(?P<name>[A-Z].+)$",
            "line_tags": ["h3"],
            "detail_lines": 1,
        }
        entries = parse_text_taplist(html, config)

        assert [(e.name, e.description, e.abv) for e in entries] == [
            ("Big Beer", "Fresh hop pale ale, 5.5%", "5.5%"),
            ("Other", None, None),
        ]

    @pytest.mark.parametrize("value", [-1, "2", 1.5])
    def test_bad_detail_lines_raises(self, value: Any) -> None:
        config: Dict[str, Any] = {"line_pattern": "(?P<name>.+)", "detail_lines": value}
        with pytest.raises(ValueError, match="detail_lines"):
            parse_text_taplist("<p>x</p>", config)


STORMBREAKER = """
<h2>IPAs, Hazies &amp; Pales</h2>
<div class="food-item-holder"><div class="food-item-title"><h3>Fresh Hop Oregon IPA</h3>
</div><div class="food-price">$8.50/Pint</div><div class="food-item-description">
Fresh Hop West Coast IPA | 6.4% ABV | 60 IBU • Fresh Strata.</div></div>
<h2>Ales &amp; Seasonal</h2>
<div class="food-item-holder"><div class="food-item-title"><h3>StormToberfest</h3></div>
<div class="food-price">$7.50/Pint</div><div class="food-item-description">
Märzen | 5.7% ABV | 22 IBU • Malty.</div></div>
<h2>Flights</h2>
<div class="food-item-holder"><div class="food-item-title"><h3>HoptoberFresh Flight</h3>
</div><div class="food-item-description">Four fresh hop beers.</div></div>
<h2>To - Go Beer</h2>
<div class="food-item-holder"><div class="food-item-title"><h3>Stormtoberfest</h3></div>
<div class="food-item-description">4-pack | 5.6% ABV</div></div>
<h2>Cocktails</h2>
<div class="food-item-holder"><div class="food-item-title"><h3>Pumpkin Spice Mule</h3>
</div><div class="food-item-description">Vodka, pumpkin, ginger beer.</div></div>
"""


class TestConfiguredVenues:
    @pytest.mark.parametrize(
        "key", ["stormbreaker-st-johns-taps", "stormbreaker-mississippi-taps"]
    )
    def test_stormbreaker_draft_sections_only(self, key: str) -> None:
        venue = VENUES[key]
        entries = parse_html_taplist(STORMBREAKER, venue.parser_config or {})
        events = build_listings(venue, entries, "html", LOGGER)

        # No flight, no to-go four-pack, no cocktail.
        assert summary(events) == [
            ["Fresh Hop Oregon IPA", "fresh-hop", "Fresh Hop West Coast IPA · 6.4%"],
            ["StormToberfest", "festbier", "Märzen · 5.7%"],
        ]

    def test_montavilla_on_tap_now_menu(self) -> None:
        html = """
        <ul class="menu">
          <li class="menu-item"><a>Visit Us</a></li>
          <li class="menu-item menu-item-has-children"><a>On Tap Now</a>
            <ul class="sub-menu">
              <li class="menu-item"><a>Academy Amber</a></li>
              <li class="menu-item"><a>Fresh Hop Flam Tap IPA</a></li>
            </ul></li>
          <li class="menu-item menu-item-has-children"><a>Shop</a>
            <ul class="sub-menu"><li class="menu-item"><a>Fresh Hop Shirt</a></li></ul>
          </li>
        </ul>
        """
        venue = VENUES["montavilla-taps"]
        entries = parse_html_taplist(html, venue.parser_config or {})

        assert [e.name for e in entries] == ["Academy Amber", "Fresh Hop Flam Tap IPA"]

    def test_flyboy_numbered_taps_and_no_cans_line(self) -> None:
        html = """
        <h2>Whiskey</h2>
        <div class="food-item-holder"><div class="food-item-title">
          <h3>Fall Fashioned Cocktail</h3></div>
          <div class="food-item-description">Bourbon, pumpkin spice syrup</div></div>
        <h2>Beers</h2>
        <div class="food-item-holder"><div class="food-item-title">
          <h3>1: Flyboy Brewing Fresh Hop Island Jumper IPA</h3></div>
          <div class="food-item-description">American IPA, ABV 7.0%</div></div>
        <div class="food-item-holder"><div class="food-item-title">
          <h3>Available in Cans</h3></div>
          <div class="food-item-description">Fresh hop IPA, Pilsner</div></div>
        """
        venue = VENUES["flyboy-taps"]
        entries = parse_html_taplist(html, venue.parser_config or {})
        events = build_listings(venue, entries, "html", LOGGER)

        assert summary(events) == [
            ["Flyboy Brewing Fresh Hop Island Jumper IPA", "fresh-hop", "7%"]
        ]


class TestPdfMenus:
    def test_pfriem_names_are_followed_by_pour_sizes(self) -> None:
        lines = [
            "Belgian-Inspired",
            "PUMPKIN BIER",
            "8oz - 6.50 / 12oz - 7.50",
            "7.3%, 15 IBU | Fresh Ground Spice, Fluffy , Pumpkin Pie",
            "Lagers",
            "OKTOBERFEST (SIDE PULL)",
            "12oz - 6.50 / 16oz - 7.50",
            "PFRIEM + FORT GEORGE",
            "VACATION DESTINATION WEST COAST IPA",
            "8oz - 5.50 / 12oz - 6.50 / 16oz - 7.50",
            "FRESH HOP KRUSH HAZY IPA",
            "8oz - 5.50 / 12oz - 6.50 / 16oz - 7.50",
            "CADILLAC MARGARITA - 15",
            "Reposado, Lime, Orange Cognac",
        ]
        venue = VENUES["pfriem-milwaukie-taps"]
        entries = parse_pdf_taplist(lines, venue.parser_config or {})

        # The collaboration credit and the cocktail are not beers.
        assert [e.name for e in entries] == [
            "PUMPKIN BIER",
            "OKTOBERFEST (SIDE PULL)",
            "VACATION DESTINATION WEST COAST IPA",
            "FRESH HOP KRUSH HAZY IPA",
        ]
        events = build_listings(venue, entries, "html", LOGGER)
        assert [[e.title, e.category] for e in events] == [
            ["PUMPKIN BIER", "pumpkin"],
            ["OKTOBERFEST (SIDE PULL)", "festbier"],
            ["FRESH HOP KRUSH HAZY IPA", "fresh-hop"],
        ]

    def test_pfriem_menu_is_found_by_its_link_text(self) -> None:
        page = (
            '<a href="/docs/2026-TR-Milwaukie-FoodMenu-10.7.pdf">Food Menu</a>'
            '<a href="/docs/2026-TR-Milwaukie-DraftMenu-10.9.pdf">Beer Menu</a>'
            '<a href="/docs/pFriem-2026-BeerGuide.pdf">2026 Package Beer Guide</a>'
        )
        venue = VENUES["pfriem-milwaukie-taps"]
        url = find_pdf_link(
            page, venue.url, (venue.parser_config or {})["link_pattern"]
        )
        assert (
            url
            == "https://www.pfriembeer.com/docs/2026-TR-Milwaukie-DraftMenu-10.9.pdf"
        )

    @pytest.mark.parametrize(
        "key", ["steeplejack-broadway-taps", "steeplejack-sw-taps"]
    )
    def test_steeplejack_beers_have_tasting_notes_cocktails_do_not(
        self, key: str
    ) -> None:
        lines = [
            "SIGNATURE COCKTAILS",
            "SPICY BLOODY MARY 13",
            "garlic and dill infused vodlka. house spicy bloody mix",
            "PUMPKIN SPICE MARTINI",
            "vodka, pumpkin, cream",
            "LIGHT",
            "OKTOBERFEST",
            "sweet / malty / bready",
            "abv 5%",
            "JEHOVAH'S WIT",
            "| brewed with apricot & peach purée |",
            "FIZZY BISCUITS FRESH HOP HAZY IPA",
            "juicy / soft / citrus",
            "STEEPLEJACK BREWING 12OZ",
            "IPA / oktoberfest / pilsner 5",
        ]
        venue = VENUES[key]
        entries = parse_pdf_taplist(lines, venue.parser_config or {})

        assert [e.name for e in entries] == [
            "OKTOBERFEST",
            "JEHOVAH'S WIT",
            "FIZZY BISCUITS FRESH HOP HAZY IPA",
        ]

    def test_grand_fir_beers_have_a_style_and_abv_line(self) -> None:
        lines = [
            "Cocktails",
            "texas sun",
            "altos reposado tequila, fresh lime, berry-",
            "16",
            "Rhody",
            "Fresh hop XPA feat. audacia hops | 5.6% ABV",
            "juicy peach, pink guava, black currant",
            "9",
            "PINK SKY",
            "WEST COAST IPA | 6.5% ABV",
        ]
        venue = VENUES["grand-fir-taps"]
        entries = parse_pdf_taplist(lines, venue.parser_config or {})

        assert [(e.name, e.style, e.abv) for e in entries] == [
            ("Rhody", "Fresh hop XPA feat. audacia hops", "5.6%"),
            ("PINK SKY", "WEST COAST IPA", "6.5%"),
        ]


class TestMoreTextLists:
    def test_living_haus_style_line_decides(self) -> None:
        html = """
        <h2>CORE BEERS</h2>
        <p>DOLORES | DRAFT &amp; TO-GO</p><p>PILSNER•4.8% ABV</p>
        <p>Dolores is our beloved Pilsner beer.</p>
        <h2>ONE-OFFS</h2>
        <p>GAYLE | DRAFT &amp; TO-GO</p><p>FRESH HOP KELLER PILSNER•5.0% ABV</p>
        <p>Gayle is a fourth generation hop farmer.</p>
        <p>BENJAMIN JUNE | DRAFT</p><p>FESTBIER•5.2% ABV</p><p>Our festbier.</p>
        <p>OLD CANS | TO-GO</p><p>FRESH HOP IPA•6% ABV</p>
        """
        venue = VENUES["living-haus-taps"]
        entries = parse_text_taplist(html, venue.parser_config or {})
        events = build_listings(venue, entries, "html", LOGGER)

        assert [e.name for e in entries] == ["DOLORES", "GAYLE", "BENJAMIN JUNE"]
        assert summary(events) == [
            ["GAYLE", "fresh-hop", "5%"],
            ["BENJAMIN JUNE", "festbier", "5.2%"],
        ]

    def test_threshold_taplist_section(self) -> None:
        html = """
        <h2>Fresh Hop Finish Line Party - this Friday!</h2>
        <p>403 SE 79th Ave</p>
        <h2>taplist.</h2>
        <p>Updated October 6</p>
        <p>Just Tapped FRESH HOP Find Your Friends ESB, with fresh Crystal hops, 5%</p>
        <p>FRESH HOP Dozynki White Ale with fresh Lorien hops from Indie Hops, 5.5%</p>
        <p>Piwo Polish Pilsner, brewed with Polish Lubelski hops, 5.4%</p>
        <p>CASK: Just Tapped FRESH HOP Find Your Friends ESB with Crystal hops, 5%</p>
        <p>Rotating local draft cider: Bull Run Cider - Blueberry Lemon - 6.5%</p>
        <h2>food.</h2>
        <p>Pumpkin pierogi, with fresh hop butter, 100% delicious</p>
        """
        venue = VENUES["threshold-taps"]
        entries = parse_text_taplist(html, venue.parser_config or {})

        assert [(e.name, e.abv) for e in entries] == [
            ("FRESH HOP Find Your Friends ESB", "5%"),
            ("FRESH HOP Dozynki White Ale", "5.5%"),
            ("Piwo Polish Pilsner", "5.4%"),
        ]

    def test_upright_beer_station_heading_per_beer(self) -> None:
        html = """
        <h4>Location</h4><p>7151 NE Prescott, Portland OR 97218</p>
        <h3>Draft List</h3>
        <h4>Oak Union Mabon</h4><p>Märzen lager.</p><p>6.1%</p>
        <h4>Ghost Town Dank Dive</h4><p>WC IPA.</p><p>7%</p>
        <h4>Machine House Simcoe Bitter</h4><p>Fresh hop bitter on cask.</p><p>4%</p>
        <h3>Bottles</h3>
        <h4>Some Fresh Hop Bottle</h4><p>To go.</p>
        """
        venue = VENUES["upright-beer-station-taps"]
        entries = parse_text_taplist(html, venue.parser_config or {})
        events = build_listings(venue, entries, "html", LOGGER)

        assert [(e.name, e.abv) for e in entries] == [
            ("Oak Union Mabon", "6.1%"),
            ("Ghost Town Dank Dive", "7%"),
            ("Machine House Simcoe Bitter", "4%"),
        ]
        assert summary(events) == [
            ["Oak Union Mabon", "festbier", "6.1%"],
            ["Machine House Simcoe Bitter", "fresh-hop", "4%"],
        ]

    def test_mad_cow_numbered_taps(self) -> None:
        html = """
        <h1>Beer Menu brewpub brewery tap room Gresham</h1>
        <h4>1 - Kelly Creek Pilsner</h4><p>A crisp, clean pilsner.</p>
        <h4>2 -Huckleberry Cream Ale</h4><p>Our award-winning Huckleberry.</p>
        <h4>12 - Hay Bale Pale Ale - Fresh Hop</h4><p>Our English Pale Ale.</p>
        <h4>13 - Watermelon Sour</h4>
        <h4>Cider</h4><p>Pumpkin cider from a friend.</p>
        """
        venue = VENUES["mad-cow-taps"]
        entries = parse_text_taplist(html, venue.parser_config or {})
        events = build_listings(venue, entries, "html", LOGGER)

        assert [e.name for e in entries] == [
            "Kelly Creek Pilsner",
            "Huckleberry Cream Ale",
            "Hay Bale Pale Ale - Fresh Hop",
            "Watermelon Sour",
        ]
        # The cider heading is not a tap, so its paragraph belongs to no beer.
        assert entries[3].description is None
        assert summary(events) == [["Hay Bale Pale Ale - Fresh Hop", "fresh-hop", None]]

    def test_stickmen_only_beers_marked_on_tap_in_tualatin(self) -> None:
        html = """
        <div id="isotope-list">
          <div class="item archive"><div class="post_content">
            <div class="post_options"></div>
            <div class="post_content-text"><p>FRESH HOP IPA</p>
              <a><h2>Last Year's Fresh Hop</h2></a></div></div></div>
          <div class="item hop-forward"><div class="post_content">
            <div class="post_options"><div class="image on_tap_tualatin"></div>
              <div class="image on_tap_lake_oswego"></div></div>
            <div class="post_content-text"><p>FRESH HOP JUICY PALE ALE</p>
              <a><h2>Luminosa Livin’</h2></a></div></div></div>
          <div class="item dark"><div class="post_content">
            <div class="post_options"><div class="image on_tap_lake_oswego"></div></div>
            <div class="post_content-text"><p>PUMPKIN BARLEYWINE</p>
              <a><h2>Elsewhere Only</h2></a></div></div></div>
        </div>
        """
        venue = VENUES["stickmen-tualatin-taps"]
        entries = parse_html_taplist(html, venue.parser_config or {})

        assert [(e.name, e.style) for e in entries] == [
            ("Luminosa Livin’", "FRESH HOP JUICY PALE ALE")
        ]
