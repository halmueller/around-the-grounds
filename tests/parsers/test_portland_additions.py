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
        html = "<h3>Big Beer</h3><p>Fresh hop pale ale, 5.5%</p><h3>Other</h3>"
        config = {
            "line_pattern": r"^(?P<name>.+)$",
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
