"""Tap lists served as JSON rows by a bar's own live-tap-list page (Roscoe's,
Tiny Bubble Room).

The page fills itself in from ``/api/taplist``, which answers with the rows
of the bar's spreadsheet, two rows per tap::

    ["1", "F.H. Thunder Blanket", "*", "Astoria, OR", "ABV", "8", "Fresh Hop …"]
    ["",  "Fort George",          "",  "",            "12",  "",  ""]

The first row has the tap number, the beer, a glass mark, where it is from, a
label, the price, and a description; the second has the brewery and the ABV.
Rows that do not start with a tap number (the title, the glass key, section
labels) are not taps.

Config (``source_type: "tap-rows"``)::

    "parser_config": {"rows_url": "https://www.roscoespdx.com/api/taplist"}

The venue ``url`` is the page people visit; it is not fetched.
"""

import json
import re
from typing import Any, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

# The description opens with the style, set off by underscores
# ("__Kolsch-style ale.__ Brewed with …") or a dash ("Fresh Hop IPA-  Brewed …").
_STYLE = re.compile(r"^(?:__\s*(.+?)[.\s]*__|([^-–]{2,40}?)\s*[-–]\s{1,})")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


def _cell(row: Any, index: int) -> str:
    if not isinstance(row, list) or index >= len(row):
        return ""
    value = row[index]
    return " ".join(value.split()) if isinstance(value, str) else ""


def _abv(text: str) -> Optional[str]:
    return f"{float(text):g}%" if _NUMBER.match(text) else None


def parse_tap_rows(rows: List[Any]) -> List[TapEntry]:
    entries = []
    for index, row in enumerate(rows):
        name = _cell(row, 1)
        if not _cell(row, 0).isdigit() or not name:
            continue
        following = rows[index + 1] if index + 1 < len(rows) else []
        # The row after a tap completes it, unless it is the next tap.
        if _cell(following, 0):
            following = []
        description = _cell(row, 6).replace("_", " ")
        description = " ".join(description.split())
        style = _STYLE.match(_cell(row, 6))
        entries.append(
            TapEntry(
                name=name,
                brewery=_cell(following, 1) or None,
                style=(
                    (style.group(1) or style.group(2)).strip(" -–.") or None
                    if style
                    else None
                ),
                abv=_abv(_cell(following, 4)),
                description=description or None,
            )
        )
    return entries


class TapRowsParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        url = str(config.get("rows_url") or "").strip()
        if not url:
            raise ValueError(f"{self.venue.key}: tap-rows needs rows_url")
        text = await fetch_listing_text(session, url)
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from {url}: {e}") from e
        if not isinstance(rows, list):
            raise ValueError(f"Unexpected tap-rows response from {url}")
        entries = parse_tap_rows(rows)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no taps in the rows")
        return build_listings(self.venue, entries, "tap-rows", self.logger)
