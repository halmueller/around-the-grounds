"""Events from a Squarespace events collection.

Squarespace serves any collection page as JSON with ``?format=json``. Events
carry ``startDate`` / ``endDate`` as epoch milliseconds (UTC); they are
converted to the venue's ``timezone`` (default Pacific) and made naive like
other parsers' times.

Config (``source_type: "squarespace-events"``): the venue ``url`` is the
collection page (e.g. ``https://www.fremontbrewing.com/fremont-ubg-events``).
Optional ``timezone``. Pair with ``event_filter`` / ``event_window_days`` to
keep only relevant upcoming events.
"""

import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import DEFAULT_TIMEZONE, fetch_listing_text

try:
    from zoneinfo import ZoneInfo  # type: ignore
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_DESCRIPTION_LIMIT = 240


def _plain(html: Optional[str]) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", html or ""))
    return " ".join(text.split())


def _local(epoch_ms: Any, zone: ZoneInfo) -> Optional[datetime]:
    if not isinstance(epoch_ms, (int, float)) or isinstance(epoch_ms, bool):
        return None
    moment = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return moment.astimezone(zone).replace(tzinfo=None, microsecond=0)


def _event_url(item: Dict[str, Any], base_url: str) -> Optional[str]:
    """The item's own page ("fullUrl" is site-relative), as an http(s) URL."""
    path = item.get("fullUrl")
    if not isinstance(path, str) or not path.strip() or not base_url:
        return None
    url = urljoin(base_url, path.strip())
    return url if url.startswith(("http://", "https://")) else None


def parse_squarespace_events(
    payload: Dict[str, Any],
    venue_key: str,
    venue_name: str,
    tz_name: str,
    base_url: str = "",
) -> List[Event]:
    zone = ZoneInfo(tz_name)
    seen = set()
    events: List[Event] = []
    # Collections list events under "upcoming"/"past" or a flat "items".
    for key in ("upcoming", "items", "past"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict) or item.get("id") in seen:
                continue
            seen.add(item.get("id"))
            title = " ".join(str(item.get("title") or "").split())
            start = _local(item.get("startDate"), zone)
            if not title or start is None:
                continue
            location = (item.get("location") or {}).get("addressTitle") or ""
            summary = _plain(item.get("excerpt")) or _plain(item.get("body"))
            if len(summary) > _DESCRIPTION_LIMIT:
                summary = summary[: _DESCRIPTION_LIMIT - 1].rstrip() + "…"
            details = [d for d in (location.strip(), summary) if d]
            events.append(
                Event(
                    venue_key=venue_key,
                    venue_name=venue_name,
                    title=title,
                    date=start,
                    start_time=start,
                    end_time=_local(item.get("endDate"), zone),
                    description=" · ".join(details) or None,
                    extraction_method="api",
                    url=_event_url(item, base_url),
                )
            )
    return events


class SquarespaceEventsParser(BaseParser):
    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        url = self.venue.url.split("?")[0]
        text = await fetch_listing_text(session, url, params={"format": "json"})
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Squarespace collection is not JSON: {url}") from e
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Squarespace JSON shape: {url}")
        return parse_squarespace_events(
            payload,
            self.venue.key,
            self.venue.name,
            config.get("timezone", DEFAULT_TIMEZONE),
            base_url=url,
        )
