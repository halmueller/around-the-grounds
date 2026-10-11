"""Tap lists kept as a category of a Square Online ordering site (Maize &
Barley).

A ``<name>.square.site`` ordering page is drawn by script; it loads each
category's items as JSON from Square's storefront address
(``cdn5.editmysite.com/app/store/api/v28/editor/users/<user>/sites/<site>/
products``). This parser reads the same JSON. It is the page's own data
request, not a documented API, so it may need care when Square changes it.

Config (``source_type: "square-online"``)::

    "parser_config": {
      "user_id": "125835288",             # `user_id: '…'` in the page source
      "site_id": "507456299749329449",    # `"site_id":…` in the page source
      "category_id": "3IQ72W2FVUNOOR3CY6EV5AYG",  # after "#" in the
                                          #   category's link
      "location_id": "4BVH25KR5VSFN",     # optional, `?location=` in the link
      "name_pattern": "^\\d+\\.\\s*(?P<name>.+?)\\s*-\\s*(?P<brewery>[^-]+)$"
    }

``name_pattern`` is optional. With it, items whose names don't match are
skipped (Maize & Barley numbers its draft lines; cans and the taster pour are
unnumbered), and its ``name`` and optional ``brewery`` groups replace the
item's name. Items marked out of stock are skipped. The ABV is the first
percentage in the item's description, which is also offered to the matcher.

Emoji at the ends of a name are not shown, but the matcher still sees them:
TeKu Tavern marks its fresh hops 💚, pumpkin beers 🎃, and festbiers 🍺, so
its config lists those as ``listing_include`` / ``pumpkin_include`` /
``festbier_include``.

The venue ``url`` is the venue's ordering page, for people; it is not fetched.
"""

import json
import re
from typing import Any, Dict, List, Optional, Pattern

import aiohttp
from bs4 import BeautifulSoup

from ...models import Event
from ..base import BaseParser
from .listing_common import (
    TapEntry,
    build_listings,
    fetch_listing_text,
    normalize_abv,
    strip_symbols,
)

API_URL = (
    "https://cdn5.editmysite.com/app/store/api/v28/editor/users/{user_id}"
    "/sites/{site_id}/products"
)
PER_PAGE = 180
MAX_PAGES = 5


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())
    return text or None


def parse_square_online(
    payload: Dict[str, Any], name_pattern: Optional[Pattern[str]] = None
) -> List[TapEntry]:
    entries = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        name = raw_name = _clean(item.get("name"))
        badges = item.get("badges")
        if not name or (isinstance(badges, dict) and badges.get("out_of_stock")):
            continue
        brewery = None
        if name_pattern is not None:
            match = name_pattern.search(name)
            if not match:
                continue
            groups = match.groupdict()
            name = (groups.get("name") or "").strip()
            brewery = (groups.get("brewery") or "").strip() or None
        name = strip_symbols(name)
        if not name:
            continue
        description = _clean(item.get("short_description"))
        entries.append(
            TapEntry(
                name=name,
                brewery=brewery,
                abv=normalize_abv(description),
                match_text=raw_name,
                description=description,
            )
        )
    return entries


class SquareOnlineParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        ids = {k: str(config.get(k) or "") for k in ("user_id", "site_id")}
        category_id = str(config.get("category_id") or "")
        if not all(ids.values()) or not category_id:
            raise ValueError(
                f"{self.venue.key}: square-online needs user_id, site_id, "
                "and category_id"
            )
        try:
            name_pattern = (
                re.compile(config["name_pattern"])
                if config.get("name_pattern")
                else None
            )
        except re.error as e:
            raise ValueError(f"Invalid name_pattern: {e}") from e
        if name_pattern is not None and "name" not in name_pattern.groupindex:
            raise ValueError("square-online name_pattern needs a (?P<name>…) group")

        url = API_URL.format(**ids)
        params: Dict[str, Any] = {
            "per_page": PER_PAGE,
            "categories[]": category_id,
            "visibilities[]": "visible",
        }
        if config.get("location_id"):
            params["location"] = str(config["location_id"])
        entries: List[TapEntry] = []
        for page in range(1, MAX_PAGES + 1):
            text = await fetch_listing_text(session, url, {**params, "page": page})
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON from Square Online: {e}") from e
            if not isinstance(payload, dict) or not isinstance(
                payload.get("data"), list
            ):
                raise ValueError(f"Unexpected Square Online response from {url}")
            entries.extend(parse_square_online(payload, name_pattern))
            pagination = (payload.get("meta") or {}).get("pagination") or {}
            if page >= int(pagination.get("total_pages") or 1):
                break
        if not entries:
            self.logger.warning(
                f"{self.venue.name}: no items in the Square Online category"
            )
        return build_listings(self.venue, entries, "square-online", self.logger)
