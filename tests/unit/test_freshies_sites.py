"""Guards every site on the fresh-hop template must pass (the Freshies sites).

Each test runs once per site. Checks of the pages read the site as published
(placeholders filled, overlay copied), not the raw template. Assertions about
one site's own venues live in that site's test file.
"""

import html
import json
import re
import shutil
import struct
import subprocess
import unicodedata
from pathlib import Path
from xml.etree import ElementTree

import pytest

from around_the_grounds.config.loader import load_all_sites
from around_the_grounds.main import _site_template_vars, _write_site_output
from around_the_grounds.models import SiteConfig, Venue
from around_the_grounds.parsers.registry import ParserRegistry

TEMPLATES = Path(__file__).resolve().parents[2] / "public_templates"
DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "digitalocean"
RENDER = (
    Path(__file__).resolve().parents[2] / "tests" / "browser" / "render_fresh_hop.mjs"
)
HOME = "index.html"
PAGES = (
    ("fresh-hops.html", "freshhop"),
    ("festbier.html", "festbier"),
    ("pumpkin.html", "pumpkin"),
    ("taprooms.html", "taprooms"),
    ("events.html", "events"),
)
SITES = [site for site in load_all_sites() if site.template == "fresh-hop"]


@pytest.fixture(scope="module", params=SITES, ids=lambda site: site.key)
def site(request: pytest.FixtureRequest) -> SiteConfig:
    return request.param


@pytest.fixture(scope="module")
def rendered(site: SiteConfig, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The template as published for this site, placeholders filled."""
    out = tmp_path_factory.mktemp("rendered")
    web_data = {
        "events": [],
        "site_key": site.key,
        "site_name": site.name,
        "public_url": site.public_url,
        "template_vars": _site_template_vars(site),
    }
    _write_site_output(out, TEMPLATES / site.template, web_data)
    return out


def _has_events(site: SiteConfig) -> bool:
    """Whether the site has an event source, and so an Events tab and page."""
    return any(not _is_tap_list(venue) for venue in site.venues)


def _pages(site: SiteConfig) -> list:
    return [name for name, _ in PAGES if name != "events.html" or _has_events(site)]


def _is_tap_list(venue: Venue) -> bool:
    parser = ParserRegistry.get_parser(venue)
    return bool(getattr(parser, "PRODUCES_LISTINGS", False))


def test_there_is_at_least_one_site() -> None:
    assert "seattle-freshies" in {site.key for site in SITES}


def test_site_basics(site: SiteConfig) -> None:
    assert site.name.endswith(" Freshies")
    assert re.fullmatch(r"https://[a-z0-9.-]+", site.public_url), site.public_url
    assert site.timezone == "America/Los_Angeles"
    assert site.generate_description is False  # the haiku prompt is Ballard's
    # Published from cron with --output-dir; --deploy must skip it.
    assert site.target_repo == ""
    assert site.template_vars.get("place")
    assert site.template_vars.get("area")
    assert site.template_vars.get("author_home")
    assert (TEMPLATES / site.template / HOME).is_file()


def test_public_urls_are_distinct() -> None:
    urls = [site.public_url for site in SITES]
    assert len(urls) == len(set(urls))


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

    names = [v.name for v in site.venues if _is_tap_list(v)]
    assert names == sorted(names, key=sort_key)


def test_venues_use_generic_listing_parsers(site: SiteConfig) -> None:
    # The registry matches venue.key before source_type, so reusing a key
    # like "stoup-ballard" would silently route to the food-truck parser.
    for venue in site.venues:
        assert venue.key not in ParserRegistry._specific, venue.key
        assert venue.source_type in ParserRegistry._generic, venue.key
        ParserRegistry.get_parser(venue)


def test_event_sources_filter_for_beer_events_and_look_ahead(
    site: SiteConfig,
) -> None:
    for venue in site.venues:
        if _is_tap_list(venue):
            continue
        config = venue.parser_config or {}
        assert config.get("event_filter") is True, venue.key
        # Everything announced so far shows up, however far out.
        assert config.get("event_window_days", 0) >= 365, venue.key


def test_venue_types_are_taproom_or_unset(site: SiteConfig) -> None:
    types = {(v.parser_config or {}).get("venue_type") for v in site.venues}
    assert types <= {"taproom", None}


@pytest.mark.parametrize("page, data_page", PAGES)
def test_page_layout(
    site: SiteConfig, rendered: Path, page: str, data_page: str
) -> None:
    if page not in _pages(site):
        # A site with no event sources has no Events page.
        assert not (rendered / page).exists()
        return
    html = (rendered / page).read_text()
    assert "{{" not in html
    assert f'data-page="{data_page}"' in html
    assert f"</span> {site.name}</h1>" in html
    # Source link goes to Hal's fork; the original project is credited by name.
    assert '<a href="https://github.com/halmueller/around-the-grounds">' in html
    # The pinned bottom bar credits the author by name; LinkedIn and
    # Claude Code are linked from the byline only.
    assert (
        'Built by <a href="https://halmueller.com">Hal Mueller</a> on '
        '<a href="https://github.com/steveandroulakis/around-the-grounds">'
        "Around the Grounds</a>"
    ) in html
    assert html.count('href="https://halmueller.com"') == 1
    assert html.count('href="https://www.linkedin.com/in/halmueller/"') == 1
    assert html.count('href="https://claude.ai"') == 1
    # Byline sits between the site title and the tabs, and says where the
    # author lives relative to this site. Only Seattle points to the Ballard
    # food-truck site.
    food_trucks = (
        r'<p class="byline">For food trucks at Ballard breweries, see '
        r'<a href="https://www.ballardfoodtrucks.com">ballardfoodtrucks.com</a>'
        r"\.</p>\s*"
    )
    if not site.template_vars.get("ballard_food_trucks"):
        assert "ballardfoodtrucks" not in html
        food_trucks = ""
    # Then one line linking the other Freshies sites.
    sister_sites = r'<p class="byline">For [^<]*, see <a [^\n]*</a>\.</p>\s*'
    assert re.search(
        r'</h1>\s*<p class="byline">By '
        + re.escape(site.template_vars["author_home"])
        + r' resident <a href="https://www.linkedin.com/in/halmueller/">'
        r'Hal Mueller</a> with the help of <a href="https://claude.ai">'
        r"Claude Code</a></p>\s*" + food_trucks + sister_sites + r'<nav class="tabs"',
        html,
    ), page
    tabs = re.findall(r'<nav class="tabs".*?</nav>', html, re.S)[0]
    assert re.findall(r'href="([^"]+)"', tabs) == _pages(site), page


@pytest.mark.parametrize("page", [name for name, _ in PAGES])
def test_header_links_every_other_freshies_site(
    site: SiteConfig, rendered: Path, page: str
) -> None:
    if page not in _pages(site):
        return
    html = (rendered / page).read_text()
    header = html[html.index("</h1>") : html.index('<nav class="tabs"')]
    lines = [line for line in header.splitlines() if "freshies.com" in line]
    assert len(lines) == 1, page
    # The other sites, in alphabetical order, named by place in the same order.
    others = [s for s in SITES if s.key != site.key]
    assert re.findall(r'<a href="([^"]+)">([^<]+)</a>', lines[0]) == [
        (s.public_url, s.public_url.split("://", 1)[1]) for s in others
    ], page
    places = " and ".join(s.template_vars["place"] for s in others)
    assert lines[0].strip().startswith(f'<p class="byline">For {places}, see '), page


def test_template_ships_the_shared_files(rendered: Path) -> None:
    for name in (HOME, "app.js", "analytics.js", "styles.css"):
        assert (rendered / name).is_file(), name


def test_sitemap_lists_every_page(site: SiteConfig, rendered: Path) -> None:
    root = ElementTree.parse(rendered / "sitemap.xml").getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text or "" for el in root.findall("sm:url/sm:loc", ns)]
    # index.html is not a page of its own: / redirects to the in-season list.
    pages = sorted(p.name for p in rendered.glob("*.html") if p.name != HOME)
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
    assert target != HOME and (rendered / target).is_file()
    head = (rendered / HOME).read_text().split("</head>")[0]
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in head
    assert f'<link rel="canonical" href="{site.public_url}/{target}">' in head


def test_robots_points_at_sitemap(site: SiteConfig, rendered: Path) -> None:
    robots = (rendered / "robots.txt").read_text()
    assert f"Sitemap: {site.public_url}/sitemap.xml" in robots.splitlines()
    assert "Disallow: /" not in robots.splitlines()


@pytest.mark.parametrize("page", [name for name, _ in PAGES])
def test_open_graph_tags(site: SiteConfig, rendered: Path, page: str) -> None:
    if page not in _pages(site):
        # A site with no event sources has no Events page.
        assert not (rendered / page).exists()
        return
    head = (rendered / page).read_text().split("</head>")[0]
    meta = dict(re.findall(r'<meta property="(og:[\w:]+)" content="([^"]*)">', head))
    url = f"{site.public_url}/{page}"
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


@pytest.mark.parametrize("page", [name for name, _ in PAGES])
def test_pages_link_the_favicon_files(
    site: SiteConfig, rendered: Path, page: str
) -> None:
    if page not in _pages(site):
        # A site with no event sources has no Events page.
        assert not (rendered / page).exists()
        return
    head = (rendered / page).read_text().split("</head>")[0]
    for link in ICON_LINKS:
        assert link in head
    assert "data:image/svg+xml" not in head  # no leftover inline emoji icon


def _png_size(path: Path) -> tuple:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def test_favicon_files(rendered: Path) -> None:
    folder = rendered
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node not available")
def test_list_taglines_name_the_area(site: SiteConfig, rendered: Path) -> None:
    # The lists reach past the city (Everett, Corvallis), so they say "Seattle
    # area breweries"; Central Washington is already a region (Hal,
    # 2026-10-15). The events page keeps "in and around Seattle".
    area = site.template_vars["area"]
    for page, where in (
        ("fresh-hops.html", "breweries"),
        ("festbier.html", "breweries"),
        ("pumpkin.html", "breweries"),
        ("taprooms.html", "bottle shops and taprooms"),
    ):
        html = (rendered / page).read_text()
        assert f"on tap right now at {area} {where}." in html, page


def test_events_summary_names_the_place(site: SiteConfig, rendered: Path) -> None:
    """app.js is filled in too: its one sentence that names the place."""
    data = {
        "updated": "2026-10-15T20:00:00+00:00",
        "timezone": "America/Los_Angeles",
        "events": [
            {
                "date": "2026-10-20T00:00:00",
                "venue": "A Brewery",
                "venue_key": "brewery",
                "title": "Fresh Hop Fest",
            }
        ],
    }
    result = subprocess.run(
        ["node", str(RENDER), str(rendered / "app.js"), "events", json.dumps(data)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)["summary"]
    assert summary == (
        "<strong>1 upcoming beer event</strong> in and around "
        f"{site.template_vars['place']}."
    )


def test_events_tab_and_page_follow_the_event_sources(
    site: SiteConfig, rendered: Path
) -> None:
    """No event sources: no Events tab, page, sitemap entry, or calendar link."""
    sitemap = (rendered / "sitemap.xml").read_text()
    assert "{{" not in sitemap
    if _has_events(site):
        assert (rendered / "events.html").is_file()
        assert f"{site.public_url}/events.html" in sitemap
        return
    assert not (rendered / "events.html").exists()
    assert "events.html" not in sitemap
    for page in _pages(site):
        # (The pages' shared-layout comment still names the file.)
        assert 'href="events.html"' not in (rendered / page).read_text(), page


def test_which_sites_have_events() -> None:
    # Hal, 2026-10-13: Seattle lists beer events; Portland, Yakima, and Bend
    # list what is on tap only.
    with_events = {site.key for site in SITES if _has_events(site)}
    assert with_events == {"seattle-freshies"}
