"""Shared pieces for tap-list ("listing") parsers.

A tap-list parser extracts every entry it can find as a ``TapEntry``, then
``build_listings`` keeps the ones the venue's ``ListingMatcher`` accepts and
turns them into ``kind="listing"`` events.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import aiohttp

from ...models import Event, Venue
from ...utils.host_throttle import listing_throttle
from ...utils.listing_matcher import ListingMatcher
from ...utils.timezone_utils import now_in_site_timezone_naive

DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass
class TapEntry:
    name: str
    brewery: Optional[str] = None
    style: Optional[str] = None
    abv: Optional[str] = None


async def fetch_listing_text(
    session: aiohttp.ClientSession,
    url: str,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """Fetch *url* politely and return its body, raising ValueError on failure."""
    await listing_throttle.wait(url)
    try:
        async with session.get(url, params=params) as response:
            # Cloudflare marks bot challenges with this header; name them
            # explicitly since they depend on the client's IP/fingerprint.
            if response.headers.get("cf-mitigated", "").lower() == "challenge":
                raise ValueError(
                    f"Blocked by Cloudflare bot challenge "
                    f"(HTTP {response.status}): {url}"
                )
            if response.status == 404:
                raise ValueError(f"Page not found (404): {url}")
            if response.status == 403:
                raise ValueError(f"Access forbidden (403): {url}")
            if response.status == 429:
                raise ValueError(f"Rate limited (429): {url}")
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}: {url}")
            text = await response.text()
    except aiohttp.ClientError as e:
        raise ValueError(f"Network error fetching {url}: {e}") from e
    if not text.strip():
        raise ValueError(f"Empty response from: {url}")
    return text


def listing_date(venue: Venue) -> datetime:
    """Today's date (midnight, site-local) for a listing.

    Day granularity keeps generated output stable within a day, so an
    unchanged tap list does not trigger a new deploy.
    """
    tz_name = (venue.parser_config or {}).get("timezone", DEFAULT_TIMEZONE)
    return now_in_site_timezone_naive(tz_name).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def build_listings(
    venue: Venue,
    entries: Iterable[TapEntry],
    extraction_method: str,
    logger: logging.Logger,
) -> List[Event]:
    """Keep matching entries (deduplicated) as listing events."""
    matcher = ListingMatcher.from_config(venue.parser_config)
    date = listing_date(venue)
    events: List[Event] = []
    seen = set()
    total = 0
    for entry in entries:
        total += 1
        if not matcher.matches(entry.name, entry.style):
            continue
        identity = (entry.name.casefold(), (entry.brewery or "").casefold())
        if identity in seen:
            continue
        seen.add(identity)
        details = [d for d in (entry.brewery, entry.style, entry.abv) if d]
        events.append(
            Event(
                venue_key=venue.key,
                venue_name=venue.name,
                title=entry.name,
                date=date,
                description=" · ".join(details) or None,
                extraction_method=extraction_method,
                kind="listing",
            )
        )
    logger.info(f"{venue.name}: {len(events)} matching of {total} tap-list entries")
    return events
