"""Guards for the yakima-freshies site config.

What every Freshies site must satisfy is in test_freshies_sites.py, which
runs for this site too. This file holds what is true of Yakima only.
"""

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import SiteConfig
from around_the_grounds.parsers.registry import ParserRegistry


@pytest.fixture(scope="module")
def site() -> SiteConfig:
    return load_site_config("yakima-freshies")


def test_site_basics(site: SiteConfig) -> None:
    assert site.name == "Yakima Freshies"
    assert site.public_url == "https://yakimafreshies.com"
    assert site.template == "fresh-hop"
    # The site reaches from Leavenworth and Wenatchee through the Yakima
    # Valley to the Tri-Cities, so its copy says "Central Washington" (Hal
    # confirmed the name and wording, 2026-10-13). The author lives in Seattle.
    assert site.template_vars == {
        "place": "Central Washington",
        "author_home": "Seattle",
        "sister_sites_yakima": "yes",
    }


def test_covers_the_valley_the_tri_cities_and_wenatchee(site: SiteConfig) -> None:
    names = " ".join(v.name for v in site.venues)
    for area in (
        "Yakima",
        "Moxee",
        "Sunnyside",
        "Kennewick",
        "Richland",
        "Pasco",
        "Leavenworth",
        "Wenatchee",
    ):
        assert f"({area})" in names, area


def test_dru_bru_is_left_out(site: SiteConfig) -> None:
    # Hal, 2026-10-13: skip it; its site has a catalogue and no tap list.
    assert not [v.key for v in site.venues if "dru-bru" in v.key]


def test_hellbent_at_pybus_market_is_not_the_seattle_list(site: SiteConfig) -> None:
    # Hellbent's site shows one tap list, for its Lake City taproom (Untappd
    # location 126); it must not stand in for the Wenatchee taproom.
    ids = {(v.parser_config or {}).get("location_id") for v in site.venues}
    assert 126 not in ids


def test_bale_breaker_is_read_as_a_tap_list(site: SiteConfig) -> None:
    # Ballard's food-truck parser is registered under its own venue key, and
    # the registry looks up keys before source types.
    bale_breaker = [v for v in site.venues if "bale-breaker" in v.key]
    assert [v.key for v in bale_breaker] == ["bale-breaker-yakima-taps"]
    parser = ParserRegistry.get_parser(bale_breaker[0])
    assert parser.PRODUCES_LISTINGS
    # The Moxee taproom's Untappd menu, not the Ballard taproom's (36760).
    assert bale_breaker[0].parser_config["location_id"] == 36383


def test_single_hill_is_the_yakima_taproom(site: SiteConfig) -> None:
    single_hill = [v for v in site.venues if "single-hill" in v.key]
    assert [v.url for v in single_hill] == ["https://singlehillbrewing.com/menu/"]


def test_static_beer_menus_stay_out(site: SiteConfig) -> None:
    # Outskirts' drink menu lists its flagships, not what is pouring (its own
    # fresh hop was on at the Public House and not on that menu, 2026-10-13),
    # and one flagship's description names a fresh-hop festival award.
    keys = " ".join(v.key for v in site.venues)
    for name in ("outskirts", "bombing-range", "atomic-ale"):
        assert name not in keys, name


def test_valley_brewing_is_left_out(site: SiteConfig) -> None:
    # Hal, 2026-10-13: its Taplist.io menu is behind Cloudflare, which refuses
    # the droplet (403), and Cloudflare blocks are not worked around.
    assert not [v.key for v in site.venues if "valley-brewing" in v.key]
