"""Parser features added for the Yakima Freshies site."""

import logging

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.html_taplist import parse_html_taplist
from around_the_grounds.parsers.generic.listing_common import (
    TapEntry,
    build_listings,
    strip_tap_number,
)

# Single Hill's Yakima taproom menu: a name row, then a description row.
TABLE = """
<table class="ontap">
  <tr><th colspan="3"><h4>Fresh Hop</h4></th></tr>
  <tr class="beer-name"><td>Five Sisters</td><td>5.2% ABV</td><td>40 IBU</td></tr>
  <tr class="beer-description"><td colspan="3"><strong>Fresh Hop IPA</strong>
    – A collaboration with fresh, wet Mosaic.</td></tr>
  <tr><th colspan="3"><h4>Lite</h4></th></tr>
  <tr class="beer-name"><td>Adams</td><td>4.6% ABV</td><td>15 IBU</td></tr>
  <tr class="beer-name"><td>Sightglass</td><td>6% ABV</td><td>35 IBU</td></tr>
  <tr class="beer-description"><td colspan="3"><strong>Hazy IPA</strong>
    – Citra and Strata.</td></tr>
</table>
"""
CONFIG = {
    "item": "table.ontap tr.beer-name",
    "name": "td:first-child",
    "abv": "td:nth-child(2)",
    "style": "strong",
    "detail_sibling": "tr.beer-description",
}


class TestDetailSibling:
    def test_description_row_supplies_style_and_match_text(self) -> None:
        first = parse_html_taplist(TABLE, CONFIG)[0]
        assert (first.name, first.style, first.abv) == (
            "Five Sisters",
            "Fresh Hop IPA",
            "5.2%",
        )
        assert first.match_text is not None
        assert "fresh, wet Mosaic" in first.match_text

    def test_an_item_followed_by_another_item_has_no_detail(self) -> None:
        adams = parse_html_taplist(TABLE, CONFIG)[1]
        assert (adams.name, adams.style, adams.match_text) == ("Adams", None, None)

    def test_details_do_not_leak_to_the_previous_item(self) -> None:
        names = {e.name: e.style for e in parse_html_taplist(TABLE, CONFIG)}
        assert names == {
            "Five Sisters": "Fresh Hop IPA",
            "Adams": None,
            "Sightglass": "Hazy IPA",
        }

    def test_without_the_option_the_next_row_is_ignored(self) -> None:
        config = {k: v for k, v in CONFIG.items() if k != "detail_sibling"}
        first = parse_html_taplist(TABLE, config)[0]
        assert (first.style, first.match_text) == (None, None)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("11. Volcano Envy", "Volcano Envy"),
        ("2. 🌿Fresh Hop Cumulus (Citra)", "Fresh Hop Cumulus (Citra)"),
        ("Volcano Envy", "Volcano Envy"),
        ("10 Barrel Apocalypse", "10 Barrel Apocalypse"),
        ("1.5 Hop Pale", "1.5 Hop Pale"),
        ("7.", "7."),
        ("🌿 Fresh Hop", "🌿 Fresh Hop"),
    ],
)
def test_strip_tap_number(name: str, expected: str) -> None:
    assert strip_tap_number(name) == expected


def test_listing_titles_drop_the_tap_number() -> None:
    venue = Venue(
        key="numbered-taps",
        name="Numbered",
        url="https://example.com",
        source_type="untappd-embed",
    )
    entries = [TapEntry(name="11. Volcano Envy", style="Fresh Hop IPA")]
    events = build_listings(venue, entries, "test", logging.getLogger(__name__))
    assert [e.title for e in events] == ["Volcano Envy"]


VENUES = {v.key: v for v in load_site_config("yakima-freshies").venues}


def test_mule_and_elk_skips_beers_marked_out() -> None:
    html = """
    <div class="relative rounded-2xl border p-6">
      <div class="absolute top-4 right-4 flex gap-2">
        <span class="rounded-full bg-amber-500/15">Seasonal</span>
        <span class="rounded-full bg-muted text-muted-foreground">Out</span>
      </div>
      <span class="inline-block rounded-full">Fresh Hop IPA</span>
      <h3>Cask Riel IPA</h3><p><span>4.9%</span> ABV</p>
    </div>
    <div class="relative rounded-2xl border p-6">
      <div class="absolute top-4 right-4 flex gap-2">
        <span class="rounded-full bg-amber-500/15">Seasonal</span>
      </div>
      <span class="inline-block rounded-full">Stout</span>
      <h3>Shed Hunter Stout</h3><p><span>4.06%</span> ABV</p>
    </div>
    <div class="rounded-2xl border p-5">
      <div class="flex items-center justify-between mb-2">
        <span class="rounded-full bg-secondary/10">Non-Alcoholic</span>
        <span class="rounded-full bg-muted text-muted-foreground">Out</span>
      </div>
      <h3>N/A Strawberry Pear Seltzer</h3>
    </div>
    """
    venue = VENUES["mule-and-elk-taps"]
    entries = parse_html_taplist(html, venue.parser_config or {})
    assert [(e.name, e.style, e.abv) for e in entries] == [
        ("Shed Hunter Stout", "Stout", "4.06%")
    ]


def test_atomic_ale_menu_items_and_abv_without_percent() -> None:
    html = """
    <div data-aid="MENU_ITEM_CONTAINER_1">
      <div data-aid="MENU_ITEM_BURKSBLOND">
        <h4 data-aid="MENU_SECTION1_ITEM0_TITLE">Burks Blonde</h4>
        <div data-aid="MENU_SECTION1_ITEM0_DESC"><p>4.8 abv  20 ibu</p></div>
      </div>
      <div data-aid="MENU_ITEM_FRESHHOPPA">
        <h4 data-aid="MENU_SECTION1_ITEM1_TITLE">Fresh Hop Pale</h4>
        <div data-aid="MENU_SECTION1_ITEM1_DESC"><p>5.5 abv  40 ibu</p></div>
      </div>
    </div>
    """
    venue = VENUES["atomic-ale-taps"]
    entries = parse_html_taplist(html, venue.parser_config or {})
    events = build_listings(venue, entries, "html", logging.getLogger(__name__))

    assert [(e.name, e.abv) for e in entries] == [
        ("Burks Blonde", "4.8%"),
        ("Fresh Hop Pale", "5.5%"),
    ]
    assert [[e.title, e.category] for e in events] == [["Fresh Hop Pale", "fresh-hop"]]
