"""Tap lists published through Bevwerk website menus.

Bevwerk-hosted sites (Watershed Pub) place a ``<bw-website-menu-root
taplist-id="…">`` element on the page; its script fetches the menu from
Bevwerk's public GraphQL endpoint with just that id. This parser makes the
same query and reads the taps that are pouring now (status ``ON_TAP``,
skipping any "up next" category). The venue ``url`` is the bar's own menu
page, for people; it is not fetched.

Config (``source_type: "bevwerk"``)::

    "parser_config": {"taplist_id": "3670c864-6020-4ec6-9088-53bd97020edd"}
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

GRAPHQL_URL = "https://hasura.bevwerk.com/v1/graphql"

MENU_QUERY = """
query menu_data_first_paint($taplist_id: uuid!) {
  menu_data(where: {taplist_id: {_eq: $taplist_id}}) {
    data
  }
}
"""


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _tap_entry(tap: Dict[str, Any]) -> Optional[TapEntry]:
    item = tap.get("on_tap_item") or {}
    if item.get("status") != "ON_TAP":
        return None
    inventory = item.get("inventory_type") or {}
    if (inventory.get("menu_category") or {}).get("is_up_next"):
        return None
    product = inventory.get("product") or {}
    name = _clean(product.get("display_name")) or _clean(product.get("title"))
    if not name:
        return None
    producer = product.get("producer") or {}
    abv = _clean(product.get("abv"))
    return TapEntry(
        name=name,
        brewery=_clean(producer.get("display_name")) or _clean(producer.get("title")),
        style=_clean(product.get("style")),
        abv=f"{abv}%" if abv and not abv.endswith("%") else abv,
    )


def parse_bevwerk_menu(payload: Dict[str, Any]) -> List[TapEntry]:
    """TapEntries for the taps on tap now in a ``menu_data`` response."""
    if payload.get("errors"):
        raise ValueError(f"Bevwerk API error: {payload['errors']}")
    try:
        rows = payload["data"]["menu_data"]
    except (KeyError, TypeError) as e:
        raise ValueError("Bevwerk response has no menu_data") from e
    if not rows:
        raise ValueError("Bevwerk has no menu for this taplist_id")
    taplist = (rows[0].get("data") or {}).get("taplist_by_pk") or {}
    taps = sorted(taplist.get("taps") or [], key=lambda t: t.get("index") or 0)
    return [entry for entry in map(_tap_entry, taps) if entry is not None]


class BevwerkParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        taplist_id = (self.venue.parser_config or {}).get("taplist_id")
        if not taplist_id:
            raise ValueError(f"{self.venue.key}: bevwerk needs taplist_id")
        body = await fetch_listing_text(
            session,
            GRAPHQL_URL,
            json_body={"query": MENU_QUERY, "variables": {"taplist_id": taplist_id}},
        )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"Bevwerk returned invalid JSON: {e}") from e
        entries = parse_bevwerk_menu(payload)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no taps on the Bevwerk menu")
        return build_listings(self.venue, entries, "bevwerk", self.logger)
