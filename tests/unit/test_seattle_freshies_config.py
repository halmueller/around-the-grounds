"""Guards for the seattle-freshies site config."""

import html
import re
import struct
import unicodedata
from pathlib import Path
from xml.etree import ElementTree

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.main import _write_site_output
from around_the_grounds.models import SiteConfig
from around_the_grounds.parsers.registry import ParserRegistry

TEMPLATES = Path(__file__).resolve().parents[2] / "public_templates"
DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "digitalocean"
HOME = "index.html"


@pytest.fixture(scope="module")
def site() -> SiteConfig:
    return load_site_config("seattle-freshies")


@pytest.fixture(scope="module")
def rendered(site: SiteConfig, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The template as published for this site, placeholders filled."""
    out = tmp_path_factory.mktemp("rendered")
    web_data = {
        "events": [],
        "site_key": site.key,
        "site_name": site.name,
        "public_url": site.public_url,
        "template_vars": site.template_vars,
    }
    _write_site_output(out, TEMPLATES / site.template, web_data)
    return out


def test_site_basics(site: SiteConfig) -> None:
    assert site.name == "Seattle Freshies"
    assert site.public_url == "https://seattlefreshies.com"
    assert site.generate_description is False  # the haiku prompt is Ballard's
    assert (TEMPLATES / site.template / "index.html").is_file()


def test_venue_keys_are_unique(site: SiteConfig) -> None:
    keys = [v.key for v in site.venues]
    assert len(keys) == len(set(keys))


def test_tap_list_venues_are_alphabetical_ignoring_articles(site: SiteConfig) -> None:
    # Pages show venues in config order. "The", the German "Die", and the
    # Spanish "El" are skipped, so The Pine Box sorts under P, Die Bierstube
    # under B, and El Sueñito under S.
    def sort_key(name: str) -> str:
        plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        return re.sub(r"^(?:the|die|el)\s+", "", plain.casefold())

    names = [
        v.name
        for v in site.venues
        if v.source_type not in ("html", "squarespace-events")
    ]
    assert names == sorted(names, key=sort_key)


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


def test_event_sources_filter_for_beer_events_and_look_ahead(
    site: SiteConfig,
) -> None:
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
        # Everything announced so far shows up, however far out.
        assert config.get("event_window_days", 0) >= 365, venue.key


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
    assert {(v.parser_config or {}).get("venue_type") for v in site.venues} == {
        "taproom",
        None,
    }


def test_template_has_every_page(site: SiteConfig, rendered: Path) -> None:
    for page in (
        "index.html",
        "fresh-hops.html",
        "festbier.html",
        "pumpkin.html",
        "taprooms.html",
        "events.html",
        "app.js",
        "styles.css",
    ):
        assert (rendered / page).is_file(), page
    for page, data_page in (
        ("fresh-hops.html", "freshhop"),
        ("festbier.html", "festbier"),
        ("pumpkin.html", "pumpkin"),
        ("taprooms.html", "taprooms"),
        ("events.html", "events"),
    ):
        html = (rendered / page).read_text()
        assert "{{" not in html
        assert f'data-page="{data_page}"' in html
        # Source link goes to Hal's fork; the original project is credited by name.
        assert '<a href="https://github.com/halmueller/around-the-grounds">' in html
        assert (
            '<a href="https://github.com/steveandroulakis/around-the-grounds">'
            "Around the Grounds</a>"
        ) in html
        # The pinned bottom bar credits the author by name; LinkedIn and
        # Claude Code are linked from the byline only.
        assert (
            'Built by <a href="https://halmueller.com">Hal Mueller</a> on '
            '<a href="https://github.com/steveandroulakis/around-the-grounds">'
        ) in html
        assert html.count('href="https://halmueller.com"') == 1
        assert html.count('href="https://www.linkedin.com/in/halmueller/"') == 1
        assert html.count('href="https://claude.ai"') == 1
        # Byline sits between the site title and the tabs.
        assert re.search(
            r'</h1>\s*<p class="byline">By Ballard resident <a href="https://www.'
            r'linkedin.com/in/halmueller/">Hal Mueller</a> with the help of '
            r'<a href="https://claude.ai">Claude Code</a></p>\s*'
            r'<p class="byline">For food trucks at Ballard breweries, see '
            r'<a href="https://www.ballardfoodtrucks.com">ballardfoodtrucks.com</a>'
            r'</p>\s*<nav class="tabs"',
            html,
        ), page
        assert f"</span> {site.name}</h1>" in html
        hrefs = re.findall(r'<nav class="tabs".*?</nav>', html, re.S)[0]
        assert re.findall(r'href="([^"]+)"', hrefs) == [
            "fresh-hops.html",
            "festbier.html",
            "pumpkin.html",
            "taprooms.html",
            "events.html",
        ], page


def test_sitemap_lists_every_page(site: SiteConfig, rendered: Path) -> None:
    root = ElementTree.parse(rendered / "sitemap.xml").getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text or "" for el in root.findall("sm:url/sm:loc", ns)]
    # index.html is not a page of its own: / redirects to the in-season list.
    pages = sorted(
        p.name for p in (TEMPLATES / "fresh-hop").glob("*.html") if p.name != HOME
    )
    assert sorted(locs) == [f"{site.public_url}/{page}" for page in pages]


def test_home_redirects_to_the_in_season_page(site: SiteConfig, rendered: Path) -> None:
    # Apache answers / with a temporary redirect so each seasonal list keeps
    # its own URL; index.html is the same redirect for hosts without that rule.
    conf = (DEPLOY / "freshies-site.conf").read_text()
    rule = re.search(
        r'^\s*RedirectMatch 302 "\^/\(index\\\.html\)\?\$" "/(.+)"$', conf, re.M
    )
    assert rule, "home page redirect missing or not a 302"
    target = rule.group(1)
    assert target != HOME and (TEMPLATES / "fresh-hop" / target).is_file()
    head = (rendered / HOME).read_text().split("</head>")[0]
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in head
    assert f'<link rel="canonical" href="{site.public_url}/{target}">' in head


def test_robots_points_at_sitemap(site: SiteConfig, rendered: Path) -> None:
    robots = (rendered / "robots.txt").read_text()
    assert f"Sitemap: {site.public_url}/sitemap.xml" in robots.splitlines()
    assert "Disallow: /" not in robots.splitlines()


@pytest.mark.parametrize(
    "page, path",
    [
        ("fresh-hops.html", "fresh-hops.html"),
        ("festbier.html", "festbier.html"),
        ("pumpkin.html", "pumpkin.html"),
        ("taprooms.html", "taprooms.html"),
        ("events.html", "events.html"),
    ],
)
def test_open_graph_tags(
    site: SiteConfig, rendered: Path, page: str, path: str
) -> None:
    head = (rendered / page).read_text().split("</head>")[0]
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


def test_open_graph_image_is_1200_by_630_png(rendered: Path) -> None:
    # The card names the site, so it comes from the site's overlay directory
    # (public_templates/_overlays/<site key>/), not the shared template.
    assert not (TEMPLATES / "fresh-hop" / "og-image.png").exists()
    data = (rendered / "og-image.png").read_bytes()
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
    [
        "fresh-hops.html",
        "festbier.html",
        "pumpkin.html",
        "taprooms.html",
        "events.html",
    ],
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
