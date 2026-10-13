"""Guards for the portland-freshies site config.

What every Freshies site must satisfy is in test_freshies_sites.py, which
runs for this site too. This file holds what is true of Portland only.
"""

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import SiteConfig


@pytest.fixture(scope="module")
def site() -> SiteConfig:
    return load_site_config("portland-freshies")


def test_site_basics(site: SiteConfig) -> None:
    assert site.name == "Portland Freshies"
    assert site.public_url == "https://portlandfreshies.com"
    assert site.template == "fresh-hop"
    # The author lives in Seattle; the Ballard food-truck line is Seattle's.
    assert site.template_vars == {"place": "Portland", "author_home": "Seattle"}


def test_covers_the_metro_area_on_both_sides_of_the_river(site: SiteConfig) -> None:
    names = " ".join(v.name for v in site.venues)
    for area in ("Vancouver", "Beaverton", "Hillsboro", "Gresham"):
        assert f"({area})" in names, area


def test_deschutes_is_the_portland_pub_not_bend(site: SiteConfig) -> None:
    deschutes = [v for v in site.venues if "deschutes" in v.key]
    assert [v.parser_config["location_id"] for v in deschutes] == [32868]


def test_dead_untappd_embeds_stay_out(site: SiteConfig) -> None:
    # The Civic Taproom's and Raindrop Taphouse's pages still carry an Untappd
    # embed, but Untappd answers 404 for both (checked 2026-10-12).
    ids = {(v.parser_config or {}).get("location_id") for v in site.venues}
    assert not ids & {33211, 28431}
