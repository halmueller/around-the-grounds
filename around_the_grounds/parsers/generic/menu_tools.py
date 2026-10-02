"""Tap lists published through Menu Tools displays (Burke-Gilman Brewing).

A venue links or embeds ``app.menu.tools/display/<subscriber>/<location>/
<menu>``; that page loads the menu as JSON from ``/api/display/<same path>``.
This parser reads the same JSON and keeps the items marked available.

Config (``source_type: "menu-tools"``)::

    "parser_config": {"display_path": "bgbc/my-location/main-menu"}

The venue ``url`` is the venue's own tap-list page, for people; it is not
fetched.
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

API_URL = "https://app.menu.tools/api/display/{display_path}"


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _abv(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value:g}%"


def parse_menu_tools(payload: Dict[str, Any]) -> List[TapEntry]:
    entries = []
    for section in payload.get("sections") or []:
        for item in section.get("items") or []:
            name = _clean(item.get("name"))
            if not name or item.get("available") is False:
                continue
            entries.append(
                TapEntry(
                    name=name,
                    brewery=_clean(item.get("manufacturer")),
                    style=_clean(item.get("style")),
                    abv=_abv(item.get("abv")),
                    description=_clean(item.get("description")),
                )
            )
    return entries


class MenuToolsParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        display_path = str(config.get("display_path") or "").strip("/")
        if not display_path:
            raise ValueError(f"{self.venue.key}: menu-tools needs display_path")
        url = API_URL.format(display_path=display_path)
        text = await fetch_listing_text(session, url)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from Menu Tools: {e}") from e
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Menu Tools response from {url}")
        entries = parse_menu_tools(payload)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no items on the Menu Tools menu")
        return build_listings(self.venue, entries, "menu-tools", self.logger)
