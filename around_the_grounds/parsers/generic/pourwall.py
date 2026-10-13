"""Tap lists published through Pourwall digital menus.

Pourwall sites (5th Line) frame ``app.pourwall.com/embed/<location id>/…``;
that page asks Pourwall's public GraphQL endpoint for the location's taps
with just that id. This parser makes the same query and reads the taps that
are pouring now (status ``ACTIVE``; the query also returns ``ON_DECK`` taps,
which are not on yet). The venue ``url`` is the brewery's own tap-list page,
for people; it is not fetched.

Config (``source_type: "pourwall"``)::

    "parser_config": {"location_id": "613b681edda9c1000831588a"}

Bars list soda, wine, and other non-beer lines as taps too; they simply
don't match any category.
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

GRAPHQL_URL = "https://api.pourwall.com/graphql"

# The embed's own query. Asking for ACTIVE taps alone is refused, so both
# statuses are requested and ON_DECK taps are dropped here.
TAPS_QUERY = """
query GetTapsByStatus($location: MongoID!, $statuses: [EnumTapStatus]) {
  taps: tapMany(
    filter: {location: $location, _operators: {status: {in: $statuses}}}
  ) {
    name
    status
    beverage { name style abv description source { name } }
  }
}
"""
STATUSES = ["ACTIVE", "ON_DECK"]


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _abv(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return f"{float(value):g}%"


def _tap_number(tap: Dict[str, Any]) -> float:
    number = tap.get("name")
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return float("inf")
    return float(number)


def _tap_entry(tap: Dict[str, Any]) -> Optional[TapEntry]:
    if tap.get("status") != "ACTIVE":
        return None
    beverage = tap.get("beverage") or {}
    name = _clean(beverage.get("name"))
    if not name:
        return None
    return TapEntry(
        name=name,
        brewery=_clean((beverage.get("source") or {}).get("name")),
        style=_clean(beverage.get("style")),
        abv=_abv(beverage.get("abv")),
        description=_clean(beverage.get("description")),
    )


def parse_pourwall_taps(payload: Any) -> List[TapEntry]:
    """TapEntries for the taps pouring now, in tap order."""
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Pourwall response")
    if payload.get("errors"):
        raise ValueError(f"Pourwall API error: {payload['errors']}")
    try:
        taps = payload["data"]["taps"]
    except (KeyError, TypeError) as e:
        raise ValueError("Pourwall response has no taps") from e
    if not isinstance(taps, list):
        raise ValueError("Pourwall response has no taps")
    ordered = sorted((t for t in taps if isinstance(t, dict)), key=_tap_number)
    return [entry for entry in map(_tap_entry, ordered) if entry is not None]


class PourwallParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        location_id = (self.venue.parser_config or {}).get("location_id")
        if not location_id:
            raise ValueError(f"{self.venue.key}: pourwall needs location_id")
        body = await fetch_listing_text(
            session,
            GRAPHQL_URL,
            json_body={
                "query": TAPS_QUERY,
                "variables": {"location": str(location_id), "statuses": STATUSES},
            },
        )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"Pourwall returned invalid JSON: {e}") from e
        entries = parse_pourwall_taps(payload)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no taps on the Pourwall menu")
        return build_listings(self.venue, entries, "pourwall", self.logger)
