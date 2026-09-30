"""Guards for the seattle-fall-beers site config."""

from pathlib import Path

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import SiteConfig
from around_the_grounds.parsers.registry import ParserRegistry

TEMPLATES = Path(__file__).resolve().parents[2] / "public_templates"


@pytest.fixture(scope="module")
def site() -> SiteConfig:
    return load_site_config("seattle-fall-beers")


def test_site_basics(site: SiteConfig) -> None:
    assert site.name == "Seattle Fall Beers"
    assert site.public_url == "https://seattlefallbeers.com"
    assert site.generate_description is False  # the haiku prompt is Ballard's
    assert (TEMPLATES / site.template / "index.html").is_file()


def test_venue_keys_are_unique(site: SiteConfig) -> None:
    keys = [v.key for v in site.venues]
    assert len(keys) == len(set(keys))


def test_venues_use_generic_listing_parsers(site: SiteConfig) -> None:
    # The registry matches venue.key before source_type, so reusing a key
    # like "stoup-ballard" would silently route to the food-truck parser.
    for venue in site.venues:
        assert venue.key not in ParserRegistry._specific, venue.key
        assert venue.source_type in ParserRegistry._generic, venue.key
        ParserRegistry.get_parser(venue)


def test_bale_breaker_is_the_seattle_taproom_not_yakima(site: SiteConfig) -> None:
    bale_breaker = [v for v in site.venues if "bale-breaker" in v.key]
    assert [v.parser_config["location_id"] for v in bale_breaker] == [36760]
