"""Guards for the seattle-freshies site config.

What every Freshies site must satisfy (page layout, sitemap, Open Graph
tags, venue order, and so on) is in test_freshies_sites.py, which runs for
this site too. This file holds what is true of Seattle only.
"""

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import SiteConfig


@pytest.fixture(scope="module")
def site() -> SiteConfig:
    return load_site_config("seattle-freshies")


def test_site_basics(site: SiteConfig) -> None:
    assert site.name == "Seattle Freshies"
    assert site.public_url == "https://seattlefreshies.com"
    assert site.template == "fresh-hop"
    # The author lives in Ballard, and only this site links the Ballard
    # food-truck site from its header.
    assert site.template_vars == {
        "place": "Seattle",
        "author_home": "Ballard",
        "ballard_food_trucks": "yes",
    }


def test_bale_breaker_is_the_seattle_taproom_not_yakima(site: SiteConfig) -> None:
    bale_breaker = [v for v in site.venues if "bale-breaker" in v.key]
    assert [v.parser_config["location_id"] for v in bale_breaker] == [36760]


def test_event_sources(site: SiteConfig) -> None:
    event_sources = [
        v for v in site.venues if v.source_type in ("html", "squarespace-events")
    ]
    assert {v.key for v in event_sources} == {
        "fremont-events",
        "fremont-columbia-city-events",
        "georgetown-event-list",
        "beveridge-place-events",
        "stoup-ballard-events",
        "stoup-capitol-hill-events",
    }


def test_bottle_shops_and_taprooms_are_typed(site: SiteConfig) -> None:
    taprooms = {v.key for v in site.venues if (v.parser_config or {}).get("venue_type")}
    assert taprooms == {
        "beer-authority-taps",
        "beer-junction-taps",
        "beer-star-taps",
        "beveridge-place-taps",
        "broadview-taps",
        "chucks-central-district-taps",
        "chucks-greenwood-taps",
        "chucks-seward-park-taps",
        "crown-taps",
        "die-bierstube-taps",
        "edway-taps",
        "growler-guys-taps",
        "latona-pub-taps",
        "maize-and-barley-taps",
        "pine-box-taps",
        "prost-phinney-taps",
        "prost-west-seattle-taps",
        "ridgecrest-taps",
        "teku-taps",
        "trailbend-taps",
        "uber-tavern-taps",
        "watershed-taps",
    }
