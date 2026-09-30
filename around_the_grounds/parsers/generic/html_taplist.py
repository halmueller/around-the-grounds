"""Tap lists rendered as repeated HTML items, described by CSS selectors.

Config (``source_type: "html-taplist"``; the venue ``url`` is fetched)::

    "parser_config": {
      "item": "div.beer-on-tap-detail",   # required: one element per beer
      "name": "h2",                       # required, within the item
      "style": ".beer-style",             # optional
      "brewery": ".producer",             # optional
      "abv": ".abv",                      # optional; else searched in item text
      "style_pattern": "-\\s*([^,]+),",    # optional: style from item text
      "match_whole_item": false,          # also match on the item's full text
      "name_fallback_to_style": false,    # unnamed item: use its style as name
      "exclude_sections": ["\\\\bto go\\\\b"]  # skip items under these headings
    }

Two platform presets supply the selectors:

- ``craftpeak-wot``: Craftpeak/Arryved "What's On Tap" modules on brewery
  WordPress sites (Cloudburst, Holy Mountain, Fair Isle). Unnamed items are
  taps whose beer page is not yet published; their style stands in as name.
- ``digitalpour``: DigitalPour's embeddable menu page. Config needs
  ``company_id`` and ``location_id`` (from the venue's iframe URL).
"""

import re
from typing import Any, Dict, List, Optional, Set

import aiohttp
from bs4 import BeautifulSoup, Tag

from ...models import Event
from ..base import BaseParser
from .listing_common import (
    TapEntry,
    build_listings,
    fetch_listing_text,
    normalize_abv,
)

_HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _text(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def _select_text(item: Tag, selector: Optional[str]) -> Optional[str]:
    return _text(item.select_one(selector)) if selector else None


def _section_heading(item: Tag, item_ids: Set[int]) -> Optional[str]:
    """Nearest heading before *item* that is not inside another item."""
    for heading in item.find_all_previous(_HEADINGS):
        if not isinstance(heading, Tag):
            continue
        if any(id(parent) in item_ids for parent in heading.parents):
            continue
        text = _text(heading)
        if text:
            return text
    return None


def parse_html_taplist(html: str, config: Dict[str, Any]) -> List[TapEntry]:
    if not config.get("item") or not config.get("name"):
        raise ValueError("html-taplist needs item and name selectors")
    try:
        excludes = [
            re.compile(p, re.IGNORECASE) for p in config.get("exclude_sections", [])
        ]
    except re.error as e:
        raise ValueError(f"Invalid exclude_sections pattern: {e}") from e

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    style_pattern = None
    if config.get("style_pattern"):
        try:
            style_pattern = re.compile(config["style_pattern"])
        except re.error as e:
            raise ValueError(f"Invalid style_pattern: {e}") from e
    items = soup.select(config["item"])
    item_ids = {id(item) for item in items}

    entries = []
    for item in items:
        if excludes:
            heading = _section_heading(item, item_ids) or ""
            if any(p.search(heading) for p in excludes):
                continue
        name = _select_text(item, config["name"])
        style = _select_text(item, config.get("style"))
        if style is None and style_pattern is not None:
            found = style_pattern.search(_text(item) or "")
            style = found.group(1).strip() if found else None
        if not name and config.get("name_fallback_to_style") and style:
            name, style = style, None
        if not name:
            continue
        abv_text = _select_text(item, config.get("abv")) if config.get("abv") else None
        entries.append(
            TapEntry(
                name=name,
                brewery=_select_text(item, config.get("brewery")),
                style=style,
                abv=normalize_abv(abv_text or _text(item)),
                match_text=_text(item) if config.get("match_whole_item") else None,
            )
        )
    return entries


class HtmlTaplistParser(BaseParser):
    PRESET: Dict[str, Any] = {}

    def config(self) -> Dict[str, Any]:
        return {**self.PRESET, **(self.venue.parser_config or {})}

    def source_url(self, config: Dict[str, Any]) -> str:
        return self.venue.url

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.config()
        url = self.source_url(config)
        entries = parse_html_taplist(await fetch_listing_text(session, url), config)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no tap-list items at {url}")
        return build_listings(self.venue, entries, "html", self.logger)


class CraftpeakWotParser(HtmlTaplistParser):
    PRESET = {
        "item": ".wot-items .list-item",
        "name": ".item-title",
        "style": ".item-descriptor",
        "abv": ".item-abv",
        "name_fallback_to_style": True,
        "exclude_sections": [r"\bto go\b"],
    }


class DigitalPourParser(HtmlTaplistParser):
    MENU_URL = "https://fbpage.digitalpour.com/"
    PRESET = {
        "item": ".lineItem",
        "name": ".beverageName",
        "brewery": ".producerName",
        "style": ".beverageStyle",
        "abv": ".abv",
    }

    def source_url(self, config: Dict[str, Any]) -> str:
        company, location = config.get("company_id"), config.get("location_id")
        if not company or not location:
            raise ValueError(
                f"{self.venue.key}: digitalpour needs company_id and location_id"
            )
        return f"{self.MENU_URL}?companyID={company}&locationID={location}"
