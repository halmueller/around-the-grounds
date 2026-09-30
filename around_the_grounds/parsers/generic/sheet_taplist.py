"""Tap lists kept in a publicly viewable Google Sheet.

Reads one tab through the sheet's CSV endpoint
(``/gviz/tq?tqx=out:csv&sheet=<tab>``), the same URL the venue's own tap-list
widget uses. That endpoint silently falls back to the first tab when the
named tab is missing, so ``header_contains`` can guard against reading the
wrong list.

Config (``source_type: "sheet-taplist"``)::

    "parser_config": {
      "sheet_id": "1zzW5XS9...",
      "sheet_name": "GW",
      "header_contains": "Greenwood",       # optional, checked in header row
      "columns": {"name": 2, "style": 1, "abv": 9},  # zero-based; name required
      "brewery_separator": ":",             # optional, splits "Brewery: Beer"
      "skip_prefix": "-"                    # optional, e.g. kicked kegs
    }

Decorative symbols (emoji markers such as 🌿) are stripped from the ends of
names.
"""

import csv
import io
import unicodedata
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"


def _strip_symbols(text: str) -> str:
    """Trim whitespace and symbol characters (emoji, ZWJ, variation selectors)."""

    def is_decoration(ch: str) -> bool:
        return ch.isspace() or unicodedata.category(ch) in ("So", "Sk", "Cf", "Mn")

    start, end = 0, len(text)
    while start < end and is_decoration(text[start]):
        start += 1
    while end > start and is_decoration(text[end - 1]):
        end -= 1
    return text[start:end]


def _cell(row: List[str], index: Optional[int]) -> Optional[str]:
    if index is None or index >= len(row):
        return None
    value = row[index].strip()
    return value or None


def parse_sheet_rows(csv_text: str, config: Dict[str, Any]) -> List[TapEntry]:
    columns = config.get("columns") or {}
    if "name" not in columns:
        raise ValueError("sheet-taplist needs columns.name in parser_config")
    separator = config.get("brewery_separator")
    skip_prefix = config.get("skip_prefix")

    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    expected = config.get("header_contains")
    if expected and not any(expected.lower() in h.lower() for h in header):
        raise ValueError(
            f"Sheet tab {config.get('sheet_name')!r} header does not contain "
            f"{expected!r}; the tab may have been renamed"
        )

    entries = []
    for row in body:
        raw = _cell(row, columns["name"])
        if not raw or (skip_prefix and raw.startswith(skip_prefix)):
            continue
        name = _strip_symbols(raw)
        brewery = None
        if separator and separator in name:
            left, right = name.split(separator, 1)
            if left.strip() and right.strip():
                brewery, name = left.strip(), right.strip()
        if not name:
            continue
        entries.append(
            TapEntry(
                name=name,
                brewery=brewery,
                style=_cell(row, columns.get("style")),
                abv=_cell(row, columns.get("abv")),
            )
        )
    return entries


class SheetTaplistParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        sheet_id = config.get("sheet_id")
        sheet_name = config.get("sheet_name")
        if not sheet_id or not sheet_name:
            raise ValueError(
                f"{self.venue.key}: sheet-taplist needs sheet_id and sheet_name"
            )
        csv_text = await fetch_listing_text(
            session,
            SHEET_CSV_URL.format(sheet_id=sheet_id),
            params={"tqx": "out:csv", "sheet": sheet_name},
        )
        entries = parse_sheet_rows(csv_text, config)
        return build_listings(self.venue, entries, "sheet", self.logger)
