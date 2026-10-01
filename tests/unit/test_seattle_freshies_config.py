"""Guards for the seattle-freshies site config."""

import html
import re
import struct
from pathlib import Path
from xml.etree import ElementTree

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import SiteConfig
from around_the_grounds.parsers.registry import ParserRegistry

TEMPLATES = Path(__file__).resolve().parents[2] / "public_templates"


@pytest.fixture(scope="module")
def site() -> SiteConfig:
    return load_site_config("seattle-freshies")


def test_site_basics(site: SiteConfig) -> None:
    assert site.name == "Seattle Freshies"
    assert site.public_url == "https://seattlefreshies.com"
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


def test_event_sources_filter_for_fresh_hop_and_look_ahead(site: SiteConfig) -> None:
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
    for venue in event_sources:
        config = venue.parser_config or {}
        assert config.get("event_filter") is True, venue.key
        assert config.get("event_window_days", 0) > 7, venue.key


def test_bottle_shops_and_taprooms_are_typed(site: SiteConfig) -> None:
    taprooms = {v.key for v in site.venues if (v.parser_config or {}).get("venue_type")}
    assert taprooms == {
        "beer-junction-taps",
        "beer-star-taps",
        "beveridge-place-taps",
        "broadview-taps",
        "chucks-central-district-taps",
        "chucks-greenwood-taps",
        "chucks-seward-park-taps",
        "die-bierstube-taps",
        "growler-guys-taps",
        "latona-pub-taps",
        "pine-box-taps",
        "prost-phinney-taps",
        "prost-west-seattle-taps",
        "watershed-taps",
    }
    assert {(v.parser_config or {}).get("venue_type") for v in site.venues} == {
        "taproom",
        None,
    }


def test_template_has_every_page() -> None:
    for page in (
        "index.html",
        "festbier.html",
        "pumpkin.html",
        "taprooms.html",
        "events.html",
        "app.js",
        "styles.css",
    ):
        assert (TEMPLATES / "fresh-hop" / page).is_file(), page
    for page, data_page in (
        ("index.html", "freshhop"),
        ("festbier.html", "festbier"),
        ("pumpkin.html", "pumpkin"),
        ("taprooms.html", "taprooms"),
        ("events.html", "events"),
    ):
        html = (TEMPLATES / "fresh-hop" / page).read_text()
        assert f'data-page="{data_page}"' in html
        # Source link goes to Hal's fork; the original project is credited by name.
        assert '<a href="https://github.com/halmueller/around-the-grounds">' in html
        assert (
            '<a href="https://github.com/steveandroulakis/around-the-grounds">'
            "Around the Grounds</a>"
        ) in html
        # Author credit in the pinned bottom bar; every page links every tab.
        assert html.count('<a href="https://halmueller.com">Hal Mueller</a>') == 1
        assert html.count('href="https://www.linkedin.com/in/halmueller/"') == 2
        # Byline sits between the site title and the tabs.
        assert re.search(
            r'</h1>\s*<p class="byline">By Ballard resident <a href="https://www.'
            r'linkedin.com/in/halmueller/">Hal Mueller</a> with the help of '
            r'<a href="https://claude.ai">Claude Code</a></p>\s*<nav class="tabs"',
            html,
        ), page
        assert "Seattle Freshies" in html
        hrefs = re.findall(r'<nav class="tabs".*?</nav>', html, re.S)[0]
        assert re.findall(r'href="([^"]+)"', hrefs) == [
            "./",
            "festbier.html",
            "pumpkin.html",
            "taprooms.html",
            "events.html",
        ], page


def test_sitemap_lists_every_page(site: SiteConfig) -> None:
    root = ElementTree.parse(TEMPLATES / "fresh-hop" / "sitemap.xml").getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text or "" for el in root.findall("sm:url/sm:loc", ns)]
    pages = sorted(p.name for p in (TEMPLATES / "fresh-hop").glob("*.html"))
    expected = [
        f"{site.public_url}/" + ("" if page == "index.html" else page) for page in pages
    ]
    assert sorted(locs) == sorted(expected)


def test_robots_points_at_sitemap(site: SiteConfig) -> None:
    robots = (TEMPLATES / "fresh-hop" / "robots.txt").read_text()
    assert f"Sitemap: {site.public_url}/sitemap.xml" in robots.splitlines()
    assert "Disallow: /" not in robots.splitlines()


@pytest.mark.parametrize(
    "page, path",
    [
        ("index.html", ""),
        ("festbier.html", "festbier.html"),
        ("pumpkin.html", "pumpkin.html"),
        ("taprooms.html", "taprooms.html"),
        ("events.html", "events.html"),
    ],
)
def test_open_graph_tags(site: SiteConfig, page: str, path: str) -> None:
    head = (TEMPLATES / "fresh-hop" / page).read_text().split("</head>")[0]
    meta = dict(re.findall(r'<meta property="(og:[\w:]+)" content="([^"]*)">', head))
    url = f"{site.public_url}/{path}"
    assert meta["og:url"] == url
    assert f'<link rel="canonical" href="{url}">' in head
    title = re.search(r"<title>(.*?)</title>", head)
    assert title and html.unescape(meta["og:title"]) == html.unescape(title.group(1))
    description = re.search(r'<meta name="description" content="([^"]*)">', head)
    assert description and meta["og:description"] == description.group(1)
    # Crawlers need an absolute image URL for a file the template ships.
    assert meta["og:image"] == f"{site.public_url}/og-image.png"
    assert (meta["og:image:width"], meta["og:image:height"]) == ("1200", "630")
    assert '<meta name="twitter:card" content="summary_large_image">' in head


def test_open_graph_image_is_1200_by_630_png() -> None:
    data = (TEMPLATES / "fresh-hop" / "og-image.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (1200, 630)


ICON_LINKS = (
    '<link rel="icon" href="favicon.svg" type="image/svg+xml">',
    '<link rel="icon" href="favicon-32.png" type="image/png" sizes="32x32">',
    '<link rel="apple-touch-icon" href="apple-touch-icon.png">',
)


@pytest.mark.parametrize(
    "page",
    ["index.html", "festbier.html", "pumpkin.html", "taprooms.html", "events.html"],
)
def test_pages_link_the_favicon_files(page: str) -> None:
    head = (TEMPLATES / "fresh-hop" / page).read_text().split("</head>")[0]
    for link in ICON_LINKS:
        assert link in head
    assert "data:image/svg+xml" not in head  # no leftover inline emoji icon


def _png_size(path: Path) -> tuple:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def test_favicon_files() -> None:
    folder = TEMPLATES / "fresh-hop"
    ElementTree.parse(folder / "favicon.svg")  # well-formed
    assert _png_size(folder / "favicon-32.png") == (32, 32)
    assert _png_size(folder / "apple-touch-icon.png") == (180, 180)
    # ICONDIR header: reserved 0, type 1 (icon), then one 16-byte entry per
    # size whose first two bytes are width and height.
    ico = (folder / "favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind) == (0, 1)
    sizes = {(ico[6 + 16 * i], ico[7 + 16 * i]) for i in range(count)}
    assert sizes == {(16, 16), (32, 32), (48, 48)}
