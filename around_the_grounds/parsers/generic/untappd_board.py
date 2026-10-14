"""Tap lists published as Untappd for Business digital display boards.

A taproom's TV board lives at ``business.untappd.com/app/boards/<id>/page/1``
(Cooper Mountain links its boards from each pub page). The page is a script
app, but it arrives with the whole board as JSON in the ``data-react-props``
attribute of one element: its menus, their sections, and each item's name,
brewery, style, and ABV. This parser reads that JSON. business.untappd.com
answers the droplet; untappd.com venue pages do not, which is why the
untappd-venue parser cannot be used there.

Config (``source_type: "untappd-board"``)::

    "parser_config": {"board_id": 57393}

The venue ``url`` is the pub's own page, for people; it is not fetched.
Unpublished or draft menus and items marked hidden are skipped.
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup, Tag

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

BOARD_URL = "https://business.untappd.com/app/boards/{board_id}/page/1"


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _abv(value: Any) -> Optional[str]:
    try:
        abv = float(value)
    except (TypeError, ValueError):
        return None
    return f"{abv:g}%" if abv > 0 else None


def _item_entry(item: Dict[str, Any]) -> Optional[TapEntry]:
    if item.get("hidden"):
        return None
    name = _clean(item.get("name"))
    if not name:
        return None
    return TapEntry(
        name=name,
        brewery=_clean(item.get("brewery")),
        style=_clean(item.get("style")),
        abv=_abv(item.get("abv")),
        description=_clean(item.get("description")),
    )


def parse_untappd_board(html: str) -> List[TapEntry]:
    """TapEntries for every visible item on the board's published menus."""
    soup = BeautifulSoup(html, "html.parser")
    holder = soup.find(attrs={"data-react-props": True})
    if not isinstance(holder, Tag):
        raise ValueError("Untappd board page has no board data")
    try:
        props = json.loads(str(holder["data-react-props"]))
        menus = props["board"]["menus"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ValueError(f"Unexpected Untappd board data: {e}") from e
    if not isinstance(menus, list):
        raise ValueError("Unexpected Untappd board data: no menus")

    entries = []
    for menu in menus:
        if not isinstance(menu, dict) or menu.get("unpublished") or menu.get("draft"):
            continue
        for section in menu.get("sections") or []:
            if not isinstance(section, dict):
                continue
            for item in section.get("items") or []:
                entry = _item_entry(item) if isinstance(item, dict) else None
                if entry is not None:
                    entries.append(entry)
    return entries


class UntappdBoardParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        board_id = (self.venue.parser_config or {}).get("board_id")
        if not board_id:
            raise ValueError(f"{self.venue.key}: untappd-board needs board_id")
        html = await fetch_listing_text(session, BOARD_URL.format(board_id=board_id))
        entries = parse_untappd_board(html)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no items on the Untappd board")
        return build_listings(self.venue, entries, "untappd-board", self.logger)
