"""Tap lists published through Untappd for Business website embeds.

Venues embed their menu with ``PreloadEmbedMenu(container, location_id,
theme_id)``, which loads ``business.untappd.com/locations/<id>/themes/<id>/js``.
That script assigns the rendered menu HTML to ``container.innerHTML`` as a
JavaScript string literal; this parser decodes that string and reads the
menu items. Themes differ in markup, so each field falls back through the
selectors seen in the wild:

- standard theme: ``h4.item-name`` link (minus ``.item-tap-number``),
  ``.item-category`` style, ``.item-abv``, ``.brewery``
- table theme: ``.table-name .item`` name, ``.item-abv``

Config (``source_type: "untappd-embed"``)::

    "parser_config": {"location_id": 3026, "theme_id": 8580}
"""

import json
import re
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup, Tag

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

EMBED_URL = "https://business.untappd.com/locations/{location_id}/themes/{theme_id}/js"

_INNER_HTML = re.compile(r'innerHTML\s*=\s*"((?:[^"\\]|\\.)*)"', re.S)


def decode_embed_html(script: str) -> str:
    """Extract the menu HTML from the embed script's string literal."""
    match = _INNER_HTML.search(script)
    if not match:
        raise ValueError("Untappd embed script has no menu HTML")
    # JavaScript allows escapes JSON does not (\$ and \'); the rest is JSON.
    literal = re.sub(r"\\([$'])", r"\1", match.group(1))
    try:
        html: str = json.loads(f'"{literal}"', strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not decode Untappd embed menu: {e}") from e
    return html


def _text(item: Tag, selector: str) -> Optional[str]:
    node = item.select_one(selector)
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def _name(item: Tag) -> Optional[str]:
    link = item.select_one(".item-name a")
    if link is not None:
        for tap in link.select(".item-tap-number"):
            tap.decompose()
        name = " ".join(link.get_text(" ", strip=True).split())
        if name:
            return name
    return _text(item, ".table-name .item") or _text(item, ".item-name")


def _style(item: Tag) -> Optional[str]:
    # Some breweries put a hop list here, prefixed with dashes.
    style = _text(item, ".item-category")
    if style is None:
        return None
    return style.lstrip("- ") or None


def parse_embed_menu(html: str) -> List[TapEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for item in soup.select(".menu-item"):
        name = _name(item)
        if not name:
            continue
        abv = _text(item, ".item-abv")
        entries.append(
            TapEntry(
                name=name,
                brewery=_text(item, ".brewery"),
                style=_style(item),
                abv=abv.replace(" ABV", "") if abv else None,
            )
        )
    return entries


class UntappdEmbedParser(BaseParser):
    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        try:
            url = EMBED_URL.format(
                location_id=int(config["location_id"]),
                theme_id=int(config["theme_id"]),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"{self.venue.key}: untappd-embed needs integer "
                f"location_id and theme_id in parser_config"
            ) from e

        script = await fetch_listing_text(session, url)
        entries = parse_embed_menu(decode_embed_html(script))
        if not entries:
            # An empty menu is legitimate but rare; a theme change is likelier.
            self.logger.warning(f"{self.venue.name}: no menu items in {url}")
        return build_listings(self.venue, entries, "untappd", self.logger)
