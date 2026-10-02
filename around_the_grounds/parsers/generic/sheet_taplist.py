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
                                            #   (also "brewery")
      "brewery_separator": ":",             # optional, splits "Brewery: Beer"
      "skip_prefix": "-",                   # optional, e.g. kicked kegs
      "name_remove": "\\s*\\(\\.?\\d.*L\\b.*\\)$"  # optional regex cut from names
    }

A sheet shared with "Publish to the web" instead (The Beer Authority) is read
from its published CSV address: give ``csv_url`` in place of ``sheet_id`` /
``sheet_name``, and ``"header_rows": 0`` when its first row is already a beer.
A bare number in the ABV column ("6.8") is shown as a percentage.

Decorative symbols (emoji markers such as 🌿) are stripped from the ends of
names.
"""

import csv
import io
import re
import unicodedata
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
_BARE_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


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
    try:
        name_remove = (
            re.compile(config["name_remove"]) if config.get("name_remove") else None
        )
    except re.error as e:
        raise ValueError(f"Invalid name_remove pattern: {e}") from e

    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return []
    header_rows = int(config.get("header_rows", 1))
    header = [cell for row in rows[:header_rows] for cell in row]
    body = rows[header_rows:]
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
        if name_remove is not None:
            raw = name_remove.sub("", raw)
        name = _strip_symbols(raw)
        brewery = None
        if separator and separator in name:
            left, right = name.split(separator, 1)
            if left.strip() and right.strip():
                brewery, name = left.strip(), right.strip()
        if not name:
            continue
        abv = _cell(row, columns.get("abv"))
        if abv and _BARE_NUMBER.match(abv):
            abv = f"{float(abv):g}%"
        entries.append(
            TapEntry(
                name=name,
                brewery=brewery or _cell(row, columns.get("brewery")),
                style=_cell(row, columns.get("style")),
                abv=abv,
            )
        )
    return entries


class SheetTaplistParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        sheet_id = config.get("sheet_id")
        sheet_name = config.get("sheet_name")
        if config.get("csv_url"):
            csv_text = await fetch_listing_text(session, str(config["csv_url"]))
        elif not sheet_id or not sheet_name:
            raise ValueError(
                f"{self.venue.key}: sheet-taplist needs sheet_id and sheet_name, "
                "or csv_url"
            )
        else:
            csv_text = await fetch_listing_text(
                session,
                SHEET_CSV_URL.format(sheet_id=sheet_id),
                params={"tqx": "out:csv", "sheet": sheet_name},
            )
        entries = parse_sheet_rows(csv_text, config)
        return build_listings(self.venue, entries, "sheet", self.logger)
