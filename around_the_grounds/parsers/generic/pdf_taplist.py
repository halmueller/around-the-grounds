"""Tap lists published as a PDF menu (El Sueñito's "BEER & DRINKS" button).

The PDF's text is read line by line, and each line is matched against
``line_pattern``; its named groups become the entry, as in ``text-taplist``.
Lines that don't match are ignored. When the line after an entry starts with
a percentage ("6.5% | The use of freshly picked…"), that is its ABV.

Site builders (Wix) give every upload a new file name, so the PDF is usually
found through the page linking to it rather than addressed directly.

Config (``source_type: "pdf-taplist"``)::

    "parser_config": {
      "line_pattern": "^(?P<name>[^|]+)\\\\|(?P<style>[^|]+)$",  # needs name
      "link_pattern": "beer"   # optional regex, case-insensitive
    }

With ``link_pattern``, the venue ``url`` is a web page: its first link to a
``.pdf`` whose text or ``aria-label`` matches is the menu. Without it, the
venue ``url`` is the PDF itself. Optional named groups: ``style``, ``abv``,
``brewery``.
"""

import io
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

from ...models import Event
from ..base import BaseParser
from .listing_common import (
    TapEntry,
    build_listings,
    fetch_listing_bytes,
    fetch_listing_text,
    normalize_abv,
)

_ABV_LINE = re.compile(r"^\d+(?:\.\d+)?\s*%")


def find_pdf_link(html: str, base_url: str, link_pattern: str) -> str:
    """Return the URL of the first PDF link whose label matches *link_pattern*."""
    try:
        pattern = re.compile(link_pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Invalid link_pattern: {e}") from e
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a", href=True):
        if not isinstance(link, Tag):
            continue
        url = urljoin(base_url, str(link["href"]))
        if not urlparse(url).path.lower().endswith(".pdf"):
            continue
        label = f"{link.get_text(' ', strip=True)} {link.get('aria-label') or ''}"
        if pattern.search(label):
            return url
    raise ValueError(f"No PDF link matching {link_pattern!r} on: {base_url}")


def extract_pdf_lines(data: bytes) -> List[str]:
    """Return the PDF's text as whitespace-normalized, non-empty lines."""
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:  # pypdf raises many types on damaged files
        raise ValueError(f"Could not read PDF: {e}") from e
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return [line for line in lines if line]


def _group(match: "re.Match[str]", name: str) -> Optional[str]:
    if name not in match.re.groupindex:
        return None
    value = match.group(name)
    return value.strip() if value and value.strip() else None


def parse_pdf_taplist(lines: List[str], config: Dict[str, Any]) -> List[TapEntry]:
    pattern_text = config.get("line_pattern")
    if not pattern_text:
        raise ValueError("pdf-taplist needs line_pattern")
    try:
        pattern = re.compile(pattern_text)
    except re.error as e:
        raise ValueError(f"Invalid line_pattern: {e}") from e
    if "name" not in pattern.groupindex:
        raise ValueError("pdf-taplist line_pattern needs a (?P<name>...) group")

    entries = []
    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue
        name = (_group(match, "name") or "").strip("* ")
        if not name:
            continue
        abv = _group(match, "abv")
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if not abv and _ABV_LINE.match(following):
            abv = following
        entries.append(
            TapEntry(
                name=name,
                brewery=_group(match, "brewery"),
                style=_group(match, "style"),
                abv=normalize_abv(abv),
            )
        )
    return entries


class PdfTaplistParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        pdf_url = self.venue.url
        link_pattern = config.get("link_pattern")
        if link_pattern:
            html = await fetch_listing_text(session, self.venue.url)
            pdf_url = find_pdf_link(html, self.venue.url, link_pattern)
        data = await fetch_listing_bytes(session, pdf_url)
        entries = parse_pdf_taplist(extract_pdf_lines(data), config)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no tap-list lines matched")
        return build_listings(self.venue, entries, "pdf", self.logger)
