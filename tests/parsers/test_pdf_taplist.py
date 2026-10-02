"""Tests for the PDF-menu (pdf-taplist) tap-list parser. The text fixture is
El Sueñito's live menu PDF as extracted on 2026-10-01; PDFs fetched in tests
are built here, since the real one is several megabytes of artwork."""

from pathlib import Path
from typing import Any, Dict, Iterator, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.pdf_taplist import (
    PdfTaplistParser,
    extract_pdf_lines,
    find_pdf_link,
    parse_pdf_taplist,
)
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

VENUE = {v.key: v for v in load_site_config("seattle-freshies").venues}[
    "el-suenito-taps"
]
CONFIG: Dict[str, Any] = dict(VENUE.parser_config or {})
PDF_URL = "https://www.elsuenitobrewing.com/_files/ugd/3b652b_beer.pdf"
PAGE = (
    '<a href="/_files/ugd/3b652b_food.pdf" aria-label="FOOD MENU">FOOD</a>'
    '<a href="/other">Beer club</a>'
    '<a href="/_files/ugd/3b652b_beer.pdf" aria-label="BEER &amp; DRINKS">'
    "<span>DRINKS</span></a>"
)


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


def make_pdf(lines: List[str]) -> bytes:
    """A minimal one-page PDF with one text line per entry of *lines*."""
    text = " ".join(
        "({}) Tj T*".format(
            line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        )
        for line in lines
    )
    stream = f"BT /F1 12 Tf 14 TL 72 720 Td {text} ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return out


MENU = [
    "Mariquita | Red Ale",
    "Sueños del Campo | Hazy Fresh Hop",
    "6.5% | The use of freshly picked, whole-cone",
    "Calabaza Loca | Pumpkin Ale",
    "$9 for 10 oz | $5 for 5 oz",
]


def test_source_type_is_registered() -> None:
    venue = Venue("some-taproom", "Some Taproom", "https://example.com", "pdf-taplist")
    assert ParserRegistry.get_parser(venue) is PdfTaplistParser
    assert PdfTaplistParser.PRODUCES_LISTINGS


class TestFindPdfLink:
    def test_matches_aria_label_and_resolves_relative_href(self) -> None:
        assert find_pdf_link(PAGE, VENUE.url, CONFIG["link_pattern"]) == PDF_URL

    def test_matches_link_text(self) -> None:
        url = find_pdf_link(PAGE, VENUE.url, "^food")
        assert url.endswith("3b652b_food.pdf")

    def test_ignores_links_that_are_not_pdfs(self) -> None:
        with pytest.raises(ValueError, match="No PDF link matching"):
            find_pdf_link(PAGE, VENUE.url, "club")

    def test_invalid_pattern(self) -> None:
        with pytest.raises(ValueError, match="Invalid link_pattern"):
            find_pdf_link(PAGE, VENUE.url, "(")


class TestExtractPdfLines:
    def test_reads_lines(self) -> None:
        assert extract_pdf_lines(make_pdf(MENU)) == MENU

    def test_not_a_pdf(self) -> None:
        with pytest.raises(ValueError, match="Could not read PDF"):
            extract_pdf_lines(b"<html>Not found</html>")


class TestParsePdfTaplist:
    def test_el_suenito_menu(self, fixtures_dir: Path) -> None:
        lines = (fixtures_dir / "text" / "pdf_el_suenito.txt").read_text().splitlines()
        entries = parse_pdf_taplist(lines, CONFIG)
        assert [(e.name, e.style, e.abv) for e in entries[:12]] == [
            ("Güerita", "Blonde Ale", "5.2%"),
            ("Conejo Azteca", "Mexican Dark Lager", "4.1%"),
            ("Night Shift", "West Coast IPA", "7%"),
            ("New Friends", "Dry Hopped Pale Ale", "5.3%"),
            ("Alemania", "German Kölsch-style Ale", "4.9%"),
            ("Alebrijes", "Mexican Lager", "4.7%"),
            # The PDF's text order puts these two after their descriptions.
            ("Mariquita", "Red Ale", None),
            ("Sueños del Campo", "Hazy Fresh Hop", "6.5%"),
            ("Still Standing Up", "Blackberry Saison", None),
            ("Patria", "Hazy IPA", "6.8%"),
            ("Ancestor’s Dreams", "Vienna Lager", "4.9%"),
            ("Fantasmas", "Imperial Stout", "10%"),
        ]
        # Page two's ciders; cocktails and prices are not entries.
        assert [e.name for e in entries[12:]] == [
            "Rotating Flavor",
            "Ch.ch.Cherry Bomb",
        ]

    def test_abv_group_wins_over_following_line(self) -> None:
        entries = parse_pdf_taplist(
            ["Fresh Hop IPA 6%", "7.5% | hoppy"],
            {"line_pattern": r"^(?P<name>.+?) (?P<abv>\d+%)$"},
        )
        assert [(e.name, e.abv) for e in entries] == [("Fresh Hop IPA", "6%")]

    @pytest.mark.parametrize(
        "config,message",
        [
            ({}, "needs line_pattern"),
            ({"line_pattern": "("}, "Invalid line_pattern"),
            ({"line_pattern": "^(.+)$"}, "needs a"),
        ],
    )
    def test_bad_config(self, config: Dict[str, Any], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_pdf_taplist(["x"], config)


class TestPdfTaplistParser:
    @pytest.mark.asyncio
    async def test_follows_page_link_to_pdf(self) -> None:
        with aioresponses() as m:
            m.get(VENUE.url, status=200, body=PAGE)
            m.get(PDF_URL, status=200, body=make_pdf(MENU))
            async with aiohttp.ClientSession() as session:
                events = await PdfTaplistParser(VENUE).parse(session)
        assert [(e.title, e.category, e.description) for e in events] == [
            ("Sueños del Campo", "fresh-hop", "Hazy Fresh Hop · 6.5%"),
            ("Calabaza Loca", "pumpkin", "Pumpkin Ale"),
        ]
        assert all(e.kind == "listing" for e in events)

    @pytest.mark.asyncio
    async def test_url_is_the_pdf_without_link_pattern(self) -> None:
        url = "https://example.com/menu.pdf"
        venue = Venue(
            "pdf-taps",
            "PDF Taproom",
            url,
            "pdf-taplist",
            {"line_pattern": CONFIG["line_pattern"]},
        )
        with aioresponses() as m:
            m.get(url, status=200, body=make_pdf(MENU))
            async with aiohttp.ClientSession() as session:
                events = await PdfTaplistParser(venue).parse(session)
        assert [e.title for e in events] == ["Sueños del Campo", "Calabaza Loca"]

    @pytest.mark.asyncio
    async def test_missing_pdf_link_is_an_error(self) -> None:
        with aioresponses() as m:
            m.get(VENUE.url, status=200, body="<a href='/menu'>Beer</a>")
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="No PDF link matching"):
                    await PdfTaplistParser(VENUE).parse(session)

    @pytest.mark.asyncio
    async def test_pdf_not_found_is_an_error(self) -> None:
        with aioresponses() as m:
            m.get(VENUE.url, status=200, body=PAGE)
            m.get(PDF_URL, status=404)
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="404"):
                    await PdfTaplistParser(VENUE).parse(session)
