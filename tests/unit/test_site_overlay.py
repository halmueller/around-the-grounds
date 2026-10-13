"""Per-site files copied over a template that several sites share."""

import struct
from pathlib import Path
from typing import Any, Dict

import pytest

from around_the_grounds.config.loader import load_all_sites
from around_the_grounds.main import _write_site_output

TEMPLATES = Path(__file__).resolve().parents[2] / "public_templates"


def _web_data(site_key: Any) -> Dict[str, Any]:
    return {"events": [], "site_key": site_key, "site_name": "Hop Town Freshies"}


@pytest.fixture
def template(tmp_path: Path) -> Path:
    """A templates root with one template and overlays for two sites."""
    root = tmp_path / "public_templates"
    folder = root / "shared"
    folder.mkdir(parents=True)
    (folder / "index.html").write_text("<p>shared</p>\n")
    (folder / "card.png").write_bytes(b"shared card")
    (root / "_overlays" / "hop-town" / "img").mkdir(parents=True)
    (root / "_overlays" / "hop-town" / "card.png").write_bytes(b"hop town card")
    (root / "_overlays" / "hop-town" / "img" / "extra.png").write_bytes(b"extra")
    (root / "_overlays" / "other-town").mkdir()
    (root / "_overlays" / "other-town" / "card.png").write_bytes(b"other card")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "card.png").write_bytes(b"outside")
    return folder


def test_overlay_files_replace_and_add_to_the_template(
    template: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    _write_site_output(out, template, _web_data("hop-town"))

    assert (out / "index.html").read_text() == "<p>shared</p>\n"
    assert (out / "card.png").read_bytes() == b"hop town card"
    assert (out / "img" / "extra.png").read_bytes() == b"extra"
    assert not (out / "_overlays").exists()


def test_site_without_an_overlay_gets_the_template_only(
    template: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    _write_site_output(out, template, _web_data("no-overlay-town"))

    assert (out / "card.png").read_bytes() == b"shared card"
    assert not (out / "img").exists()


@pytest.mark.parametrize(
    "site_key", ["../../secret", "..", "hop-town/img", "", None, "hop town", "."]
)
def test_keys_that_are_not_a_plain_slug_get_no_overlay(
    template: Path, tmp_path: Path, site_key: Any
) -> None:
    out = tmp_path / "out"
    _write_site_output(out, template, _web_data(site_key))

    assert (out / "card.png").read_bytes() == b"shared card"
    assert not (out / "extra.png").exists()


def test_every_fresh_hop_site_has_its_own_open_graph_card() -> None:
    """Pages point og:image at og-image.png, which the template does not ship."""
    for site in load_all_sites():
        if site.template != "fresh-hop":
            continue
        card = TEMPLATES / "_overlays" / site.key / "og-image.png"
        assert card.is_file(), f"{site.key}: run deploy/images/render.py"
        data = card.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", site.key
        assert struct.unpack(">II", data[16:24]) == (1200, 630), site.key
