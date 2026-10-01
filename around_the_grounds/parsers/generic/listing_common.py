"""Shared pieces for tap-list ("listing") parsers.

A tap-list parser extracts every entry it can find as a ``TapEntry``, then
``build_listings`` keeps the ones the venue's ``ListingMatcher`` accepts and
turns them into ``kind="listing"`` events.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import aiohttp

from ...models import Event, Venue
from ...utils.host_throttle import listing_throttle
from ...utils.listing_matcher import ListingMatcher
from ...utils.timezone_utils import now_in_site_timezone_naive

DEFAULT_TIMEZONE = "America/Los_Angeles"

# "6.5% ABV" first (so "5.4% ABV 35 IBU" is not read as 35), then
# "ABV: 6.80%" / "ABV | 6 | %", then a bare "5.9%".
_ABV_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*%\s*ABV", re.I),
    re.compile(r"ABV[:\s|]*(\d+(?:\.\d+)?)\s*%?", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*%"),
]


@dataclass
class TapEntry:
    name: str
    brewery: Optional[str] = None
    style: Optional[str] = None
    abv: Optional[str] = None
    # Extra text (e.g. a description) consulted for matching but not shown.
    match_text: Optional[str] = None
    # The beer's description, consulted only when the other fields don't
    # match, and only for each category's core words
    # (ListingMatcher.matches_description).
    description: Optional[str] = None


def normalize_abv(text: Optional[str]) -> Optional[str]:
    """Find an ABV in *text* and format it as "6.8%" (no trailing zeros)."""
    if not text:
        return None
    for pattern in _ABV_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"{float(match.group(1)):g}%"
    return None


async def fetch_listing_text(
    session: aiohttp.ClientSession,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """Fetch *url* politely and return its body, raising ValueError on failure.

    With *json_body*, POSTs it as JSON (for GraphQL APIs) instead of a GET.
    *headers* override the session's for this request.
    """
    await listing_throttle.wait(url)
    if json_body is None:
        request = session.get(url, params=params, headers=headers)
    else:
        request = session.post(url, params=params, json=json_body, headers=headers)
    try:
        async with request as response:
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
    """Keep entries matching any of the venue's categories as listing events.

    An entry matching several categories (a "Fresh Hop Festbier") yields one
    listing per category. Exact repeats are dropped; style is part of an
    entry's identity because a venue can pour two beers with the same name
    (Ravenna's "Wet Season: Amarillo" IPA and Hazy IPA).
    """
    matchers = ListingMatcher.for_venue(venue.parser_config)
    date = listing_date(venue)
    events: List[Event] = []
    seen = set()
    total = 0
    for entry in entries:
        total += 1
        details = [d for d in (entry.brewery, entry.style, entry.abv) if d]
        for matcher in matchers:
            fields = (entry.name, entry.style, entry.match_text)
            if not matcher.matches(*fields) and not matcher.matches_description(
                entry.description, *fields
            ):
                continue
            identity = tuple(
                (field or "").casefold()
                for field in (entry.name, entry.brewery, entry.style, matcher.category)
            )
            if identity in seen:
                continue
            seen.add(identity)
            events.append(
                Event(
                    venue_key=venue.key,
                    venue_name=venue.name,
                    title=entry.name,
                    date=date,
                    description=" · ".join(details) or None,
                    extraction_method=extraction_method,
                    kind="listing",
                    category=matcher.category,
                )
            )
    logger.info(f"{venue.name}: {len(events)} listings from {total} tap-list entries")
    return events
