"""Tap lists from public Untappd venue pages (``untappd.com/v/<slug>/<id>``).

Verified venues can publish their menu on their Untappd page. Each item is
an ``li.menu-item`` with the tap number and name in ``h5 a``, the style in
``h5 em``, and ABV and brewery in ``h6``. Venues that are verified but do not
publish a menu produce no items.

Config (``source_type: "untappd-venue"``): the venue ``url`` is the page.
"""

import re
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup, Tag

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

_TAP_NUMBER = re.compile(r"^\d+\.\s*")
_ABV = re.compile(r"(\d+(?:\.\d+)?%)\s*ABV")


def _clean(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def parse_venue_menu(html: str) -> List[TapEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for item in soup.select("li.menu-item"):
        raw_name = _clean(item.select_one(".beer-details h5 a"))
        if not raw_name:
            continue
        meta = _clean(item.select_one(".beer-details h6")) or ""
        abv = _ABV.search(meta)
        entries.append(
            TapEntry(
                name=_TAP_NUMBER.sub("", raw_name),
                brewery=_clean(item.select_one('h6 a[data-href=":brewery"]')),
                style=_clean(item.select_one(".beer-details h5 em")),
                abv=abv.group(1) if abv else None,
            )
        )
    return entries


class UntappdVenueParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        html = await fetch_listing_text(session, self.venue.url)
        entries = parse_venue_menu(html)
        if not entries:
            self.logger.warning(
                f"{self.venue.name}: no published menu on {self.venue.url}"
            )
        return build_listings(self.venue, entries, "untappd", self.logger)
