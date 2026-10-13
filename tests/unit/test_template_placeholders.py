"""{{name}} placeholders in templates shared between sites."""

from pathlib import Path
from typing import Any, Dict

import pytest

from around_the_grounds.config.loader import load_all_sites
from around_the_grounds.main import _write_site_output

TEMPLATES = Path(__file__).resolve().parents[2] / "public_templates"


def _web_data(**extra: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "events": [],
        "site_name": "Hop Town Freshies",
        "public_url": "https://hoptown.example",
    }
    data.update(extra)
    return data


@pytest.fixture
def template(tmp_path: Path) -> Path:
    folder = tmp_path / "template"
    (folder / "nested").mkdir(parents=True)
    (folder / "index.html").write_text(
        '<title>{{site_name}}</title><a href="{{public_url}}/x.html">'
        "Beers in {{place}}, and more in {{place}}</a>\n"
    )
    (folder / "nested" / "app.js").write_text("const where = '{{place}}';\n")
    (folder / "robots.txt").write_text("Sitemap: {{public_url}}/sitemap.xml\n")
    (folder / "plain.html").write_text("<p>No placeholders</p>\n")
    (folder / "styles.css").write_text("/* {{place}} is left alone in CSS */\n")
    (folder / "logo.png").write_bytes(b"\x89PNG{{place}}\xff")
    return folder


def test_fills_every_placeholder(template: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _write_site_output(out, template, _web_data(template_vars={"place": "Hop Town"}))

    assert (out / "index.html").read_text() == (
        '<title>Hop Town Freshies</title><a href="https://hoptown.example/x.html">'
        "Beers in Hop Town, and more in Hop Town</a>\n"
    )
    assert (out / "nested" / "app.js").read_text() == "const where = 'Hop Town';\n"
    assert (out / "robots.txt").read_text() == (
        "Sitemap: https://hoptown.example/sitemap.xml\n"
    )
    assert (out / "plain.html").read_text() == "<p>No placeholders</p>\n"


SECTIONED = (
    "<header>\n"
    "    <h1>{{site_name}}</h1>\n"
    "    {{#neighbors}}\n"
    "    <p>Next door: {{neighbors}}</p>\n"
    "    <p>Second line</p>\n"
    "    {{/neighbors}}\n"
    "    <nav></nav>\n"
    "</header>\n"
)


def test_section_is_kept_for_a_site_that_sets_the_value(tmp_path: Path) -> None:
    folder = tmp_path / "template"
    folder.mkdir()
    (folder / "index.html").write_text(SECTIONED)
    out = tmp_path / "out"
    _write_site_output(out, folder, _web_data(template_vars={"neighbors": "Hopville"}))

    assert (out / "index.html").read_text() == (
        "<header>\n"
        "    <h1>Hop Town Freshies</h1>\n"
        "    <p>Next door: Hopville</p>\n"
        "    <p>Second line</p>\n"
        "    <nav></nav>\n"
        "</header>\n"
    )


def test_section_is_dropped_for_a_site_that_does_not(tmp_path: Path) -> None:
    folder = tmp_path / "template"
    folder.mkdir()
    (folder / "index.html").write_text(SECTIONED)
    out = tmp_path / "out"
    _write_site_output(out, folder, _web_data(template_vars={"place": "Hop Town"}))

    assert (out / "index.html").read_text() == (
        "<header>\n    <h1>Hop Town Freshies</h1>\n    <nav></nav>\n</header>\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        "{{#neighbors}}\n<p>never closed</p>\n",
        "<p>never opened</p>\n{{/neighbors}}\n",
        "<p>{{#neighbors}}inline{{/neighbors}}</p>\n",
        "{{#neighbors}}\n<p>wrong close</p>\n{{/place}}\n",
    ],
)
def test_unmatched_section_marker_fails(tmp_path: Path, text: str) -> None:
    folder = tmp_path / "template"
    folder.mkdir()
    (folder / "index.html").write_text(text)
    out = tmp_path / "out"
    data = _web_data(template_vars={"place": "Hop Town", "neighbors": "Hopville"})
    with pytest.raises(ValueError, match="Unmatched"):
        _write_site_output(out, folder, data)
    assert not out.exists()


def test_fresh_hop_byline_for_another_city(tmp_path: Path) -> None:
    """The food-truck line is Seattle's; other cities credit a Seattle resident."""
    out = tmp_path / "out"
    data = _web_data(template_vars={"place": "Hop Town", "author_home": "Seattle"})
    _write_site_output(out, TEMPLATES / "fresh-hop", data)

    for page in out.glob("*.html"):
        html = page.read_text()
        assert "{{" not in html, page.name
        assert "ballardfoodtrucks" not in html, page.name
        if page.name != "index.html":
            assert '<p class="byline">By Seattle resident <a ' in html, page.name
            assert html.count('class="byline"') == 1, page.name


def test_other_file_types_are_copied_as_is(template: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _write_site_output(out, template, _web_data(template_vars={"place": "Hop Town"}))

    assert "{{place}}" in (out / "styles.css").read_text()
    assert (out / "logo.png").read_bytes() == b"\x89PNG{{place}}\xff"


def test_template_itself_is_not_modified(template: Path, tmp_path: Path) -> None:
    before = (template / "index.html").read_text()
    _write_site_output(
        tmp_path / "out", template, _web_data(template_vars={"place": "Hop Town"})
    )
    assert (template / "index.html").read_text() == before


def test_site_without_template_vars_is_copied_unchanged(
    template: Path, tmp_path: Path
) -> None:
    """Other sites' templates may use {{...}} for their own purposes."""
    out = tmp_path / "out"
    _write_site_output(out, template, _web_data())

    for name in ("index.html", "nested/app.js", "robots.txt"):
        assert (out / name).read_bytes() == (template / name).read_bytes()


def test_trailing_slash_on_public_url_is_dropped(
    template: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    data = _web_data(
        public_url="https://hoptown.example/", template_vars={"place": "Hop Town"}
    )
    _write_site_output(out, template, data)
    assert "https://hoptown.example/sitemap.xml" in (out / "robots.txt").read_text()


@pytest.mark.parametrize(
    "data, message",
    [
        (_web_data(template_vars={"region": "Hop Town"}), "{{place}}"),
        (_web_data(template_vars={"place": "Hop Town"}, public_url=""), "public_url"),
        (_web_data(template_vars={"place": "Hop <b>Town</b>"}), "plain text"),
        (_web_data(template_vars={"place": 'Hop "Town"'}), "plain text"),
        (_web_data(template_vars={"place": "O'Hop"}), "plain text"),
        (_web_data(template_vars={"place": "Hop & Town"}), "plain text"),
        (_web_data(template_vars={"place": "{{site_name}}"}), "plain text"),
        (
            _web_data(template_vars={"place": "Hop Town"}, site_name="Hops </title>"),
            "plain text",
        ),
        (_web_data(template_vars={"place": "x", "site_name": "y"}), "override"),
        (_web_data(template_vars={"place": 7}), "string"),
    ],
)
def test_bad_values_fail_before_anything_is_written(
    template: Path, tmp_path: Path, data: Dict[str, Any], message: str
) -> None:
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=message):
        _write_site_output(out, template, data)
    assert not out.exists()


@pytest.mark.parametrize(
    "site", [s for s in load_all_sites() if s.template_vars], ids=lambda s: s.key
)
def test_real_sites_leave_no_placeholder_behind(site: Any, tmp_path: Path) -> None:
    out = tmp_path / "out"
    data = _web_data(
        site_name=site.name,
        public_url=site.public_url,
        template_vars=site.template_vars,
    )
    _write_site_output(out, TEMPLATES / site.template, data)

    for path in out.rglob("*"):
        if path.suffix in {".html", ".js", ".xml", ".txt"}:
            assert "{{" not in path.read_text(), path.name


def test_sites_on_the_fresh_hop_template_set_template_vars() -> None:
    """Without template_vars the pages would publish with raw placeholders."""
    for site in load_all_sites():
        if site.template == "fresh-hop":
            assert site.template_vars.get("place"), site.key
            assert site.template_vars.get("author_home"), site.key
